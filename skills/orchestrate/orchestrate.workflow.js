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
 *     issues:  { number, title, blocked_by, plan? }[],  // from orchestrate.py plan; plan = ADR-0002 per-issue "how" overlay, absent at XL / in a pre-plan run
 *     standardsPath?: string,                    // coding-standard directory the agents read
 *     maxFixRounds?: number,                     // fix<->verify cap per issue (default 1)
 *     maxIntegrationRounds?: number,             // integration-review hotfix cap (default maxFixRounds)
 *     merge?:  boolean,                          // integrate to the default branch, else open PRs
 *     budgetFloor?: number,                      // stop opening waves below this many tokens left
 *     implementerMode?: 'execute'|'balanced'|'autonomous', // ADR-0002 §4 run-level marker; absent → engine adds no mode framing (today's behaviour)
 *     roles?:  {                                 // per-role (model, effort) the orchestrator
 *       judgment?:    { model?, effort? },       //   resolved from --level; absent → session model
 *       implementer?: { model?, effort? },
 *       mechanical?:  { model?, effort? },
 *     },
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
    inSituHazard: { type: 'string', description: 'A genuine, previously-unseen danger surface discovered DURING the work — a write path, a permission gate, an irreversible delete — that the brief or plan did not anticipate. Present only when found; absent otherwise. Independent of `status`: it does not block progress, but on an empty verifier panel it triggers the one sanctioned automatic verify-lens escalation (ADR-0003 §5, shouldEscalateInSitu).' },
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
          suggestedFix: { type: 'string', description: 'A remedy DIRECTION for this finding, proposed only AFTER judging it real (ADR-0004) — so the fix agent starts from a diagnosis + direction rather than re-deriving it. ADVISORY, not authoritative: the reviewer read the code but did not run it, so the fixer verifies it before following, may choose a better fix, and binds the tests to the acceptance criteria, never to this suggestion. Omitted when the reviewer has no confident direction.' },
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
    conflict: { type: 'boolean', description: 'True ONLY when the merge-mode landing was refused because rebasing the verified branch onto the advanced default hit a genuine content conflict the integrator will not resolve — the signal the bounded reconcile stage repairs (#46). False or absent for any other, non-conflict failure.' },
  },
}

// What the mechanical preflight sub-agent returns (issue #49): the durable
// idempotence state of one issue, gathered read-only, that `preflightDecision`
// maps to a verdict. It changes nothing — it only reads `gh issue view`, checks
// ancestry with `git merge-base --is-ancestor`, and reads any orchestrate PR's
// state.
const PREFLIGHT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['landedMarker', 'prMarker'],
  properties: {
    landedMarker: { type: 'boolean', description: 'A merge-mode `orchestrate: landed <sha> on <branch>, run <runId>` marker comment is present on the issue.' },
    landedSha: { type: 'string', description: 'The SHA recorded by that landed-marker (informational; ancestry below is the deciding fact).' },
    shaIsAncestor: { type: 'boolean', description: 'That SHA is an ancestor of the CURRENT default-branch tip (`git merge-base --is-ancestor <sha> <default>` exits 0). Distinguishes durably-landed work from a reverted/rebased-away marker.' },
    prMarker: { type: 'boolean', description: 'A PR-mode `orchestrate: opened PR #<pr>, run <runId>` marker comment is present on the issue.' },
    prOpen: { type: 'boolean', description: 'The pull request that PR-marker names is still OPEN (`gh pr view <pr> --json state`).' },
    closed: { type: 'boolean', description: 'The issue itself is closed.' },
  },
}

// `normalizeArgs`, `planIsEmpty`, `blockingFindings`, `unlandedPrerequisites`,
// `roleTuning`, `shouldEscalateInSitu`, `withInSituHazard`,
// `isReconcilableConflict`, and `preflightDecision` are kept inline as
// plain internal `const`s because the Workflow harness rejects any top-level
// `export` beyond the single leading `export const meta` and forbids a top-level
// `import` — so this script cannot import them. Their tested source of truth is
// the byte-for-byte identical `lib/orchestrate/engine-helpers.mjs`; keep the two
// in sync.

/**
 * Normalize the raw `args` the Workflow harness delivers into the single config
 * object the engine reads every field off. The harness passes `args` as a JSON
 * string, but a hand-launched or already-parsed run passes an object; tolerate
 * both shapes. Anything absent or unparseable yields an empty plan so the
 * empty-plan guard below — not a thrown error — decides how to react.
 *
 * @param {string|object|undefined} raw The harness-delivered run config: a JSON
 *   string, an already-parsed object, or nothing.
 * @returns {object} The normalized config the engine reads every field off — the
 *   full `args` shape: `waves`, `issues` (each with an optional per-issue `plan`
 *   overlay), `merge`, `maxFixRounds`, `maxIntegrationRounds`, `standardsPath`,
 *   `budgetFloor`, `implementerMode`, and `roles`. `normalizeArgs` is a pass-through,
 *   so it neither adds nor drops fields.
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

/**
 * The `agent()` opts fragment that tunes one role's sub-agents to the model and
 * reasoning effort the `--level` dial resolved for it. The ambition dial is
 * turned OUTSIDE the engine: the orchestrator resolves `--level` into a per-role
 * `(model, effort)` against the harness's live model list — the engine has no
 * primitive to enumerate models — and passes the result in as `args.roles`. This
 * helper merely APPLIES one role's resolution, storing no model-name table of its
 * own. Only a field the resolution actually set is copied, and an absent or
 * non-object role yields an empty fragment: spread into an agent's opts it adds no
 * `model`/`effort` key, so the agent inherits the session model and a plan
 * produced before the dial existed still runs unchanged.
 *
 * @param {{model?: string, effort?: string}|undefined} role One role's resolved
 *   tuning from `args.roles` (`judgment` / `implementer` / `mechanical`), or
 *   nothing.
 * @returns {{model?: string, effort?: string}} The opts fragment to spread into an
 *   `agent()` call — only the fields the resolution actually set, nothing when it
 *   set none.
 */
