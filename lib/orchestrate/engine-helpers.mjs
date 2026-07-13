/**
 * Tested source of truth for the pure helpers the orchestrate engine relies on:
 * `normalizeArgs`, `planIsEmpty`, and `blockingFindings`. The engine at
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
 * @returns {object} The normalized config the engine consumes:
 *   `{ waves, issues, merge, maxFixRounds, standardsPath, budgetFloor }`.
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
