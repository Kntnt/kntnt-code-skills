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

// Worktree-isolation rule: every code-touching agent — implement and fix here,
// and any future salvage/hotfix agent (issue #18) — MUST carry
// `isolation: 'worktree'` in its opts, so no two agents, and no agent and the
// launcher, ever share a working directory. Sharing one tree let an agent's
// uncommitted changes park the next issue, and a left-behind worktree locked a
// branch a later run could not rebase. Read-only verifiers need no worktree;
// integrate is deliberately un-isolated because it is the SOLE mutator of the
// real default branch. End-of-run teardown removes exactly the worktrees this
// run created (see `builtBranches` and the `finally` block below).

// The shared safe-state contract every code-touching sub-agent is bound by:
// what it may NEVER do to shared state — close the GitHub issue, push, merge, or
// run destructive git that can lose committed work — and the ONE non-destructive
// recipe for reaching a clean tree. Defined ONCE and interpolated into every
// implement, fix, and verify prompt (and any future salvage/hotfix agent — issue
// #18 — MUST include it too) rather than copy-pasted, so the rule cannot drift
// between agents. Deliberately NOT interpolated into `integrate`, whose whole job
// is to merge and push; `teardown` already carries its own no-delete/no-reset
// rule and does not merge, so it needs no addition here.
const AGENT_CONSTRAINTS = `Shared-state rules — these bind you; obey them without exception:\n` +
  `- You must NOT close the GitHub issue, NOT push to any remote, and NOT merge into the default branch. Closing, pushing, and merging are the orchestrator's and the integrate step's job exclusively; the issue is closed only after independent verification, never by you.\n` +
  `- NEVER run \`git reset --hard <ref>\` while HEAD is on a feature branch — it silently discards that branch's commits.\n` +
  `- The ONE safe way to reach a clean state: if a rebase or merge is in progress, abort it (\`git rebase --abort\` / \`git merge --abort\`); then \`git checkout -f <the integration base>\` and discard only working-tree changes to TRACKED files with \`git checkout -- .\`. Never delete untracked files.`

// Dispatch one implementer on its own worktree-isolated branch, test-first.
const implement = (number) =>
  agent(
    `Implement GitHub issue #${number} ("${titleOf(number)}") test-first.\n` +
      `Read its contract first: run \`gh issue view ${number} --comments\` and treat the "Agent Brief" comment as authoritative; the issue body and acceptance criteria are context.\n` +
      `Read and obey ${standardInstruction}.\n` +
      `${AGENT_CONSTRAINTS}\n` +
      `Work on a fresh branch off the current integration base. Demonstrate the red — a failing-test commit — before the green, because a test never seen to fail is of unknown value. Refactor only once green.\n` +
      `Automate everything meaningfully automatable, then run the project's full gate suite (discover it from the project) and report the REAL result.\n` +
      `Resolve genuine ambiguity by the most reasonable assumption and record it; never pause to ask. The one exception is work that cannot proceed without contradicting a settled decision (an ADR or design doc): set status "blocked", record the blocker, and stop only this issue.`,
    { label: `implement:#${number}`, phase: 'Implement', schema: IMPLEMENT_SCHEMA, isolation: 'worktree' },
  )

