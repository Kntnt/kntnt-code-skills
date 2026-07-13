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
 *     maxFixRounds?: number,                     // fix<->verify cap per issue (default 1)
 *     maxIntegrationRounds?: number,             // integration-review hotfix cap (default maxFixRounds)
 *     merge?:  boolean,                          // integrate to the default branch, else open PRs
 *     budgetFloor?: number,                      // stop opening waves below this many tokens left
 *   }
 *
 * Returns { verdicts, parked, integration } in the shape `orchestrate.py report`
 * consumes: the main session pipes the verdicts/parked records back to it to
 * render the final report, and `integration` carries the mandatory final
 * integration review's outcome ({ cleared, ... } or null when nothing was
 * integrated). An empty or misdelivered plan instead returns { verdicts: [],
 * parked: [], status: 'empty-plan', warning } so a zero-agent run can never pass
 * for a clean one.
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

// `normalizeArgs`, `planIsEmpty`, `blockingFindings`, and `unlandedPrerequisites`
// are kept inline as plain internal `const`s because the Workflow harness rejects
// any top-level `export` beyond the single leading `export const meta` and forbids
// a top-level `import` — so this script cannot import them. Their tested source of
// truth is the byte-for-byte identical `lib/orchestrate/engine-helpers.mjs`; keep
// the two in sync.

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

/**
 * The findings that must BLOCK integration, given a verifier panel's verdicts.
 * Integration proceeds only when this returns an empty array, which requires at
 * least one verdict AND every verdict explicitly cleared. This closes two silent-
 * integration escapes the lean single-lens default would otherwise widen: an
 * empty panel (a dead verifier `.filter(Boolean)`-ed down to nothing) is never
 * "done", and a not-clear verdict that carries no `findings` array still blocks.
 *
 * @param {Array<{clear?: boolean, summary?: string, findings?: object[]}>} verdicts
 *   The verdicts a verify pass produced (already Boolean-filtered).
 * @returns {object[]} The blocking findings; empty only when the change is
 *   explicitly cleared for integration.
 */
const blockingFindings = (verdicts) => {

  // An empty or missing panel is never "done": the verifier did not run, so the
  // change is unverified and must not integrate.
  if (!Array.isArray(verdicts) || verdicts.length === 0) {
    return [{ title: 'verification did not run', detail: 'the verifier returned no verdict; the change is unverified' }]
  }

  // Only an explicit clear=true contributes nothing. Any other verdict blocks:
  // its own findings when it listed them, else one synthesized from its summary,
  // so a "not clear" verdict with no findings array cannot slip through as done.
  return verdicts.flatMap((verdict) => {
    if (verdict.clear === true) return []
    const findings = verdict.findings || []
    return findings.length > 0
      ? findings
      : [{ title: 'unresolved', detail: verdict.summary || 'reviewer did not clear the change' }]
  })

}

/**
 * The in-scope prerequisites of an issue that have NOT yet landed — the reason to
 * skip (park) it rather than build it on an incomplete base. A dependent must
 * build on a base that already contains its prerequisites; when a prerequisite
 * parked, blocked, or failed to integrate it is absent from `landed`, so building
 * the dependent would sit it on a base missing that work. Only IN-SCOPE
 * prerequisites count: a `blocked_by` entry outside this run's plan is assumed
 * already present on the default branch and never blocks. Returning the unlanded
 * numbers (not a bare boolean) lets the caller name them in the park reason and
 * drives the cascade — a skipped issue never enters `landed`, so its own
 * dependents find it unlanded here and skip in turn, transitively.
 *
 * @param {number[]|undefined} blockedBy The issue's `blocked_by` numbers, in- and
 *   out-of-scope alike.
 * @param {{has: (n: number) => boolean}} inScope Membership of this run's plan;
 *   only `.has` is used, so the engine's `issuesByNumber` Map serves directly.
 * @param {Set<number>} landed The numbers of the issues that have integrated.
 * @returns {number[]} The in-scope prerequisites still missing from `landed`;
 *   empty when the issue is clear to build.
 */