const roleTuning = (role) => {

  // An absent, null, or non-object resolution yields an empty fragment: spread into
  // an agent's opts it adds no model/effort key, so the agent inherits the session
  // model and a plan produced before the dial existed runs unchanged.
  if (role == null || typeof role !== 'object') return {}

  // Copy only the fields the orchestrator actually resolved, so a role that set
  // just the model (or just the effort) overrides only that one dimension.
  const tuning = {}
  if (role.model != null) tuning.model = role.model
  if (role.effort != null) tuning.effort = role.effort
  return tuning

}

/**
 * The ADR-0003 §5 in-situ hazard escalation decision: true only when an
 * EXPLICITLY empty per-issue verifier panel (the plan produced `0`, from
 * `--max-lenses=0`) meets a genuine, previously-unseen danger surface the
 * implementer discovered DURING the work — a write path, a permission gate, an
 * irreversible delete — and flagged in its three-bucket report's
 * `inSituHazard` field. This is the rare, sanctioned automatic override: on
 * `true` the engine dispatches exactly ONE verify lens for that one issue and
 * folds its verdict in normally, never the whole panel. A plan-time hazard
 * (surfaced at the planner's gate, ADR-0003 §5) never reaches this helper —
 * only what the implementer itself discovers in flight does.
 *
 * @param {{inSituHazard?: string}|null|undefined} report The implementer's
 *   IMPLEMENT_SCHEMA-shaped report for this issue.
 * @param {unknown[]} panel The issue's resolved verifier panel (from
 *   `lensesFor`) — escalation only ever applies when this is explicitly empty.
 * @returns {boolean} Whether to dispatch the one sanctioned escalation lens.
 */
const shouldEscalateInSitu = (report, panel) => {

  // Escalation exists ONLY to fill the gap an explicitly empty panel leaves; a
  // panel that already carries at least one lens got its independent review
  // and is untouched by this decision, whatever the report says.
  if (!Array.isArray(panel) || panel.length > 0) return false

  // A non-blank `inSituHazard` is the implementer's own flag of a genuine,
  // previously-unseen danger surface — never inferred from any other field.
  return typeof report?.inSituHazard === 'string' && report.inSituHazard.trim().length > 0

}

/**
 * Fold the implementer's own in-situ hazard (ADR-0003 §5) into a lens panel's
 * brief(s), so the ONE sanctioned reviewer dispatched on an escalated empty
 * panel is pointed at the exact danger surface the implementer flagged during
 * the work, rather than reviewing through the generic brief alone. Used ONLY
 * for the escalated `DEFAULT_LENSES` dispatch in `buildAndVerify` — an
 * ordinary, non-empty panel already carries its own risk-scaled framing from
 * planning and passes straight through to `verify`, never through this helper.
 *
 * @param {Array<string|{brief: string, agentType?: string}>} lenses The panel
 *   to fold the hazard into — each entry a plain brief string or a
 *   `{brief, agentType}` object routing to a named review agent.
 * @param {string} hazard The implementer's own `inSituHazard` text. The only
 *   caller (`buildAndVerify`) reaches this helper exclusively through a panel
 *   `shouldEscalateInSitu` already confirmed true, so `hazard` is guaranteed a
 *   non-blank string.
 * @returns {Array<string|{brief: string, agentType?: string}>} The same shape
 *   each lens came in as, with its brief appended by a pointer at the flagged
 *   surface.
 */
const withInSituHazard = (lenses, hazard) => {

  // Append the flagged surface to each lens's OWN brief rather than replacing
  // it, so the escalated reviewer keeps the broad DEFAULT_LENSES framing AND
  // the specific pointer, and a `{ brief, agentType }` lens keeps its routing.
  return lenses.map((lens) => {
    const brief = typeof lens === 'string' ? lens : lens.brief
    const hazardBrief = `${brief} The implementer flagged this specific in-situ hazard discovered during the work — scrutinize it directly: ${hazard}`
    return typeof lens === 'string' ? hazardBrief : { ...lens, brief: hazardBrief }
  })

}

/**
 * Whether a parked integration record is a GENUINE rebase content conflict the
 * bounded reconcile stage can repair (#46 fix 2), as opposed to any other landing
 * failure. A verified-green branch that failed `--ff-only` only because rebasing it
 * onto the advanced default hit a content conflict is sound work the integrator
 * (rightly) will not resolve; rather than park it outright, the engine attempts a
 * bounded reconcile — rebase+resolve, targeted re-verify of the resolution, then
 * land. Only such a record qualifies: it must be parked AND carry the integrator's
 * `conflict` flag. A landed, design-blocked, or otherwise-failed record never
 * reconciles, and the wave loop gates the attempt on merge mode besides.
 *
 * @param {{status?: string, conflict?: boolean}|null|undefined} record The record
 *   `integrate` returned.
 * @returns {boolean} Whether to attempt a bounded reconcile before parking.
 */
const isReconcilableConflict = (record) => record != null && record.status === 'parked' && record.conflict === true

/**
 * The preflight idempotence verdict for one issue (issue #49), computed PURELY
 * from the facts a mechanical preflight sub-agent gathered — no I/O of its own.
 * This is what makes a blind cross-session restart safe: an issue whose work
 * already landed is never re-implemented, and a landed-marker whose commit is no
 * longer on the default branch parks LOUDLY rather than rebuilding from zero.
 * Workflow resume is same-session-only, so a relaunched run gets zero cache hits
 * and re-runs the whole plan; this guard — not resume — is the safety net.
 *
 * `facts` is the preflight agent's structured result:
 *   - `landedMarker`  a merge-mode `orchestrate: landed …` marker is present
 *   - `landedSha`     the SHA that marker recorded (informational — the ancestry
 *                     boolean already reflects it)
 *   - `shaIsAncestor` that SHA is an ancestor of the CURRENT default-branch tip
 *   - `prMarker`      a PR-mode `orchestrate: opened PR …` marker is present
 *   - `prOpen`        that pull request is still open
 *   - `closed`        the issue itself is closed (gathered for the record; the
 *                     durable marker + its ancestry are the authoritative signal,
 *                     so this field is not branched on here)
 * `merge` is the run's mode (true = land on the default branch).
 *
 * Verdicts:
 *   - `already-landed`       marker present AND its SHA is on the default branch
 *                            → skip; the work is durably present.
 *   - `landed-marker-stale`  marker present but its SHA is NOT on the default
 *                            (reverted / rebased away / foreign history) → park
 *                            loudly for a human; never rebuild.
 *   - `already-open`         PR mode with an existing open orchestrate PR → the
 *                            expected completed PR-mode state; benign skip.
 *   - `dispatch`             no actionable marker → build normally.
 *
 * @param {{landedMarker?: boolean, landedSha?: string, shaIsAncestor?: boolean,
 *   prMarker?: boolean, prOpen?: boolean, closed?: boolean}|null|undefined} facts
 *   The preflight agent's gathered state, or nothing when it died (→ dispatch).
 * @param {boolean} merge Whether the run lands on the default branch.
 * @returns {'already-landed'|'landed-marker-stale'|'already-open'|'dispatch'} The
 *   guard's verdict.
 */
