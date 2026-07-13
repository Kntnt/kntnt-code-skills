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
 *     standardsPath?: string,                    // coding-standard directory the agents read
 *     maxFixRounds?: number,                     // fix<->verify cap per issue (default 2)
 *     merge?:  boolean,                          // integrate to the default branch, else open PRs
 *     budgetFloor?: number,                      // stop opening waves below this many tokens left
 *   }
 *
 * Returns { verdicts, parked } in the shape `orchestrate.py report` consumes:
 * the main session pipes them back to it to render the final report. An empty
 * or misdelivered plan instead returns { verdicts: [], parked: [], status:
 * 'empty-plan', warning } so a zero-agent run can never pass for a clean one.
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

// `normalizeArgs` and `planIsEmpty` are kept inline as plain internal `const`s
// because the Workflow harness rejects any top-level `export` beyond the single
// leading `export const meta` and forbids a top-level `import` — so this script
// cannot import them. Their tested source of truth is the byte-for-byte
// identical `lib/orchestrate/engine-helpers.mjs`; keep the two in sync.

/**
 * Normalize the raw `args` the Workflow harness delivers into the single config
 * object the engine reads every field off. The harness passes `args` as a JSON
 * string, but a hand-launched or already-parsed run passes an object; tolerate
 * both shapes. Anything absent or unparseable yields an empty plan so the
 * empty-plan guard below — not a thrown error — decides how to react.
 *
 * @param {string|object|undefined} raw The harness-delivered run config: a JSON
 *   string, an already-parsed object, or nothing.
 * @returns {object} The normalized config the engine consumes:
 *   `{ waves, issues, merge, maxFixRounds, standardsPath, budgetFloor }`.
 */
const normalizeArgs = (raw) => {

  // Tolerate a JSON string from the harness; a malformed string degrades to an
  // empty plan rather than throwing, so the loud empty-plan guard owns the
  // response. The boundary is untrusted: the harness contract is what bit us.
  if (typeof raw === 'string') {
    try {
      return JSON.parse(raw) ?? {}
    } catch {
      return {}
    }
  }

  return raw ?? {}

}

/**
 * True when a normalized plan has no waves to run. A zero-wave plan means the
 * run was misdelivered or scoped to nothing; the engine surfaces that loudly
 * rather than returning an empty success in milliseconds — the exact failure
 * mode that made a broken run masquerade as a clean one.
 *
 * @param {object} config A config from {@link normalizeArgs}.
 * @returns {boolean} Whether the plan would spawn no agents.
 */
const planIsEmpty = (config) => !Array.isArray(config.waves) || config.waves.length === 0

// Run options, with the conservative defaults the skill documents. Every field
// is read off the normalized config, never off the raw `args` the harness
// delivers as a JSON string.
const config = normalizeArgs(args)
const issuesByNumber = new Map((config.issues || []).map((issue) => [issue.number, issue]))
const maxFixRounds = config.maxFixRounds ?? 2
const standardsPath = config.standardsPath || 'agents.d/coding-standard/'

// How every sub-agent is told to reach the coding standard: a directory of
// on-demand modules, not a single file. Each agent reads general.md plus the
// module(s) for the language or framework it actually touches.
const standardInstruction =
  `the coding standard in \`${standardsPath}\` — read \`general.md\` plus the module(s) for the language or framework you touch`
const merge = config.merge === true
const budgetFloor = config.budgetFloor ?? 60000

// Title lookup for logging and report records.
const titleOf = (number) => issuesByNumber.get(number)?.title || `issue ${number}`

// The default verifier panel, used when planning has not annotated the issue:
// an independent correctness lens, a test-quality lens, and a security lens.
const DEFAULT_LENSES = [
  'correctness against the issue intent and its acceptance criteria',
  'test quality — is the red demonstrated, are the tests load-bearing, does every criterion map to a test',
  'security, error handling, and edge cases',
]

