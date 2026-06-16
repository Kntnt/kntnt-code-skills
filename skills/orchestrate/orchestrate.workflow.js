/**
 * Engine for the `orchestrate` skill: the deterministic spine of an
 * away-from-keyboard, issue-to-code build, with every judgement delegated to
 * a sub-agent. The control flow — wave order, the fix<->verify cap, parallel
 * vs serial — is code here, so it cannot drift over a long unattended run.
 *
 * Launch it through the Workflow tool, never by hand:
 *
 *   Workflow({
 *     scriptPath: "${CLAUDE_PLUGIN_ROOT}/skills/orchestrate/orchestrate.workflow.js",
 *     args: <the plan JSON from `uv run scripts/orchestrate.py plan`, plus run options>,
 *   })
 *
 * Cost model: every agent() below runs as a sub-agent of the interactive
 * session that launched the workflow, so the work counts against the Max
 * subscription pool — never the headless `claude -p` credit. Nothing here
 * shells out to `claude`; the agents themselves run `gh`, `git`, and the
 * project's gates via their own tools.
 *
 * `args` shape:
 *   {
 *     waves:   number[][],                       // dispatch order; one wave runs concurrently
 *     issues:  { number, title, blocked_by }[],  // from orchestrate.py plan
 *     standardsPath?: string,                    // coding standard the agents read as a file
 *     maxFixRounds?: number,                     // fix<->verify cap per issue (default 2)
 *     merge?:  boolean,                          // integrate to the default branch, else open PRs
 *     budgetFloor?: number,                      // stop opening waves below this many tokens left
 *   }
 *
 * Returns { verdicts, parked } in the shape `orchestrate.py report` consumes:
 * the main session pipes them back to it to render the final report.
 */
export const meta = {
  name: 'orchestrate',
  description: 'AFK engine: implement -> independently verify -> integrate the planned issues',
  phases: [{ title: 'Implement' }, { title: 'Verify' }, { title: 'Integrate' }],
}

// What an implementer sub-agent returns: the branch it built, the demonstrated
// red/green commits, the real gate result, and its three-bucket report.
const IMPLEMENT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['branch', 'gatesPassed', 'status'],
  properties: {
    branch: { type: 'string' },
    redCommit: { type: 'string', description: 'SHA of the demonstrated failing-test commit' },
    greenCommit: { type: 'string', description: 'SHA of the commit that turns it green' },
    gatesPassed: { type: 'boolean' },
    gatesSummary: { type: 'string' },
    automaticallyTested: { type: 'array', items: { type: 'string' } },
    remainingForHuman: { type: 'array', items: { type: 'string' } },
    assumptions: { type: 'array', items: { type: 'string' } },
    blockers: { type: 'array', items: { type: 'string' } },
    status: { type: 'string', enum: ['green', 'blocked'] },
  },
}

// What one verifier lens returns: clear, or a list of real findings to fix.
const VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['clear', 'summary'],
  properties: {
    clear: { type: 'boolean', description: 'true when nothing real needs fixing' },
    summary: { type: 'string' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['title', 'detail'],
        properties: {
          title: { type: 'string' },
          detail: { type: 'string' },
          severity: { type: 'string', enum: ['low', 'medium', 'high'] },
        },
      },
    },
  },
}

// What an integrator sub-agent returns: whether it landed, and why not.
const INTEGRATE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['integrated', 'summary'],
  properties: {
    integrated: { type: 'boolean' },
    summary: { type: 'string' },
    blocker: { type: 'string' },
  },
}

// Run options, with the conservative defaults the skill documents.
const issuesByNumber = new Map((args.issues || []).map((issue) => [issue.number, issue]))
const maxFixRounds = args.maxFixRounds ?? 2
const standardsPath = args.standardsPath || 'docs/coding-standards.md'
const merge = args.merge === true
const budgetFloor = args.budgetFloor ?? 60000

// Title lookup for logging and report records.
const titleOf = (number) => issuesByNumber.get(number)?.title || `issue ${number}`

// The verifier panel for an issue. EXTENSION POINT: scale to the issue's real
// risk and use the project's own review agents (a silent-failure hunter, a
// test-coverage analyzer, a type-design analyzer) via opts.agentType where they
// exist. The default panel gives every issue an independent correctness lens
// plus test-quality and security lenses; prune for a trivial change.
const lensesFor = (_issue) => [
  'correctness against the issue intent and its acceptance criteria',
  'test quality — is the red demonstrated, are the tests load-bearing, does every criterion map to a test',
  'security, error handling, and edge cases',
]

// Shape an implementer result plus its verify outcome into the record that
// orchestrate.py report consumes.
const toRecord = (number, impl, status, verify) => ({
  number,
  title: titleOf(number),
  status,
  gates: impl?.gatesSummary || (impl?.gatesPassed ? 'green' : 'unknown'),
  verify: verify || '',
  remaining_for_human: impl?.remainingForHuman || [],
  assumptions: impl?.assumptions || [],
  blockers: impl?.blockers || [],
})