const preflightDecision = (facts, merge) => {

  // A landed marker is the strongest signal in either mode: its SHA's ancestry
  // on the current default tip separates durably-present work from a marker
  // whose commit was reverted or rebased away.
  const f = facts || {}
  if (f.landedMarker === true) {
    return f.shaIsAncestor === true ? 'already-landed' : 'landed-marker-stale'
  }

  // PR mode only: an already-open orchestrate PR is the expected completed state
  // for a previously-run issue, not a loud park.
  if (merge !== true && f.prMarker === true && f.prOpen === true) {
    return 'already-open'
  }

  return 'dispatch'

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

// The per-role (model, effort) the orchestrator resolved from the `--level`
// ambition dial against the harness's live model list, keyed by role class —
// `judgment` (planning + adversarial review), `implementer` (writes code), and
// `mechanical` (integrate, teardown). The engine stores NO model-name table; it
// only applies what it is handed, spreading `roleTuning(roles.<class>)` into each
// agent's opts. An absent `roles` (a plan produced before the dial existed) leaves
// this an empty object, so every role resolves to an empty fragment and every
// agent inherits the session model — the run is unchanged.
const roles = config.roles || {}

// The run-level sliding-implementer marker the orchestrator resolved from the
// `--level` dial (ADR-0002 §4): `execute` at XS/S, `balanced` at M, `autonomous` at
// L/XL. It is EXPLICIT, never inferred from whether a plan string is present, and it
// selects the fixed framing the `implement` agent is told to treat its plan with.
// Absent (a pre-ADR-0002 or hand-launched plan) leaves it undefined, so no framing
// is added and the implement prompt degrades to exactly today's behaviour.
const implementerMode = config.implementerMode

// Title lookup for logging and report records.
const titleOf = (number) => issuesByNumber.get(number)?.title || `issue ${number}`

// The default verifier panel, used ONLY when planning has not annotated the
// issue (a hand-launched or pre-plan run): a SINGLE broad adversarial reviewer
// that folds every concern into one lens — correctness against the issue intent
// and its acceptance criteria, the quality of the tests, and any security or
// data-safety hazard the issue touches. One agent, not three. A planned run
// always sets the per-issue `lenses` override below — 1 broad lens at XS/S, 3
// focused lenses at M/L/XL (ADR-0004, rigor saturating at M), escalated further
// only by a Risk marker on an XS/S issue — so this fallback is the lean floor,
// not the normal path.
const DEFAULT_LENSES = [
  'correctness against the issue intent and its acceptance criteria, the quality of the tests (is the red demonstrated, are the tests load-bearing, does every acceptance criterion map to a test), AND any security or data-safety hazard the issue touches — review all of these together through one broad adversarial lens',
]

// The verifier panel for an issue. The default is the single broad adversarial
// reviewer in DEFAULT_LENSES; a planned run overrides it per issue by setting
// `lenses`, scaled from the level baseline (1 broad at XS/S, 3 focused at
// M/L/XL since ADR-0004) and escalated further by a Risk marker on an XS/S issue
// (a write path, a permission gate, an irreversible delete). A lens is a plain
// brief string, or a { brief, agentType } object to
// route to one of the project's own review agents (a silent-failure hunter, a
// test-coverage analyzer, …). An ABSENT `lenses` field (a non-array, the normal
// case) falls back to DEFAULT_LENSES; an EXPLICITLY empty array (the plan
// produced 0, from --max-lenses=0, ADR-0003 §2) passes through as empty — the
// signal buildAndVerify reads to skip the per-issue verify stage entirely.
const lensesFor = (issue) => {
  const lenses = issue?.lenses
  return Array.isArray(lenses) ? lenses : DEFAULT_LENSES
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

// The shared-symbol ripple-report instruction every code-touching implementer
// gets (#36): if the change alters a shared symbol's contract, signature, or
// effective behaviour — especially beyond the files this one task obviously
// owns — enumerate the affected call sites and state under `assumptions` which
// were updated and which were not. A per-issue verifier is bound to the diff
// alone and structurally cannot see an unchanged caller outside it, so a
// silently incomplete refactor was previously caught only at the mandatory
// integration review — a full extra review + remediation cycle; this makes it
// a REPORTED one the orchestrator and verifier can act on immediately, rather
// than a silent gap. Defined ONCE and interpolated into `implement` and `fix`,
// mirroring how AGENT_CONSTRAINTS is shared rather than copy-pasted — `fix` is
// finding-driven but can still touch a shared symbol while addressing a
// finding, so it carries the same instruction.
const RIPPLE_REPORT_INSTRUCTION = `If this change alters a shared symbol's contract, signature, or effective behaviour — especially beyond the files this task obviously owns — enumerate the affected call sites and state under \`assumptions\` which you updated and which you did not; a silently incomplete refactor becomes a reported one the orchestrator and verifier can act on.`

// The conditional consistency/ripple lens every dispatched `verify` lens gets
// (#36): a per-issue reviewer is bound to the diff and structurally cannot see
// an unchanged caller outside it, so an implementer who updates a shared
// symbol's contract or effective behaviour but only some of its callers still
// reads as locally consistent — the exact class the mandatory integration
// review otherwise caught alone, a full extra review + remediation cycle
// later. This instruction pulls that check earlier: WHEN the diff changes a
// shared, multi-caller symbol's contract or effective behaviour, the reviewer
// ALSO checks that symbol's OTHER, unchanged callers for consistency, not only
// the diff; an ordinary diff that touches no such shared symbol pays nothing
// extra. Folded into `verify` ONLY — never into the narrowly-scoped
// `reverifyFindings` / `reverifyReconcile` re-verifies (already confined to
// specific findings or a resolution), and never into the mandatory integration
// review, which stays the unchanged backstop (#36 leaves it alone by design).
const CONSISTENCY_LENS_INSTRUCTION = `If the diff changes a shared, multi-caller symbol's contract or effective behaviour, ALSO check that symbol's OTHER, UNCHANGED callers for consistency — not only the diff itself, since an unchanged caller sits outside it; skip this check entirely when the diff touches no such shared symbol.`

// The three fixed prompt framings that slide how the `implement` agent is told to
// TREAT its plan — from mechanical execution of a settled recipe at the low end of
// the `--level` dial to autonomous problem-solving at the high end (ADR-0002 §4).
// Fixed engine text keyed by the run-level `implementerMode` marker the orchestrator
// resolves and passes in (`XS, S → execute`, `M → balanced`, `L, XL → autonomous`),
// modeled the way DEFAULT_LENSES and AGENT_CONSTRAINTS are — inline, so a structural
// test can assert each mode selects its own framing. The marker is EXPLICIT, never
// inferred from a plan string's presence; the framing applies to `implement` ONLY,
// since `fix` is finding-driven and `integrationHotfix` is cross-issue.
const IMPLEMENTER_MODE_FRAMINGS = {
  execute: 'This plan is the settled *how*. Follow it test-first. Deviate only if it is demonstrably wrong, and record why. Do not re-derive the approach.',
  balanced: 'Follow the spec\'s shape, fill in the routine *how* yourself, and respect the decisions it calls out.',
  autonomous: 'Here are the goals and constraints (or, at `XL`, the brief). Reason out the *how* yourself, test-first; the tests are your guide. You own the approach.',
}

// Compose ADR-0002's additive "how" overlay for the `implement` prompt: the plan's
// stance framing (selected from the fixed IMPLEMENTER_MODE_FRAMINGS by the run-level
// marker) and the per-issue plan text, each degrading cleanly and INDEPENDENTLY to
// nothing when its field is absent. An absent or unrecognized mode contributes no
// framing; an absent or blank plan contributes no plan text; so a legacy or
// hand-launched run (neither field) yields the empty string and the implement prompt
// is byte-for-byte today's. The brief stays the authoritative WHAT and the tests
// bind to the acceptance criteria, never to this plan. Called from `implement` ONLY.
const planOverlay = (mode, plan) => {

  // Resolve the plan half first: an absent or blank plan contributes no plan text,
  // so the plan half degrades on its own. Computed before the framing line because
  // the framing's "plan below" pointer is emitted only when a plan block follows.
  const hasPlan = typeof plan === 'string' && plan.trim().length > 0

  // Select the fixed stance framing by the EXPLICIT run-level marker, hardened against
  // prototype-key collisions: a `mode` colliding with an Object.prototype member
  // ('constructor', 'toString', '__proto__', …) resolves to a truthy INHERITED
  // non-string on this plain object, so require an actual framing STRING before it can
  // reach the prompt — an absent, unrecognized, or colliding mode adds no framing.
  const framing = IMPLEMENTER_MODE_FRAMINGS[mode]
  const hasFraming = typeof framing === 'string'

  // Emit the stance framing (ADR-0002 §4). The "plan below" pointer is added ONLY when
  // a plan block follows; with a mode but no plan (autonomous at XL) the framing stands
  // alone and never dangles a reference to a plan that was not emitted.
  const framingPrefix = hasPlan ? 'How to treat the plan below: ' : ''
  const framingLine = hasFraming ? `${framingPrefix}${framing}\n` : ''

  // Layer the per-issue plan as HOW-only guidance; the Agent Brief (or issue body)
  // stays the authoritative WHAT and the tests bind to the acceptance criteria.
  const planBlock = hasPlan
    ? `Implementation plan — level-scaled guidance on HOW to build this, authored up front. The Agent Brief (or issue body) above remains the authoritative WHAT, and your tests bind to the acceptance criteria, never to this plan:\n${plan}\n`
    : ''

  return framingLine + planBlock

}

// The mechanical preflight idempotence check dispatched BEFORE an implementer
// (issue #49): a read-only agent that gathers the issue's durable landing state
// so a blind cross-session restart never re-implements already-landed work. It
// changes nothing — no comment, no close, no push, no code — it only reads. The
// engine feeds its structured result to `preflightDecision`. A dead preflight
// (null) decodes to `dispatch` there, so the worst case is the pre-#49 behaviour
// (a re-implement caught by verify), never a wrongful skip.
const preflight = (number) =>
  agent(
    `Preflight idempotence check for GitHub issue #${number} ("${titleOf(number)}") — GATHER STATE ONLY, CHANGE NOTHING.\n` +
      `This run may be a restart: a previous run (Workflow resume is same-session-only, so a relaunch re-runs the whole plan) may have already landed this issue. Before it is re-implemented, report the durable markers that exist so the engine can skip already-done work.\n` +
      `1. Run \`gh issue view ${number} --comments\`. Look for the LATEST orchestrate landed-marker comment in the exact form \`orchestrate: landed <sha> on <branch>, run <runId>\` and/or the LATEST PR-marker \`orchestrate: opened PR #<pr>, run <runId>\`. Also read the issue's own open/closed state (set \`closed\`).\n` +
      `2. If a landed-marker exists, set \`landedMarker\` true and \`landedSha\` to its <sha>, then run \`git merge-base --is-ancestor <sha> <the default branch>\` (exit 0 = ancestor): set \`shaIsAncestor\` to whether that SHA is an ancestor of the CURRENT default-branch tip. If no landed-marker exists, set \`landedMarker\` false.\n` +
      `3. If a PR-marker exists, set \`prMarker\` true and run \`gh pr view <pr> --json state\`: set \`prOpen\` to whether that PR is still OPEN. If no PR-marker exists, set \`prMarker\` false.\n` +
      `Report ONLY these facts. Do NOT implement, comment, close, push, merge, or modify anything.`,
    { label: `preflight:#${number}`, phase: 'Implement', schema: PREFLIGHT_SCHEMA, ...roleTuning(roles.mechanical) },
  )

// Dispatch one implementer on its own worktree-isolated branch, test-first. It
// consumes ADR-0002's additive "how" overlay — the run-level mode framing plus the
// per-issue plan — layered onto the contract; when neither field is present the
// overlay is empty and this is exactly today's prompt.
const implement = (number) =>
  agent(
    `Implement GitHub issue #${number} ("${titleOf(number)}") test-first.\n` +
      `Read its contract first: run \`gh issue view ${number} --comments\`. If an Agent Brief comment exists it is authoritative; OTHERWISE the issue body and its acceptance criteria ARE the contract — build from them and never stall for a missing brief.\n` +
      `Read and obey ${standardInstruction}.\n` +
      `${AGENT_CONSTRAINTS}\n` +
      `${planOverlay(implementerMode, issuesByNumber.get(number)?.plan)}` +
      `Create your feature branch FRESH off the up-to-date default branch — do NOT rely on the worktree's current HEAD, which is the harness's run-start scaffolding ref and is STALE (pinned when the run started, it does not advance as each issue lands, so building on it would fork you off a base missing your predecessors' landed work). Choose a branch name, then run \`git checkout -B <your-branch> <the up-to-date default branch>\` — the \`-B\` form points your branch at the CURRENT default-branch tip whether or not the ref already exists, mirroring the integration hotfix. In this serial integrate-immediately design your predecessors have already landed on the default, so this base contains their work and your branch fast-forwards cleanly at integration. Do all the work in this worktree. Demonstrate the red — a failing-test commit — before the green, because a test never seen to fail is of unknown value. Refactor only once green.\n` +
      `Automate everything meaningfully automatable, then run the project's full gate suite (discover it from the project) and report the REAL result.\n` +
      `Resolve genuine ambiguity by the most reasonable assumption and record it; never pause to ask. The one exception is work that cannot proceed without contradicting a settled decision (an ADR or design doc): set status "blocked", record the blocker, and stop only this issue.\n` +
      `${RIPPLE_REPORT_INSTRUCTION}\n` +
      `If, during the work, you discover a genuine, previously-unseen danger surface the brief and plan did not anticipate — a write path, a permission gate, an irreversible delete — record it in \`inSituHazard\`; this does not block your progress or change your status, it only flags the surface for independent review.`,
    { label: `implement:#${number}`, phase: 'Implement', schema: IMPLEMENT_SCHEMA, isolation: 'worktree', ...roleTuning(roles.implementer) },
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
      `Address ONLY these verified findings, keep the tests green, and obey ${standardInstruction}. Each finding is authoritative; any \`suggested direction\` attached to it is ADVISORY only — the reviewer read the code but did not run it, so verify a suggestion before following it, pick a better fix if you see one, and bind your tests to the acceptance criteria, never to the suggestion:\n` +
      findings.map((finding) => `- ${finding.title}: ${finding.detail}${finding.suggestedFix ? `\n  suggested direction (advisory): ${finding.suggestedFix}` : ''}`).join('\n') +
      `\nCommit on ${impl.branch}, then re-run the full gate suite and report the real result.\n` +
      `${RIPPLE_REPORT_INSTRUCTION}`,
    { label: `fix:#${number}`, phase: 'Implement', schema: IMPLEMENT_SCHEMA, isolation: 'worktree', ...roleTuning(roles.implementer) },
  )

// Run the adversarial panel concurrently; each reviewer gets one lens and only
// what the gates cannot prove. `lenses` is the panel to run — buildAndVerify
// passes the issue's own plan panel in the ordinary case, or the single
// escalated lens when an explicitly empty panel's in-situ hazard just
// triggered the one sanctioned automatic override (ADR-0003 §5).
const verify = async (number, impl, lenses) => {
  const verdicts = await parallel(
    lenses.map((lens) => () => {
      // A lens is a brief string, or { brief, agentType } to use a named agent.
      const brief = typeof lens === 'string' ? lens : lens.brief
      const opts = { label: `verify:#${number}:${brief.split(' ')[0]}`, phase: 'Verify', schema: VERDICT_SCHEMA, ...roleTuning(roles.judgment) }
      if (typeof lens === 'object' && lens.agentType) opts.agentType = lens.agentType

      return agent(
        `Adversarially review branch ${impl.branch} for issue #${number} ("${titleOf(number)}") through ONE lens: ${brief}.\n` +
          `You did NOT write this code. Read the issue's contract (\`gh issue view ${number} --comments\`; if an Agent Brief comment exists it is authoritative, OTHERWISE the issue body and its acceptance criteria are the contract) and ${standardInstruction}.\n` +
          `${AGENT_CONSTRAINTS}\n` +
          `Check ONLY what the gates cannot — do not re-check lint, build, or tests that already passed. ${CONSISTENCY_LENS_INSTRUCTION} Default to clear=false if you find anything real, and be specific. For each finding, JUDGE it real FIRST, on its own merits — only THEN, if you can see one, add a \`suggestedFix\` naming a remedy DIRECTION for the fixer to start from. The ease or difficulty of a fix must NEVER soften, inflate, or drop the finding itself; your neutrality is judging the defect, not designing its repair.`,
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
    { label: `reverify:#${number}`, phase: 'Verify', schema: VERDICT_SCHEMA, ...roleTuning(roles.judgment) },
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

  // The plan's own verifier panel for this issue (ADR-0003 §2): DEFAULT_LENSES
  // when the plan set none, a risk-scaled override when it named one, or
  // EXPLICITLY empty when the plan produced 0 (--max-lenses=0). An explicitly
  // empty panel skips the per-issue verify stage entirely — implement ->
  // integrate — UNLESS the implementer's in-situ report just earned the one
  // sanctioned automatic escalation (§5). The mandatory integration review
  // still runs exactly as for any other issue (not a lens, so this never
  // touches it) — but red-before-green itself is NOT independently re-checked
  // here: the implementer's redCommit/greenCommit are self-reported, no lens
  // runs to read the history back, and nothing in this lifecycle calls the
  // deterministic `orchestrate.py redgreen` helper either, so on an empty
  // panel red-before-green is self-attested only.
  const panel = lensesFor(issuesByNumber.get(number))
  if (panel.length === 0 && !shouldEscalateInSitu(impl, panel)) {
    return toRecord(number, impl, 'done', 'no independent verify: empty panel (--max-lenses=0)')
  }

  // Initial verification: the full verifier panel runs EXACTLY ONCE, after green
  // — the plan's own panel, or the single escalated lens (DEFAULT_LENSES) when
  // an explicitly empty panel just triggered the in-situ override above. The
  // escalated lens's brief is folded with the implementer's own `inSituHazard`
  // text (ADR-0003 §5) via `withInSituHazard`, so the one sanctioned reviewer is
  // pointed at the exact surface flagged rather than reviewing generically; an
  // ordinary, non-empty panel already has its own risk-scaled framing from
  // planning and is passed straight through, untouched by this fold.
  // Integration proceeds ONLY when the panel explicitly cleared — blockingFindings
  // treats an empty panel (a dead verifier) and a not-clear-without-findings verdict
  // as blocking, so a change never integrates unverified on either escape.
  const lenses = panel.length > 0 ? panel : withInSituHazard(DEFAULT_LENSES, impl.inSituHazard)
  const verdicts = await verify(number, impl, lenses)
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

  // The integrate step is the SOLE authorized outward mutator: alongside landing
  // the change it posts the durable landed-marker and (merge mode) closes the
  // issue — the narrow exception ADR-0005 carves, because the orchestrator is
  // blocked on the one Workflow call mid-run and the engine has no I/O. This is
  // gated to a REAL issue: the integration hotfix reuses `integrate` with
  // `number: 0`, which must post no marker and close nothing.
  const isRealIssue = record.number > 0

  // How the agent sources each field of the canonical marker. The runId is not
  // an engine arg (the orchestrator only learns it AFTER launch), so the agent
  // discovers it from the run's own worktree scaffolding branches, which the
  // harness names `worktree-<runId>-<n>`; failing that it uses `unknown`, which
  // the tolerant `parse_landed_marker` still accepts as valid provenance.
  const runIdHint = `this run's id — discover it from the run's worktree scaffolding branches, named \`worktree-<runId>-<n>\`: run \`git branch --list 'worktree-*'\` and take the \`<runId>\` segment; if none is discoverable use \`unknown\``

  // Compose the mode-specific marker+close instruction, gated to a real issue: in
  // merge mode post the landed-marker and close; in PR mode post the PR-marker and
  // leave the issue open; for the number:0 hotfix reuse, nothing.
  const markerStep = merge
    ? (isRealIssue
        ? ` Once the fast-forward has landed the change, record the landing durably and CLOSE the issue — the ONE outward write integrate is authorized to make, and nothing else. Post a comment on issue #${record.number} in EXACTLY this canonical form: \`orchestrate: landed <sha> on <branch>, run <runId>\` — substitute <sha> with the landed commit SHA (\`git rev-parse HEAD\` on the default branch after the fast-forward), <branch> with the default branch name, and <runId> with ${runIdHint}. Post it with \`gh issue comment ${record.number} --body '<the marker>'\`. THEN close the issue with \`gh issue close ${record.number}\`: the verify-then-integrate floor is satisfied at this exact moment — the branch cleared INDEPENDENT verification AND has now integrated — so closing here is correct.`
        : ``)
    : (isRealIssue
        ? ` After opening the pull request, record it durably (do NOT close the issue — PR mode leaves it open): post a comment on issue #${record.number} in EXACTLY this form: \`orchestrate: opened PR #<pr>, run <runId>\` — substitute <pr> with the opened PR number and <runId> with ${runIdHint}. Post it with \`gh issue comment ${record.number} --body '<the marker>'\`.`
        : ``)

  const action = (merge
    ? `Land branch ${record.branch} on the default branch by fast-forwarding the DEFAULT branch to that branch's tip, WITHOUT ever checking out ${record.branch}. ${record.branch} is still checked out in the implementer's (or a fix round's) persisted worktree, and git refuses to check out one branch in two worktrees at once, so checking it out here would fail mechanically for a non-conflict reason. From the default branch, run \`git merge --ff-only ${record.branch}\` — this advances the default to the feature tip and creates NO merge commit. ` +
      `Keep the integrated history LINEAR: NEVER merge the default branch INTO the feature branch, and NEVER create a merge commit on the feature branch. ` +
      `${record.branch} was created FRESH off the then-current default tip (the implementer forks off the up-to-date default), and in this serial integrate-immediately design issues land one at a time, so nothing has landed on the default since ${record.branch} was cut: it is already a fast-forward ahead of the default and \`--ff-only\` succeeds with no rebase replay. Only in the rare case the default moved under the feature branch anyway will the fast-forward be refused; that is the one case a genuine rebase is needed — perform it WITHOUT checking out ${record.branch} while a worktree still holds it: free that worktree first with \`git worktree remove --force <path>\` (which KEEPS the branch ref), exactly as the fix-round handoff does, then rebase ${record.branch} onto the default and fast-forward the default to its tip. That rebase checks ${record.branch} out in THIS worktree — the main, un-isolated, only default-branch checkout — so when the fast-forward is done, return this worktree to the default branch (\`git checkout <default>\`), leaving integrate on the default branch and never stranded on ${record.branch}. ` +
      `If a genuine conflict makes that rebase unsafe to resolve, do NOT merge — report it as a blocker AND set \`conflict: true\` in your result, so the run can attempt a bounded reconcile of this verified branch; for any other, non-conflict failure set \`conflict: false\` or omit it.`
    : `Open a pull request for branch ${record.branch} against the default branch. Do NOT merge.`) + markerStep
  const result = await agent(
    `Integrate issue #${record.number} ("${record.title}"). ${action} Report what you did in one line.`,
    { label: `integrate:#${record.number}`, phase: 'Integrate', schema: INTEGRATE_SCHEMA, ...roleTuning(roles.mechanical) },
  )

  // A failed or missing integration parks the otherwise-green issue with its reason.
  // A merge-mode non-integration threads the integrator's `conflict` flag onto the
  // parked record so the caller can tell a genuine, reconcilable rebase conflict
  // (#46) apart from any other landing failure.
  if (result == null) return { ...record, status: 'parked', blockers: [...record.blockers, 'integrator returned nothing'] }
  if (!result.integrated) return { ...record, status: 'parked', blockers: [...record.blockers, result.blocker || result.summary], conflict: result.conflict === true }
  return { ...record, verify: `${record.verify} | ${result.summary}` }
}

// Reconcile a verified-green branch that failed to land ONLY on a genuine rebase
// content conflict (#46 fix 2): one implementer-grade agent rebases the feature
// branch onto the advanced default and resolves the conflicts MINIMALLY, keeping
// both sides' concerns. Like `fix`, it lands in a FRESH worktree while the branch
// is still checked out in the implementer's (or a fix round's) persisted worktree,
// so it frees that worktree first (keeping the branch ref) before taking the branch
// over. It touches code, so it carries worktree isolation and the shared
// constraints; it must NOT push or merge — the subsequent integrate lands it.
const reconcile = (record) =>
  agent(
    `Reconcile issue #${record.number} ("${record.title}") onto the advanced default branch. Its branch ${record.branch} passed independent verification but could not fast-forward the default because the default moved under it; rebase it and resolve the conflicts so it can land cleanly.\n` +
      `You are in a FRESH isolated worktree, but branch ${record.branch} is still checked out in another worktree (the implementer's or a fix round's), and git refuses to check out one branch in two worktrees at once. BEFORE anything else, take the branch over:\n` +
      `1. Run \`git worktree list --porcelain\` and find any OTHER worktree that currently has ${record.branch} checked out.\n` +
      `2. If one exists, run \`git worktree remove --force <that path>\` to free it. \`remove\` KEEPS the branch ref, so ${record.branch}'s commits survive — NEVER run \`git branch -D\` (or any branch delete) and NEVER \`git reset --hard\`.\n` +
      `3. Check out ${record.branch} in your own worktree, then rebase it onto the up-to-date default branch (\`git rebase <the up-to-date default branch>\`).\n` +
      `${AGENT_CONSTRAINTS}\n` +
      `Resolve EVERY conflict MINIMALLY, keeping BOTH sides' concerns — your branch's change AND whatever landed on the default under you — never discarding either side, and never broadening the change beyond resolving the conflict. Keep the tests green and obey ${standardInstruction}.\n` +
      `Commit the rebased result on ${record.branch}, then re-run the full gate suite and report the real result.`,
    { label: `reconcile:#${record.number}`, phase: 'Implement', schema: IMPLEMENT_SCHEMA, isolation: 'worktree', ...roleTuning(roles.implementer) },
  )

// Targeted re-verify of ONLY the conflict resolution a reconcile just produced — a
// single adversarial agent, never the whole panel, mirroring reverifyFindings. It
// confirms the rebase kept both sides' concerns and introduced no regression, and
// returns the same VERDICT_SCHEMA a lens does. Read-only reviewer (no worktree),
// bound by the shared constraints: it must not push, merge, or close the issue.
const reverifyReconcile = (number, impl) =>
  agent(
    `Adversarially re-verify branch ${impl.branch} for issue #${number} ("${titleOf(number)}") after a reconcile — a rebase onto the advanced default that resolved integration conflicts.\n` +
      `Review ONLY the conflict resolution: confirm the rebase kept BOTH sides' concerns — this issue's change AND whatever landed on the default under it — with no side silently dropped and no regression introduced. Do NOT re-review the whole change or re-run the full verifier panel.\n` +
      `You did NOT write this code. Read the issue's contract (\`gh issue view ${number} --comments\`; if an Agent Brief comment exists it is authoritative, OTHERWISE the issue body and its acceptance criteria are the contract) and ${standardInstruction}.\n` +
      `${AGENT_CONSTRAINTS}\n` +
      `Check ONLY what the gates cannot — do not re-check lint, build, or tests that already passed. Return clear=true only when the resolution is sound with no dropped concern or regression; otherwise clear=false with the specific problems.`,
    { label: `reconcile-reverify:#${number}`, phase: 'Verify', schema: VERDICT_SCHEMA, ...roleTuning(roles.judgment) },
  )

// Bounded reconcile -> targeted re-verify -> land loop for a verified branch that
// hit a genuine integration conflict (#46 fix 2; the wave loop gates this on merge
// mode, where landing is authorised and the branch can rebase onto the real
// default). Each round rebases+resolves on the branch, re-verifies ONLY the
// resolution (its verdict runs through blockingFindings, so a dead / not-clear
// review never lands an unconfirmed resolution), then lands via the same linear
// fast-forward integrate step. It parks only when the re-verify blocks, the branch
// fails to land for a NON-conflict reason, or the maxFixRounds cap is hit — never
// looping forever, mirroring the per-issue fix cap. The reconciled branch is
// tracked in builtBranches so teardown removes its worktree too.
const reconcileAndIntegrate = async (record) => {
  let current = record
  for (let round = 1; round <= maxFixRounds; round += 1) {
    log(`#${record.number}: reconcile round ${round}/${maxFixRounds} — rebasing the verified branch onto the advanced default`)

    // Rebase + minimal resolve on the feature branch; a dead agent parks it.
    const rebased = await reconcile(current)
    if (rebased == null) return { ...current, status: 'parked', blockers: [...current.blockers, 'reconcile agent returned nothing'] }
    current = { ...current, branch: rebased.branch || current.branch }
    if (current.branch) builtBranches.add(current.branch)

    // Targeted re-verify of ONLY the resolution; a dead or not-clear verdict blocks.
    const recheck = await reverifyReconcile(record.number, current)
    const findings = blockingFindings(recheck ? [recheck] : [])
    if (findings.length > 0) {
      return { ...current, status: 'parked', blockers: [...current.blockers, `reconcile re-verify blocked: ${findings.map((finding) => finding.title).join('; ')}`] }
    }

    // Land the reconciled branch through the same fast-forward integrate step. A
    // clean land returns done; a fresh genuine conflict may loop within the cap;
    // any other landing failure parks as-is.
    const landedRecord = await integrate({ ...current, status: 'done' })
    if (landedRecord.status === 'done') return landedRecord
    if (!isReconcilableConflict(landedRecord)) return landedRecord
    current = landedRecord
  }
  return { ...current, status: 'parked', blockers: [...current.blockers, `reconcile cap hit after ${maxFixRounds} round(s): the branch still conflicts with the default`] }
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
    { label: 'integration-review', phase: 'Verify', schema: VERDICT_SCHEMA, ...roleTuning(roles.judgment) },
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
    { label: 'integration-hotfix', phase: 'Implement', schema: IMPLEMENT_SCHEMA, isolation: 'worktree', ...roleTuning(roles.implementer) },
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
      // unlanded prerequisite(s) and is carried in `blockers` — the field the report
      // surfaces for a parked issue (it shows `verify` only for a done one) — so the
      // report points at the real cause. Because a skipped issue is never added to
      // `landed`, this same check parks every downstream dependent in turn — the
      // transitive cascade.
      const missing = unlandedPrerequisites(issuesByNumber.get(number)?.blocked_by, issuesByNumber, landed)
      if (missing.length > 0) {

        // Build a MODE-AWARE park reason. In merge mode a missing prerequisite
        // genuinely failed to land (parked/blocked/failed integrate). In PR mode
        // NOTHING merges, so a prerequisite is off the base for one of two reasons an
        // honest report must not conflate: one that INTEGRATED opened a pull request
        // and is merely unmerged — re-running with --merge (or waiting for that PR)
        // lands it; one that did NOT integrate parked or failed with its own real
        // reason in its own record, which --merge cannot conjure, so point the human
        // at that record rather than a pull request that was never opened.
        const named = missing.map((prereq) => `#${prereq}`).join(', ')
        let reason
        if (merge) {
          reason = `prerequisite did not land: ${named}`
        } else {
          const openedPr = new Set(verdicts.map((verdict) => verdict.number))
          const unmerged = missing.filter((prereq) => openedPr.has(prereq)).map((prereq) => `#${prereq}`)
          const incomplete = missing.filter((prereq) => !openedPr.has(prereq)).map((prereq) => `#${prereq}`)
          const clauses = []
          if (unmerged.length > 0) clauses.push(`prerequisite opened a pull request but is not merged onto the base: ${unmerged.join(', ')} — re-run with --merge (or after that PR merges) to build this issue on a base that contains it`)
          if (incomplete.length > 0) clauses.push(`prerequisite did not complete — see its own parked record: ${incomplete.join(', ')}`)
          reason = clauses.join('; ')
        }

        parked.push({ ...toRecord(number, null, 'parked', reason), blockers: [reason] })
        continue
      }

      // Preflight idempotence guard (#49): BEFORE dispatching an implementer,
      // a mechanical preflight agent gathers the issue's durable landing state
      // and `preflightDecision` maps it to a verdict, so a blind cross-session
      // restart (Workflow resume is same-session-only — a relaunch re-runs the
      // whole plan) never re-implements work that already landed. A dead
      // preflight decodes to `dispatch`, so its failure only ever falls back to
      // the pre-#49 behaviour, never a wrongful skip.
      const facts = await preflight(number)
      const verdict = preflightDecision(facts, merge)
      if (verdict === 'already-landed') {
        const note = `already landed on the default branch (durable marker${facts?.landedSha ? ` ${facts.landedSha}` : ''}); no implementer dispatched`
        log(`#${number}: ${note} — skipping`)
        verdicts.push(toRecord(number, null, 'already-landed', note))
        // Its work is PROVEN on the default tip (the preflight ancestry check),
        // so it is on the base a dependent forks from in EITHER mode — unblock
        // its dependents unconditionally, unlike a this-run integration (which
        // lands on the base only in merge mode) or an already-open PR (never on
        // the base).
        landed.add(number)
        continue
      }
      if (verdict === 'landed-marker-stale') {
        const reason = `landed-marker present${facts?.landedSha ? ` (${facts.landedSha})` : ''} but its commit is NOT an ancestor of the default tip — reverted, rebased away, or foreign history; parked for a human to reconcile, never rebuilt (#49)`
        log(`#${number}: ${reason}`)
        parked.push({ ...toRecord(number, null, 'landed-marker-stale', ''), blockers: [reason] })
        continue
      }
      if (verdict === 'already-open') {
        const note = `an orchestrate-opened pull request already exists for this issue (PR mode); skipped without opening a duplicate (#49)`
        log(`#${number}: ${note}`)
        verdicts.push(toRecord(number, null, 'already-open', note))
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
      let integrated = await integrate(record)

      // #46 reconcile: a verified branch that failed to land ONLY because rebasing
      // onto the advanced default hit a genuine content conflict is not parked
      // outright — a bounded reconcile (rebase+resolve -> targeted re-verify -> land)
      // repairs it before parking. Merge mode only: PR mode lands nothing on the
      // default, so there is no default to rebase onto. This should not fire in the
      // ordinary serial run (each branch is cut off the current default tip, so
      // ff-only holds), but it salvages the rare case the default moved anyway.
      if (merge && isReconcilableConflict(integrated)) {
        integrated = await reconcileAndIntegrate(record)
      }

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
  // issue THIS run (integratedThisRun — the only case a combined change set
  // exists; a preflight skip carries no branch and does not count), one
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
  // The review covers only what THIS run actually integrated — records that
  // produced a feature branch. A preflight skip (already-landed / already-open,
  // #49) carries no branch: its work is prior, not part of this run's combined
  // change set, so it must neither trigger the review nor pollute the PR-mode
  // branch union with an `undefined` entry.
  const integratedThisRun = verdicts.filter((verdict) => verdict.branch)
  if (integratedThisRun.length > 0) {
    let review = await integrationReview(integratedThisRun)
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
      review = await integrationReview(integratedThisRun)
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
      { label: 'teardown:worktrees', phase: 'Integrate', ...roleTuning(roles.mechanical) },
    )
  }
}

return { verdicts, parked, integration: integrationOutcome }