// Re-dispatch the same kind of implementer to fix concrete findings, then it
// re-runs the gates and returns a fresh implement record.
const fix = (number, impl, findings) =>
  agent(
    `Fix issue #${number} ("${titleOf(number)}") on branch ${impl.branch}.\n` +
      `You are in a FRESH isolated worktree, but branch ${impl.branch} is still checked out in another worktree (the implementer's, now defunct, or a previous fix round's), and git refuses to check out one branch in two worktrees at once. BEFORE anything else, take the branch over:\n` +
      `1. Run \`git worktree list --porcelain\` and find any OTHER worktree that currently has ${impl.branch} checked out.\n` +
      `2. If one exists, run \`git worktree remove --force <that path>\` to free it. \`remove\` KEEPS the branch ref, so ${impl.branch}'s commits survive — NEVER run \`git branch -D\` (or any branch delete) and NEVER \`git reset --hard\`.\n` +
      `3. Now check out ${impl.branch} in your own worktree and do all the work here.\n` +
      `${AGENT_CONSTRAINTS}\n` +
      `Address ONLY these verified findings, keep the tests green, and obey ${standardInstruction}:\n` +
      findings.map((finding) => `- ${finding.title}: ${finding.detail}`).join('\n') +
      `\nCommit on ${impl.branch}, then re-run the full gate suite and report the real result.`,
    { label: `fix:#${number}`, phase: 'Implement', schema: IMPLEMENT_SCHEMA, isolation: 'worktree' },
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
          `${AGENT_CONSTRAINTS}\n` +
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

  // Record the feature branch this run built. Every such branch was checked out
  // in the implementer's isolated worktree; the set is the exact, precise list
  // the end-of-run teardown removes worktrees for — nothing the run did not
  // create is ever touched. Recorded even for a blocked implementer, which still
  // ran in a worktree on its branch.
  if (impl.branch) builtBranches.add(impl.branch)

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

// Integrate one green issue: open a PR by default, or land it on the default
// branch with a linear rebase-then-fast-forward when the run is authorized to.
// Integration is the one outward-facing, irreversible step.
const integrate = async (record) => {
  const action = merge
    ? `Rebase branch ${record.branch} onto the up-to-date default branch, then fast-forward the default branch to it — fast-forward ONLY. ` +
      `Keep the integrated history LINEAR: NEVER merge the default branch INTO the feature branch, and NEVER create a merge commit on the feature branch. ` +
      `If the rebase hits a conflict you cannot resolve safely, do NOT merge — report it as a blocker.`
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

// Drive the waves in dependency order, processing issues SERIALLY and
// integrating each green one the MOMENT it goes green — before the next issue's
// work begins. This makes partial progress durable: each verified-green issue
// lands on the default branch immediately (rebase-then-fast-forward), so a
// mid-run stop — a spend-limit cut-off, a crash — leaves every issue integrated
// so far on the default branch and nothing already-completed is lost. Ordering
// (waves in order, issue numbers within a wave in order) still guarantees a
// dependent issue builds on an already-integrated prerequisite; worktree
// isolation (#14) keeps concurrent agents apart, so serial dispatch is safe.
const verdicts = []
const parked = []
const waves = config.waves || []

// The feature branches this run built, one per implementer worktree. This is the
// exact, precise identity of the worktrees the run created; the end-of-run
// teardown removes only worktrees checked out to one of these branches. Empty
// when the run created no worktree (e.g. the empty-plan early return), so
// teardown is then a skipped no-op.
const builtBranches = new Set()

// Loud empty-plan guard: a misdelivered or empty plan must never masquerade as
// a successful zero-agent run completing in milliseconds. Surface it
// prominently and return a non-success status so the caller cannot mistake it
// for a legitimately empty scope.
if (planIsEmpty(config)) {
  log('WARNING: orchestrate received an empty plan (0 waves) — nothing to run. Verify that `args` reached the engine (a JSON string is parsed; an object is used as-is).')
  return { verdicts, parked, status: 'empty-plan', warning: 'No waves to run: the plan was empty or misdelivered.' }
}

// Everything from here runs inside a `try` whose `finally` always tears down the
// worktrees this run created — on the clean-completion path, on the
// parked/blocked path, and even if the body throws. The teardown is the last
// thing the run does before returning its report.
try {
  for (let index = 0; index < waves.length; index += 1) {
    const wave = waves[index]
    log(`Wave ${index + 1}/${waves.length}: #${wave.join(', #')}`)

    // Process the wave's issues one at a time, in issue-number order, each built
    // and — when green — integrated before the next issue's build begins.
    for (const number of [...wave].sort((a, b) => a - b)) {

      // Stop dispatching once the turn's token target is nearly spent; park this
      // issue without dispatching. The budget only falls, so every later issue is
      // parked too, and the run ends with a clean report instead of a hard cut-off.
      if (budget.total && budget.remaining() < budgetFloor) {
        parked.push(toRecord(number, null, 'parked', 'token budget exhausted before dispatch'))
        continue
      }

      // Build + independently verify this one issue (worktree-isolated).
      const record = await buildAndVerify(number)
      if (record == null) continue
      if (record.status !== 'done') {
        parked.push(record)
        continue
      }

      // Land it NOW, before the next issue's build starts: a clean rebase-then-
      // fast-forward is done, a conflict parks it. Because the land happens here,
      // inline, a stop after this point still leaves this issue on the default
      // branch — the durability property the batched design lacked.
      const integrated = await integrate(record)
      if (integrated.status === 'done') verdicts.push(integrated)
      else parked.push(integrated)
    }
  }
} finally {
  // Teardown: remove exactly the worktrees this run created, preserving every
  // branch ref, whether the run finished cleanly or left issues parked/blocked.
  // Dispatch only when the run actually created a worktree — `builtBranches` is
  // empty on the empty-plan early return, so this is then a skipped no-op. The
  // teardown agent is deliberately NOT worktree-isolated: it must act on the
  // real repository's worktree admin, not a throwaway copy of it.
  if (builtBranches.size > 0) {
    const branches = [...builtBranches]
    await agent(
      `Tear down the git worktrees this orchestrate run created, and ONLY those. Act on the real repository — you are NOT in an isolated worktree.\n` +
        `The run built exactly these feature branches, each checked out in its own throwaway worktree:\n` +
        branches.map((branch) => `- ${branch}`).join('\n') +
        `\nRun \`git worktree list --porcelain\` to enumerate every worktree. For each worktree whose checked-out branch is one of the branches listed above, run \`git worktree remove --force <path>\`; \`remove\` KEEPS the branch ref, which is exactly what we want. Finish with \`git worktree prune\`.\n` +
        `NEVER remove the main worktree (the repository's primary checkout) and NEVER remove a worktree whose branch is not in the list above — those were not created by this run. You MUST preserve every branch ref: do NOT run \`git branch -D\` (or any branch delete), and do NOT run \`git reset --hard\`. Removing a worktree must leave its branch ref intact, so the integrated history and every parked branch survive for the report and any human follow-up.\n` +
        `Report in one line how many worktrees you removed.`,
      { label: 'teardown:worktrees', phase: 'Integrate' },
    )
  }
}

return { verdicts, parked }
