/**
 * Tested source of truth for the pure helpers the orchestrate engine relies on:
 * `normalizeArgs`, `planIsEmpty`, `blockingFindings`, `unlandedPrerequisites`,
 * `roleTuning`, and `shouldEscalateInSitu`. The engine at
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