const unlandedPrerequisites = (blockedBy, inScope, landed) => {

  // Keep only the blockers that are BOTH in this run's scope and not yet landed.
  // An out-of-scope blocker is assumed already on the default branch; an in-scope
  // one that has not integrated would leave this issue on an incomplete base.
  return (blockedBy || []).filter((prereq) => inScope.has(prereq) && !landed.has(prereq))

}

// Run options, with the conservative defaults the skill documents. Every field
// is read off the normalized config, never off the raw `args` the harness
// delivers as a JSON string.
const config = normalizeArgs(args)
const issuesByNumber = new Map((config.issues || []).map((issue) => [issue.number, issue]))
const maxFixRounds = config.maxFixRounds ?? 1

// The cap on the mandatory integration review's hotfix loop: how many times a
// cross-issue finding may be hotfixed and the combined diff re-reviewed before
// the finding is parked for a human rather than looping. Defaults to
// `maxFixRounds` (itself 1), so the integration stage is bounded exactly as a
// per-issue fix loop is; a run can raise it via `maxIntegrationRounds`.
const maxIntegrationRounds = config.maxIntegrationRounds ?? maxFixRounds
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
// a SINGLE broad adversarial reviewer that folds every lean-verification concern
// into one lens — correctness against the issue intent and its acceptance
// criteria, the quality of the tests, and any security or data-safety hazard the
// issue touches. One agent, not three. Planning raises this to 2–3 focused lenses
// ONLY for a genuinely high-risk issue, via the per-issue `lenses` override below.
const DEFAULT_LENSES = [
  'correctness against the issue intent and its acceptance criteria, the quality of the tests (is the red demonstrated, are the tests load-bearing, does every acceptance criterion map to a test), AND any security or data-safety hazard the issue touches — review all of these together through one broad adversarial lens',
]

// The verifier panel for an issue. The default is the single broad adversarial
// reviewer in DEFAULT_LENSES; planning overrides it per issue by setting
// `lenses`, scaled to real risk — the orchestrator raises a genuinely high-risk
// issue (a write path, a permission gate, an irreversible delete) to 2–3 focused
// lenses. A lens is a plain brief string, or a { brief, agentType } object to
// route to one of the project's own review agents (a silent-failure hunter, a
// test-coverage analyzer, …).
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
  branch: impl?.branch,
  gates: impl?.gatesSummary || (impl?.gatesPassed ? 'green' : 'unknown'),
  verify: verify || '',
  remaining_for_human: impl?.remainingForHuman || [],
  assumptions: impl?.assumptions || [],
  blockers: impl?.blockers || [],
})

// Worktree-isolation rule: every code-touching agent — implement and fix here,
// and the integration hotfix (issue #18) — MUST carry
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
// implement, fix, verify, and re-verify prompt — and the integration hotfix
// (issue #18) — rather than copy-pasted, so the rule cannot drift
// between agents. Deliberately NOT interpolated into `integrate`, whose whole job
// is to land each green issue on the default branch (fast-forward the default to
// the feature tip, without checking out the worktree-locked feature branch);
// pushing that branch to a remote is the orchestrator's separate authorised step,
// not integrate's. `teardown` already carries its own no-delete/no-reset rule and
// does not integrate, so it needs no addition here.
const AGENT_CONSTRAINTS = `Shared-state rules — these bind you; obey them without exception:\n` +
  `- You must NOT close the GitHub issue, NOT push to any remote, and NOT merge into the default branch. Closing, pushing, and merging are the orchestrator's and the integrate step's job exclusively; the issue is closed only after independent verification, never by you.\n` +
  `- NEVER run \`git reset --hard <ref>\` while HEAD is on a feature branch — it silently discards that branch's commits.\n` +
  `- The ONE safe way to reach a clean state: if a rebase or merge is in progress, abort it (\`git rebase --abort\` / \`git merge --abort\`); then \`git checkout -f <the integration base>\` and discard only working-tree changes to TRACKED files with \`git checkout -- .\`. Never delete untracked files.`

