/**
 * Tested source of truth for two pure helpers the orchestrate engine relies on:
 * `normalizeArgs` and `planIsEmpty`. The engine at
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
