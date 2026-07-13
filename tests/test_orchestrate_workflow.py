"""Tests for the orchestrate Workflow engine and its extracted helpers.

Three concerns are covered here, because the engine lives in two files that
must stay in lock-step:

1. A *structural* test on ``skills/orchestrate/orchestrate.workflow.js``: the
   Workflow harness tolerates only a single leading ``export const meta`` and
   rejects any other top-level ``export`` (or ``import``) with a
   ``SyntaxError`` at launch. A passing ``node --check`` is necessary but not
   sufficient — modern Node auto-detects ESM and accepts multiple exports — so
   the real contract is asserted here by parsing the file directly.

2. A *drift guard* over both files: the workflow keeps its own inline copies of
   ``normalizeArgs`` and ``planIsEmpty`` (it cannot ``import`` them — the
   harness forbids a top-level ``import``), and the whole design rests on those
   copies staying byte-identical to ``lib/orchestrate/engine-helpers.mjs``
   modulo the one ``export `` keyword. That invariant is enforced here rather
   than left to a comment.

3. A *behavioural* test on ``lib/orchestrate/engine-helpers.mjs`` — the tested
   source of truth for the same logic. The test shells out to ``node`` to
   exercise it. It skips when ``node`` is absent so a node-less CI does not
   fail, but it runs for real wherever node exists.

Run with: `uv run --with pytest pytest -q`
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / "skills" / "orchestrate" / "orchestrate.workflow.js"
ENGINE_HELPERS = REPO_ROOT / "lib" / "orchestrate" / "engine-helpers.mjs"


# --- structural: single top-level export, no top-level import ----------------


def _top_level_lines(source: str, keyword: str) -> list[str]:
    """Every source line that begins a top-level ``export``/``import``.

    A top-level statement is one whose keyword opens the line, allowing legal
    leading whitespace (indentation is valid ESM — the harness parses, it does
    not column-scan) and space-less forms like ``export{x}`` or
    ``import{x}from…``. The ``\\b`` after the keyword avoids matching an
    identifier such as ``exported`` or a property named ``exports``."""

    pattern = re.compile(rf"^\s*{keyword}\b")
    return [line for line in source.splitlines() if pattern.match(line)]


def test_workflow_has_exactly_one_top_level_export() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    exports = _top_level_lines(source, "export")
    assert len(exports) == 1, f"expected exactly one top-level export, found: {exports}"
    assert exports[0].strip().startswith("export const meta"), exports[0]


def test_workflow_has_no_top_level_import() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert _top_level_lines(source, "import") == []


# --- drift guard: the inline copies match the exported source of truth -------


def _extract_def(source: str, name: str) -> str:
    """Extract the ``const <name> = …`` definition, stripping a leading
    ``export `` first so an inline copy and its exported twin compare equal
    modulo that one keyword.

    A block-bodied arrow (``… => { … }``) is captured through its balanced
    closing brace; an expression-bodied arrow (``… => expr``) to the end of its
    physical line. The declaration's own JSDoc sits above the ``const`` line and
    is deliberately excluded — this compares the runtime logic, not the prose."""

    normalised = re.sub(r"^export const ", "const ", source, flags=re.MULTILINE)
    match = re.search(rf"^const {re.escape(name)} = ", normalised, flags=re.MULTILINE)
    assert match is not None, f"`const {name} =` not found"
    start = match.start()

    arrow = normalised.index("=>", start)
    body = arrow + len("=>")
    while normalised[body].isspace():
        body += 1

    if normalised[body] == "{":
        depth = 0
        for index in range(body, len(normalised)):
            char = normalised[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return normalised[start : index + 1]
        raise AssertionError(f"unbalanced braces while extracting `{name}`")

    return normalised[start : normalised.index("\n", start)]


def test_inline_copies_match_engine_helpers() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    helpers = ENGINE_HELPERS.read_text(encoding="utf-8")
    for name in ("normalizeArgs", "planIsEmpty"):
        assert _extract_def(workflow, name) == _extract_def(helpers, name), (
            f"the inline `{name}` in orchestrate.workflow.js has drifted from "
            f"lib/orchestrate/engine-helpers.mjs — keep the two byte-identical"
        )


# --- worktree isolation and teardown (issue #14) -----------------------------

# Every code-touching agent (implement, fix, and any future salvage/hotfix) must
# run in its own git worktree so no two agents — and no agent and the launcher —
# ever share a working directory. The verify agents are read-only reviewers and
# need no worktree; the integrate agent is the SOLE mutator of the default branch
# and operates on the real repo, so it must NOT be worktree-isolated. These tests
# are structural: they read the workflow source (the harness makes it
# un-importable) and assert the required constructs.


def _agent_block(source: str, name: str) -> str:
    """Slice one top-level ``const <name> = …`` block out of the workflow source.

    A whole-file grep for ``isolation: 'worktree'`` is useless here — one agent
    already carries it, so the grep would pass even with another agent unfixed.
    This isolates a single ``const`` definition instead: from the ``const
    <name> = `` line up to the next top-level ``const `` declaration or the first
    blank line, whichever comes first. Both the multi-line ``agent(…)`` calls and
    a block-bodied arrow are captured up to (and including) their agent options,
    which is all these assertions inspect."""

    lines = source.splitlines()
    start = next(
        (
            i
            for i, line in enumerate(lines)
            if re.match(rf"^const {re.escape(name)} = ", line)
        ),
        None,
    )
    assert start is not None, f"`const {name} =` not found in the workflow source"

    block = [lines[start]]
    for line in lines[start + 1 :]:
        if line.strip() == "" or re.match(r"^const ", line):
            break
        block.append(line)
    return "\n".join(block)


def test_fix_agent_is_worktree_isolated() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "fix")
    assert "isolation: 'worktree'" in block, (
        "the `fix` agent must carry isolation: 'worktree' — it touches code and "
        "must never share a working directory with another agent or the launcher"
    )


def test_implement_agent_is_worktree_isolated() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "implement")
    assert "isolation: 'worktree'" in block, (
        "the `implement` agent must keep isolation: 'worktree'"
    )


def test_integrate_agent_is_not_worktree_isolated() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "integrate")
    assert "isolation" not in block, (
        "the `integrate` agent is the sole mutator of the default branch and must "
        "operate on the real repo — it must NOT be worktree-isolated"
    )


def test_teardown_wave_dispatch_is_wrapped_in_try_finally() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    # There is exactly one `finally` (normalizeArgs uses a try/catch, no finally);
    # the try that pairs with it is the nearest `try {` before it, and the wave
    # loop must sit between them so teardown always runs — clean or parked.
    finally_idx = source.index("finally")
    try_idx = source.rindex("try {", 0, finally_idx)
    wave_idx = source.index("for (let index = 0; index < waves.length")
    assert try_idx < wave_idx < finally_idx, (
        "the wave-dispatch loop must be inside the try that pairs with the "
        "teardown finally, so teardown runs on both the clean and parked paths"
    )


def test_teardown_agent_prunes_worktrees_and_preserves_branch_refs() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    tail = source[source.index("finally") :]

    # The teardown agent enumerates, removes (keeping the ref), and prunes.
    assert "git worktree list --porcelain" in tail
    assert "git worktree remove --force" in tail
    assert "git worktree prune" in tail

    # It must preserve every branch ref and never touch the main worktree.
    lowered = tail.lower()
    assert "branch ref" in lowered, "teardown must be told to preserve branch refs"
    assert "git branch -d" in lowered, "teardown must be told never to delete a branch"
    assert "main worktree" in lowered, "teardown must never touch the main worktree"


# --- behavioural: the extracted helpers, exercised through node --------------

# The JS harness imports the extracted module by absolute file:// URL, runs the
# same helpers over a table of inputs, and prints the results as JSON for the
# Python side to assert on. `__MODULE_URL__` is substituted with the module's
# file:// URI so the module resolves regardless of the working directory.
_HARNESS = """
import { normalizeArgs, planIsEmpty } from "__MODULE_URL__";
const out = {
  norm_json: normalizeArgs('{"waves":[[1]],"merge":true}'),
  norm_malformed: normalizeArgs("{not json"),
  norm_object: normalizeArgs({ waves: [], keep: 1 }),
  norm_undefined: normalizeArgs(undefined),
  norm_null: normalizeArgs(null),
  norm_null_string: normalizeArgs("null"),
  empty_empty: planIsEmpty({}),
  empty_waves_empty: planIsEmpty({ waves: [] }),
  empty_waves_full: planIsEmpty({ waves: [[1]] }),
};
process.stdout.write(JSON.stringify(out));
"""


def test_engine_helpers_behaviour() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available on this machine")

    harness = _HARNESS.replace("__MODULE_URL__", ENGINE_HELPERS.resolve().as_uri())
    result = subprocess.run(
        [node, "--input-type=module"],
        input=harness,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    out = json.loads(result.stdout)

    # normalizeArgs: a JSON string parses; an object passes through; a malformed
    # string and both null-ish inputs degrade to an empty plan rather than throw.
    # The JSON string "null" parses to `null`, which the `?? {}` clause coerces.
    assert out["norm_json"] == {"waves": [[1]], "merge": True}
    assert out["norm_object"] == {"waves": [], "keep": 1}
    assert out["norm_malformed"] == {}
    assert out["norm_undefined"] == {}
    assert out["norm_null"] == {}
    assert out["norm_null_string"] == {}

    # planIsEmpty: no waves or an empty waves list is empty; a real wave is not.
    assert out["empty_empty"] is True
    assert out["empty_waves_empty"] is True
    assert out["empty_waves_full"] is False