// Dispatch one implementer on its own worktree-isolated branch, test-first.
const implement = (number) =>
  agent(
    `Implement GitHub issue #${number} ("${titleOf(number)}") test-first.\n` +
      `Read its contract first: run \`gh issue view ${number} --comments\`. If an Agent Brief comment exists it is authoritative; OTHERWISE the issue body and its acceptance criteria ARE the contract — build from them and never stall for a missing brief.\n` +
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
          `You did NOT write this code. Read the issue's contract (\`gh issue view ${number} --comments\`; if an Agent Brief comment exists it is authoritative, OTHERWISE the issue body and its acceptance criteria are the contract) and ${standardInstruction}.\n` +
          `${AGENT_CONSTRAINTS}\n` +
          `Check ONLY what the gates cannot — do not re-check lint, build, or tests that already passed. Default to clear=false if you find anything real, and be specific.`,
        opts,
      )
    }),
  )
  return verdicts.filter(Boolean)
}

// Re-verify ONLY the findings a fix round just addressed — a single targeted
// adversarial agent, NOT the whole panel. This is the biggest cost multiplier
// removed: after the initial panel runs once, each fix round costs one re-verify
// agent instead of re-dispatching every lens. It confirms each listed finding is
// properly resolved and that no regression crept into those specific areas, and
// returns the same VERDICT_SCHEMA a lens does. Like `verify`, it is a read-only
// reviewer that did NOT write the code (so it needs no worktree) and is bound by
// the shared ${AGENT_CONSTRAINTS}: it must not push, merge, or close the issue.
const reverifyFindings = (number, impl, findings) =>
  agent(
    `Adversarially re-verify branch ${impl.branch} for issue #${number} ("${titleOf(number)}") after a fix round.\n` +
      `A previous fix round was asked to address EXACTLY these findings; review ONLY whether each is now properly resolved and that no regression crept into those specific areas — do NOT re-review the whole change or re-run the full verifier panel:\n` +
      findings.map((finding) => `- ${finding.title}: ${finding.detail}`).join('\n') +
      `\nYou did NOT write this code. Read the issue's contract (\`gh issue view ${number} --comments\`; if an Agent Brief comment exists it is authoritative, OTHERWISE the issue body and its acceptance criteria are the contract) and ${standardInstruction}.\n` +
      `${AGENT_CONSTRAINTS}\n` +
      `Check ONLY what the gates cannot — do not re-check lint, build, or tests that already passed. Return clear=true only when every listed finding is resolved with no new problem in those areas; otherwise clear=false with the specific findings still unresolved or newly regressed.`,
    { label: `reverify:#${number}`, phase: 'Verify', schema: VERDICT_SCHEMA },
  )

// Build one issue, then verify once and — if needed — fix and targeted re-verify
// up to the cap.
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

  // Initial verification: the full verifier panel runs EXACTLY ONCE, after green.
  // Integration proceeds ONLY when the panel explicitly cleared — blockingFindings
  // treats an empty panel (a dead verifier) and a not-clear-without-findings verdict
  // as blocking, so a change never integrates unverified on either escape.
  const verdicts = await verify(number, impl)
  let summary = verdicts.map((verdict) => verdict.summary).join(' | ')
  let findings = blockingFindings(verdicts)
  if (findings.length === 0) return toRecord(number, impl, 'done', summary)

  // Capped fix loop: fix the concrete findings, then RE-VERIFY ONLY THOSE FIXED
  // FINDINGS with a single targeted agent — never the whole panel again. That
  // targeted re-verify is the cost saving over re-running every lens each round.
  // A stubborn issue parks rather than looping forever.
  for (let round = 1; round <= maxFixRounds; round += 1) {
    log(`#${number}: fix round ${round}/${maxFixRounds} — ${findings.length} finding(s)`)
    impl = (await fix(number, impl, findings)) ?? impl

    // A dead re-verifier never clears the issue: keep the prior findings
    // unresolved so the next round re-fixes them, or the cap parks the issue —
    // it never integrates unconfirmed. A live verdict is judged by blockingFindings,
    // symmetric with the initial pass, so a not-clear-without-findings still blocks.
    const recheck = await reverifyFindings(number, impl, findings)
    if (recheck == null) continue
    summary = recheck.summary || summary
    findings = blockingFindings([recheck])
    if (findings.length === 0) return toRecord(number, impl, 'done', summary)
  }

  return toRecord(number, impl, 'parked', `cap hit after ${maxFixRounds} fix round(s): ${summary}`)
}