// The verifier panel for an issue. The orchestrator sets `lenses` per issue
// during planning, scaled to its real risk — one lens for a trivial change,
// the full panel plus a security lens for a write path, a permission gate, or
// an irreversible delete. A lens is a plain brief string, or a
// { brief, agentType } object to route to one of the project's own review
// agents (a silent-failure hunter, a test-coverage analyzer, …).
const lensesFor = (issue) => {
  const lenses = issue?.lenses
  return Array.isArray(lenses) && lenses.length > 0 ? lenses : DEFAULT_LENSES
}

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
      `Read and obey ${standardInstruction}.\n` +
      `Work on a fresh branch off the current integration base. Demonstrate the red — a failing-test commit — before the green, because a test never seen to fail is of unknown value. Refactor only once green.\n` +
      `Automate everything meaningfully automatable, then run the project's full gate suite (discover it from the project) and report the REAL result.\n` +
      `Resolve genuine ambiguity by the most reasonable assumption and record it; never pause to ask. The one exception is work that cannot proceed without contradicting a settled decision (an ADR or design doc): set status "blocked", record the blocker, and stop only this issue.`,
    { label: `implement:#${number}`, phase: 'Implement', schema: IMPLEMENT_SCHEMA, isolation: 'worktree' },
  )

// Re-dispatch the same kind of implementer to fix concrete findings, then it
// re-runs the gates and returns a fresh implement record.
const fix = (number, impl, findings) =>
  agent(
    `Fix issue #${number} ("${titleOf(number)}") on branch ${impl.branch}. Address ONLY these verified findings, keep the tests green, and obey ${standardInstruction}:\n` +
      findings.map((finding) => `- ${finding.title}: ${finding.detail}`).join('\n') +
      `\nThen re-run the full gate suite and report the real result.`,
    { label: `fix:#${number}`, phase: 'Implement', schema: IMPLEMENT_SCHEMA },
  )

// Run the adversarial panel concurrently; each reviewer gets one lens and only
// what the gates cannot prove.
const verify = async (number, impl) => {
  const lenses = lensesFor(issuesByNumber.get(number))
  const verdicts = await parallel(
    lenses.map((lens) => () => {
      // A lens is a brief string, or { brief, agentType } to use a named agent.
      const brief = typeof lens === 'string' ? lens : lens.brief
      const opts = { label: `verify:#${number}:${brief.split(' ')[0]}`, phase: 'Verify', schema: VERDICT_SCHEMA }
      if (typeof lens === 'object' && lens.agentType) opts.agentType = lens.agentType

      return agent(
        `Adversarially review branch ${impl.branch} for issue #${number} ("${titleOf(number)}") through ONE lens: ${brief}.\n` +
          `You did NOT write this code. Read the issue's Agent Brief (\`gh issue view ${number} --comments\`) and ${standardInstruction}.\n` +
          `Check ONLY what the gates cannot — do not re-check lint, build, or tests that already passed. Default to clear=false if you find anything real, and be specific.`,
        opts,
      )
    }),
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

  // A failed or missing integration parks the otherwise-green issue with its reason.
  if (result == null) return { ...record, status: 'parked', blockers: [...record.blockers, 'integrator returned nothing'] }
  if (!result.integrated) return { ...record, status: 'parked', blockers: [...record.blockers, result.blocker || result.summary] }
  return { ...record, verify: `${record.verify} | ${result.summary}` }
}

// Drive the waves: implement + verify a whole wave concurrently, then integrate
// its green issues serially so a real file conflict is rebased, not raced. A
// later wave depends on an earlier one, so the wave boundary is a real barrier.
const verdicts = []
const parked = []
const waves = config.waves || []

// Loud empty-plan guard: a misdelivered or empty plan must never masquerade as
// a successful zero-agent run completing in milliseconds. Surface it
// prominently and return a non-success status so the caller cannot mistake it
// for a legitimately empty scope.
if (planIsEmpty(config)) {
  log('WARNING: orchestrate received an empty plan (0 waves) — nothing to run. Verify that `args` reached the engine (a JSON string is parsed; an object is used as-is).')
  return { verdicts, parked, status: 'empty-plan', warning: 'No waves to run: the plan was empty or misdelivered.' }
}

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
    if (record.status !== 'done') {
      parked.push(record)
      continue
    }

    // Route by the integration outcome: a clean land is done, a conflict parks.
    const integrated = await integrate(record)
    if (integrated.status === 'done') verdicts.push(integrated)
    else parked.push(integrated)
  }
}

return { verdicts, parked }
