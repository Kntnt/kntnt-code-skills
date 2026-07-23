/**
 * Tested source of truth for the pure helpers the orchestrate engine relies on:
 * `normalizeArgs`, `planIsEmpty`, `blockingFindings`, `unlandedPrerequisites`,
 * `roleTuning`, `shouldEscalateInSitu`, `withInSituHazard`,
 * `isReconcilableConflict`, and `preflightDecision`. The engine at
 * `skills/orchestrate/orchestrate.workflow.js` keeps byte-for-byte identical
 * inline copies of these, because the Workflow harness forbids any top-level
 * `import` in a workflow script (it tolerates only a single leading
 * `export const meta`). This module exists solely so that logic can be unit
 * tested; keep the two in sync. Covered by `tests/test_orchestrate_workflow.py`.
 */

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
export const normalizeArgs = (raw) => {

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
export const planIsEmpty = (config) => !Array.isArray(config.waves) || config.waves.length === 0

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
export const blockingFindings = (verdicts) => {

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
export const unlandedPrerequisites = (blockedBy, inScope, landed) => {

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
export const roleTuning = (role) => {

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
export const shouldEscalateInSitu = (report, panel) => {

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
export const withInSituHazard = (lenses, hazard) => {

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
export const isReconcilableConflict = (record) => record != null && record.status === 'parked' && record.conflict === true

/**
 * The specific reason a merge-mode landing did NOT verifiably reach disk, or
 * `null` when the integrator's reported facts prove it did (issue #53). The
 * integrate step lands by fast-forwarding the default branch's WORK TREE to the
 * feature tip; a bare repository, a default branch not checked out in the
 * integrating worktree, or a ref that moved without the tree following (a
 * `git update-ref` / `git branch -f` / `git push .` "landing") advances the
 * pointer while leaving the code off disk — so the gates and the mandatory final
 * re-run then test the STALE checkout while the run reports "landed". The engine
 * cannot run git itself, so the integrator reports the raw post-land facts and
 * THIS helper — not the agent's own `integrated` boolean — decides whether the
 * land is sound, mirroring how `preflightDecision` turns gathered facts into a
 * verdict. A non-null return is a loud, specific park reason; the caller never
 * records `integrated: true` over a stranded working tree.
 *
 * `result` is the integrator's INTEGRATE_SCHEMA result (merge mode, already known
 * to claim `integrated: true`):
 *   - `bareRepo`          `git rev-parse --is-bare-repository` returned true
 *   - `defaultCheckedOut` the default branch is checked out in THIS worktree
 *   - `headSha`           `git rev-parse HEAD` on the default after the ff
 *   - `featureSha`        the feature branch tip `git rev-parse <branch>`
 *   - `worktreeClean`     `git status --porcelain` was empty at the landed tip
 *
 * @param {{bareRepo?: boolean, defaultCheckedOut?: boolean, headSha?: string,
 *   featureSha?: string, worktreeClean?: boolean}|null|undefined} result The
 *   integrator's reported post-land facts.
 * @returns {string|null} A specific blocker when the land is not proven on disk;
 *   `null` when the reported facts confirm the tree advanced to the feature tip.
 */
export const landStrandedBlocker = (result) => {

  // Refuse a bare repo or a worktree not on the default branch: neither can
  // receive the land in its work tree, so any "advance" moves the ref alone —
  // exactly the corruption the guard forbids. Refuse before trusting any sha.
  const r = result || {}
  if (r.bareRepo === true) return 'integration refused: the repository is bare (core.bare=true), so a landing advances the ref without updating any working tree — repair the repository before re-running'
  if (r.defaultCheckedOut !== true) return 'integration refused: the default branch is not checked out in the integrating worktree, so a landing here would strand the working tree at its pre-run commit'

  // Prove the land reached disk: the default HEAD must equal the feature tip
  // with a clean tree. A missing sha, an unmoved HEAD, or a dirty tree is a
  // ref-only advance — reported as a failed land, never `integrated: true`.
  if (typeof r.headSha !== 'string' || r.headSha.length === 0) return 'integration unverified: the integrator reported no post-landing HEAD sha, so the land cannot be confirmed to have reached disk'
  if (typeof r.featureSha !== 'string' || r.featureSha.length === 0) return 'integration unverified: the integrator reported no feature-branch tip sha, so the land cannot be confirmed to have reached disk'
  if (r.headSha !== r.featureSha) return `integration stranded: the default branch HEAD (${r.headSha}) did not advance to the feature tip (${r.featureSha}) — the ref moved without updating the working tree (a ref-only advance)`
  if (r.worktreeClean !== true) return 'integration stranded: the working tree is not clean at the landed commit, so the land did not cleanly reach disk'

  return null

}

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
export const preflightDecision = (facts, merge) => {

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