// Integrate one green issue: open a PR by default, or land it on the default
// branch when the run is authorized to — by fast-forwarding the default branch
// to the feature branch's tip WITHOUT checking out the worktree-locked feature
// branch. Integration is the one outward-facing, irreversible step.
const integrate = async (record) => {
  const action = merge
    ? `Land branch ${record.branch} on the default branch by fast-forwarding the DEFAULT branch to that branch's tip, WITHOUT ever checking out ${record.branch}. ${record.branch} is still checked out in the implementer's (or a fix round's) persisted worktree, and git refuses to check out one branch in two worktrees at once, so checking it out here would fail mechanically for a non-conflict reason. From the default branch, run \`git merge --ff-only ${record.branch}\` — this advances the default to the feature tip and creates NO merge commit. ` +
      `Keep the integrated history LINEAR: NEVER merge the default branch INTO the feature branch, and NEVER create a merge commit on the feature branch. ` +
      `In the serial integrate-immediately design nothing landed between ${record.branch}'s build and now, so it is already a fast-forward ahead of the default and \`--ff-only\` succeeds with no rebase replay. Only in the rare case the default moved under the feature branch will the fast-forward be refused; that is the one case a genuine rebase is needed — perform it WITHOUT checking out ${record.branch} while a worktree still holds it: free that worktree first with \`git worktree remove --force <path>\` (which KEEPS the branch ref), exactly as the fix-round handoff does, then rebase ${record.branch} onto the default and fast-forward the default to its tip. That rebase checks ${record.branch} out in THIS worktree — the main, un-isolated, only default-branch checkout — so when the fast-forward is done, return this worktree to the default branch (\`git checkout <default>\`), leaving integrate on the default branch and never stranded on ${record.branch}. ` +
      `If a genuine conflict makes that rebase unsafe to resolve, do NOT merge — report it as a blocker.`
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

// The MANDATORY final integration review: ONE adversarial reviewer over the real
// combined change set of everything this run produced. A per-issue verifier sees
// one issue in isolation and structurally CANNOT catch a cross-issue defect — one
// issue's change silently weakening another's guarantee, two issues contradicting
// each other, an invariant that holds per issue but breaks across their union. So
// this reviewer is given the SAME rigor as a per-issue verifier, NOT a token
// smoke test, and hunts exactly that class of defect. It is MODE-AWARE, because
// where the change set lives depends on the run's mode: in MERGE mode everything
// landed on the default branch, so it reviews the combined diff there; in the
// conservative PR mode NOTHING landed on the default branch (each issue is a PR),
// so it must review the UNION of the run's feature branches against the default
// branch instead — the engine knows those branches (`verdict.branch`) and passes
// them in. Reviewing "the default branch" in PR mode would see nothing and clear
// — the exact silent pass this review exists to kill, in the default mode. It did
// NOT write any of the code, is read-only (no worktree), carries the shared
// ${AGENT_CONSTRAINTS}, and returns the same VERDICT_SCHEMA a verifier does — so
// its clear decision runs through `blockingFindings` just like a per-issue
// verdict and a dead / not-clear / empty-findings review can never pass.
const integrationReview = (verdicts) => {
  const target = merge
    ? `the COMBINED diff now on the default branch — everything this run landed there`
    : `the UNION of this run's feature branches against the default branch (this run opened PRs and landed NOTHING on the default branch, so review the branches themselves, together): ${verdicts.map((verdict) => verdict.branch).join(', ')}`
  return agent(
    `Adversarially review ${target} — issues ${verdicts.map((verdict) => `#${verdict.number}`).join(', ')} TOGETHER, as one union, NOT any single issue on its own.\n` +
      `Give this the SAME rigor as a per-issue verifier — this is NOT a smoke test. Hunt for CROSS-issue defects that no per-issue review could see: one issue's change silently weakening another's guarantee, two changes contradicting each other, a broken invariant across their union, a gate that passes per issue but not over the combined whole.\n` +
      `You did NOT write this code. Read each issue's contract (\`gh issue view <n> --comments\`; if an Agent Brief comment exists it is authoritative, OTHERWISE the issue body and its acceptance criteria are the contract) and ${standardInstruction}.\n` +
      `${AGENT_CONSTRAINTS}\n` +
      `Check what a per-issue reviewer structurally cannot: the interaction of the changes. Default to clear=false if you find anything real across the union, name the specific issues that interact, and be concrete.`,
    { label: 'integration-review', phase: 'Verify', schema: VERDICT_SCHEMA },
  )
}

// Dispatch ONE code-touching hotfix agent to address ONLY the integration
// review's cross-issue findings, test-first, on a hotfix branch created FRESH off
// the up-to-date default branch. This is the salvage/hotfix agent #14's comment
// anticipated: it TOUCHES CODE, so it MUST carry `isolation: 'worktree'` and the
// shared ${AGENT_CONSTRAINTS} (it must not merge, push, or close). Each round
// uses a distinct branch name, so no in-run worktree handoff is ever needed; the
// branch is created with `git checkout -B` off the current default-branch tip,
// which RESETS any stale ref a prior run's teardown left behind (teardown removes
// the worktree but keeps the ref), so the hotfix can never build on an old base.
const integrationHotfix = (branch, findings) =>
  agent(
    `Fix the cross-issue integration findings below, test-first, on a hotfix branch created FRESH off the up-to-date default branch.\n` +
      `You are in a fresh isolated worktree. Create the branch fresh so a stale ref left by an earlier run cannot make you build on an old base: run \`git checkout -B ${branch} <the up-to-date default branch>\` — the \`-B\` form points ${branch} at the current default-branch tip whether or not the ref already exists. Do all the work in this worktree.\n` +
      `${AGENT_CONSTRAINTS}\n` +
      `Address ONLY these integration findings — nothing else — demonstrate the red before the green, keep every test green, and obey ${standardInstruction}:\n` +
      findings.map((finding) => `- ${finding.title}: ${finding.detail}`).join('\n') +
      `\nCommit on ${branch}, then re-run the full gate suite and report the real result.`,
    { label: 'integration-hotfix', phase: 'Implement', schema: IMPLEMENT_SCHEMA, isolation: 'worktree' },
  )

// Drive the waves in dependency order, processing issues SERIALLY and
// integrating each green one the MOMENT it goes green — before the next issue's
// work begins. This makes partial progress durable: each verified-green issue
// lands on the default branch immediately (fast-forward the default to the
// feature tip), so a mid-run stop — a spend-limit cut-off, a crash — leaves every
// issue integrated so far on the default branch and nothing already-completed is
// lost. Processing the waves IN ORDER puts a dependent's build AFTER its
// prerequisite's, but order alone is not enough: if the prerequisite parked,
// blocked, or failed to integrate — or, in the conservative PR mode, only opened a
// pull request without merging — the base still lacks it. So the loop also honours
// wave OUTCOME — before building an issue it skips (parks) it when an in-scope
// prerequisite has not landed (see `landed` and `unlandedPrerequisites` below). The
// within-wave issue-number sort is only deterministic ordering, since
// a wave's issues are independent by construction. Worktree isolation (#14) keeps
// concurrent agents apart, so serial dispatch is safe.
const verdicts = []
const parked = []
const waves = config.waves || []

// The issue numbers whose code actually LANDED on the base a dependent builds from
// — the default branch. A dependent must build on a base that already contains its
// prerequisites, so this set is consulted before each build: an issue with an
// unlanded in-scope prerequisite is skipped rather than built on an incomplete
// base. Only a MERGE-mode integration lands an issue here, because only merge mode
// puts the change on the default branch; the conservative default PR mode opens a
// pull request and merges NOTHING, so a PR-opened issue is deliberately absent —
// its dependents would otherwise build on a base missing it (issue #23). A
// parked/blocked/failed issue never lands either. Both omissions cascade the skip
// to everything downstream, which is exactly the intent.
const landed = new Set()

// The outcome of the mandatory final integration review, surfaced on the return
// so the caller/report can see whether the combined diff cleared. Stays null
// when the run integrated nothing (no combined diff exists to review).
let integrationOutcome = null

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

      // Skip (park) this issue when one of its in-scope prerequisites is not on the
      // base, rather than build it on a base missing that work. The reason NAMES the
      // unlanded prerequisite and is carried in `blockers` — the field the report
      // surfaces for a parked issue (it shows `verify` only for a done one) — so the
      // report points at the real cause. It is MODE-AWARE: in merge mode a missing
      // prerequisite genuinely failed to land (parked/blocked/failed integrate); in
      // PR mode NOTHING merges, so a prerequisite is missing because it is only an
      // open PR — the reason points the human at --merge, the way to build this
      // issue on a base that contains it. Because a skipped issue is never added to
      // `landed`, this same check parks every downstream dependent in turn — the
      // transitive cascade.
      const missing = unlandedPrerequisites(issuesByNumber.get(number)?.blocked_by, issuesByNumber, landed)
      if (missing.length > 0) {
        const named = missing.map((prereq) => `#${prereq}`).join(', ')
        const reason = merge
          ? `prerequisite did not land: ${named}`
          : `prerequisite not on the base — PR mode opens a pull request without merging it: ${named}. Re-run with --merge (or after the prerequisite's PR merges) to build this issue on a base that contains it.`
        parked.push({ ...toRecord(number, null, 'parked', reason), blockers: [reason] })
        continue
      }

      // Build + independently verify this one issue (worktree-isolated).
      const record = await buildAndVerify(number)

      // A null record should never happen (buildAndVerify always returns one),
      // but park it with a reason rather than silently dropping the issue — a
      // vanished issue would not even appear in the report.
      if (record == null) {
        parked.push(toRecord(number, null, 'parked', 'buildAndVerify returned nothing'))
        continue
      }
      if (record.status !== 'done') {
        parked.push(record)
        continue
      }

      // Integrate it NOW, before the next issue's build starts: in merge mode a
      // clean fast-forward of the default to the feature tip lands it, in PR mode a
      // pull request is opened; a conflict or failure parks it. Because this happens
      // here, inline, a stop after this point still leaves a merge-mode issue on the
      // default branch — the durability property the batched design lacked.
      const integrated = await integrate(record)

      // Record the outcome. Mark the issue landed ONLY when the run actually merged
      // it onto the base — merge mode alone. A PR-mode integration opens a pull
      // request and merges nothing, so the issue is NOT on the base a dependent
      // would build from; leaving it out of `landed` parks every in-scope dependent
      // (pointing them at --merge) and cascades that skip transitively, exactly as a
      // parked or failed integration does. A parked integration is never landed in
      // either mode.
      if (integrated.status === 'done') {
        verdicts.push(integrated)
        if (merge) landed.add(integrated.number)
      } else {
        parked.push(integrated)
      }
    }
  }

  // MANDATORY final integration review. A per-issue verifier sees one issue in
  // isolation and structurally cannot catch a cross-issue defect across the
  // combined change set. So whenever the run produced at least one integrated
  // issue (verdicts.length > 0 — the only case a combined change set exists), one
  // adversarial reviewer examines it with a verifier's full rigor (the reviewer
  // is mode-aware: the combined diff on the default branch in merge mode, the
  // union of the run's feature branches in PR mode), and its clear decision runs
  // through blockingFindings exactly like a per-issue verdict: a dead / not-clear
  // / empty-findings review can never pass silently. The bounded hotfix loop runs
  // ONLY in merge mode — where landing is authorised and the default branch
  // actually holds the changes, so a hotfix branched off it can see them; a real
  // finding then drives a BOUNDED hotfix + re-review, not a mere report. In PR
  // mode auto-hotfixing would contradict the conservative leave-the-merge-to-you
  // posture (and the changes are not on the default branch), so the finding is
  // reported (parked) for the human instead. Either way a finding is never
  // silently cleared or dropped. This sits after the wave loop but INSIDE the
  // teardown try, and before the finally, so teardown still fires and any hotfix
  // worktree is torn down too.
  if (verdicts.length > 0) {
    let review = await integrationReview(verdicts)
    let findings = blockingFindings(review ? [review] : [])

    // Bounded hotfix loop — MERGE MODE ONLY (the `merge &&` guard). Address ONLY
    // the cross-issue findings on a fresh hotfix branch (tracked in builtBranches
    // so teardown removes its worktree), land it through the same linear
    // fast-forward integrate step, then RE-REVIEW — the hotfix could itself break
    // the union.
    // Stops when the review clears or the round cap is reached. In PR mode the
    // guard is false, the loop never runs, and the finding is parked below.
    for (let round = 1; merge && round <= maxIntegrationRounds && findings.length > 0; round += 1) {
      log(`integration review: hotfix round ${round}/${maxIntegrationRounds} — ${findings.length} finding(s)`)

      const hotfixBranch = `orchestrate-integration-hotfix-${round}`
      builtBranches.add(hotfixBranch)
      const impl = await integrationHotfix(hotfixBranch, findings)

      // A dead hotfix agent leaves the findings unresolved for the next round or
      // the cap; the combined diff is never re-reviewed on an unconfirmed hotfix.
      if (impl == null) continue

      // Land the hotfix through the existing fast-forward integrate step, then re-
      // review. A hotfix that cannot land is parked with its blocker and the loop
      // stops — there is nothing new to re-review.
      const hotfixIntegration = await integrate({
        number: 0,
        title: `integration hotfix round ${round}`,
        branch: hotfixBranch,
        status: 'done',
        gates: '',
        verify: '',
        remaining_for_human: [],
        assumptions: [],
        blockers: [],
      })
      if (hotfixIntegration.status !== 'done') {
        parked.push(hotfixIntegration)
        break
      }
      review = await integrationReview(verdicts)
      findings = blockingFindings(review ? [review] : [])
    }

    // Record the integration outcome for the return. A clean pass leaves a trace
    // in the log; an unresolved cross-issue finding is parked for a human — after
    // the merge-mode hotfix cap, or straightaway in PR mode — never dropped.
    if (findings.length === 0) {
      log('integration review: cleared — no cross-issue findings across the combined change set')
      integrationOutcome = { cleared: true, summary: review?.summary || 'integration review cleared the combined change set' }
    } else {
      integrationOutcome = { cleared: false, findings }
      parked.push({
        number: 0,
        title: 'integration review',
        status: 'parked',
        gates: '',
        verify: review?.summary || '',
        remaining_for_human: [],
        assumptions: [],
        blockers: findings.map((finding) => `${finding.title}: ${finding.detail}`),
      })
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

return { verdicts, parked, integration: integrationOutcome }