// Dispatch one implementer on its own worktree-isolated branch, test-first.
const implement = (number) =>
  agent(
    `Implement GitHub issue #${number} ("${titleOf(number)}") test-first.\n` +
      `Read its contract first: run \`gh issue view ${number} --comments\` and treat the "Agent Brief" comment as authoritative; the issue body and acceptance criteria are context.\n` +
      `Read and obey the coding standard at ${standardsPath}.\n` +
      `Work on a fresh branch off the current integration base. Demonstrate the red — a failing-test commit — before the green, because a test never seen to fail is of unknown value. Refactor only once green.\n` +
      `Automate everything meaningfully automatable, then run the project's full gate suite (discover it from the project) and report the REAL result.\n` +
      `Resolve genuine ambiguity by the most reasonable assumption and record it; never pause to ask. The one exception is work that cannot proceed without contradicting a settled decision (an ADR or design doc): set status "blocked", record the blocker, and stop only this issue.`,
    { label: `implement:#${number}`, phase: 'Implement', schema: IMPLEMENT_SCHEMA, isolation: 'worktree' },
  )

// Re-dispatch the same kind of implementer to fix concrete findings, then it
// re-runs the gates and returns a fresh implement record.
const fix = (number, impl, findings) =>
  agent(
    `Fix issue #${number} ("${titleOf(number)}") on branch ${impl.branch}. Address ONLY these verified findings, keep the tests green, and obey ${standardsPath}:\n` +
      findings.map((finding) => `- ${finding.title}: ${finding.detail}`).join('\n') +
      `\nThen re-run the full gate suite and report the real result.`,
    { label: `fix:#${number}`, phase: 'Implement', schema: IMPLEMENT_SCHEMA },
  )

// Run the adversarial panel concurrently; each reviewer gets one lens and only
// what the gates cannot prove.
const verify = async (number, impl) => {
  const lenses = lensesFor(issuesByNumber.get(number))
  const verdicts = await parallel(
    lenses.map((lens) => () =>
      agent(
        `Adversarially review branch ${impl.branch} for issue #${number} ("${titleOf(number)}") through ONE lens: ${lens}.\n` +
          `You did NOT write this code. Read the issue's Agent Brief (\`gh issue view ${number} --comments\`) and the standard at ${standardsPath}.\n` +
          `Check ONLY what the gates cannot — do not re-check lint, build, or tests that already passed. Default to clear=false if you find anything real, and be specific.`,
        { label: `verify:#${number}:${lens.split(' ')[0]}`, phase: 'Verify', schema: VERDICT_SCHEMA },
      ),
    ),
  )
  return verdicts.filter(Boolean)
}

// Build one issue, then loop fix<->verify until clear or the cap is hit.
const buildAndVerify = async (number) => {
  let impl = await implement(number)

  // A dead or blocked implementer parks the issue without a verify pass.
  if (impl == null) return toRecord(number, null, 'parked', 'implementer returned nothing')
  if (impl.status === 'blocked') return toRecord(number, impl, 'blocked', 'design blocker')

  // Capped fix<->verify loop: a stubborn issue parks rather than looping forever.
  for (let round = 0; ; round += 1) {
    const verdicts = await verify(number, impl)
    const findings = verdicts.flatMap((verdict) => (verdict.clear ? [] : verdict.findings || []))
    const summary = verdicts.map((verdict) => verdict.summary).join(' | ')
    if (findings.length === 0) return toRecord(number, impl, 'done', summary)
    if (round >= maxFixRounds) return toRecord(number, impl, 'parked', `cap hit after ${round} round(s): ${summary}`)

    log(`#${number}: fix round ${round + 1}/${maxFixRounds} — ${findings.length} finding(s)`)
    impl = (await fix(number, impl, findings)) ?? impl
  }
}

// Integrate one green issue: open a PR by default, or merge with rebase when the
// run is authorized to. Integration is the one outward-facing, irreversible step.
const integrate = async (record) => {
  const action = merge
    ? `Rebase branch ${record.branch} onto the up-to-date default branch, then fast-forward merge it. If the rebase hits a conflict you cannot resolve safely, do NOT merge — report it as a blocker.`
    : `Open a pull request for branch ${record.branch} against the default branch. Do NOT merge.`
  const result = await agent(
    `Integrate issue #${record.number} ("${record.title}"). ${action} Report what you did in one line.`,
    { label: `integrate:#${record.number}`, phase: 'Integrate', schema: INTEGRATE_SCHEMA },
  )

  // A failed integration parks the otherwise-green issue with its reason.
  if (result == null) return { ...record, verify: `${record.verify} | integration returned nothing` }
  if (!result.integrated) return { ...record, status: 'parked', blockers: [...record.blockers, result.blocker || result.summary] }
  return { ...record, verify: `${record.verify} | ${result.summary}` }
}

// Drive the waves: implement + verify a whole wave concurrently, then integrate
// its green issues serially so a real file conflict is rebased, not raced. A
// later wave depends on an earlier one, so the wave boundary is a real barrier.
const verdicts = []
const parked = []
const waves = args.waves || []

for (let index = 0; index < waves.length; index += 1) {
  const wave = waves[index]
  log(`Wave ${index + 1}/${waves.length}: #${wave.join(', #')}`)

  // Stop opening new waves once the turn's token target is nearly spent; park
  // the rest so the run ends with a clean report instead of a hard cut-off.
  if (budget.total && budget.remaining() < budgetFloor) {
    for (const number of wave) parked.push(toRecord(number, null, 'parked', 'token budget exhausted before dispatch'))
    continue
  }

  // Implement and verify every issue in the wave at once (worktree-isolated).
  const built = (await parallel(wave.map((number) => () => buildAndVerify(number)))).filter(Boolean)

  // Integrate the green ones in issue order; park everything else for the report.
  for (const record of built.sort((a, b) => a.number - b.number)) {
    if (record.status === 'done') verdicts.push(await integrate(record))
    else parked.push(record)
  }
}

return { verdicts, parked }
