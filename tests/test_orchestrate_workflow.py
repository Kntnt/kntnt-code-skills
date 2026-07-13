"""Tests for the orchestrate Workflow engine and its extracted helpers.

Two concerns are covered here, because the engine lives in two files that must
stay in lock-step:

1. A *structural* test on ``skills/orchestrate/orchestrate.workflow.js``: the
   Workflow harness tolerates only a single leading ``export const meta`` and
   rejects any other top-level ``export`` (or ``import``) with a
   ``SyntaxError`` at launch. A passing ``node --check`` is necessary but not
   sufficient — modern Node auto-detects ESM and accepts multiple exports — so
   the real contract is asserted here by parsing the file directly.

2. A *behavioural* test on ``lib/orchestrate/engine-helpers.mjs``: the workflow
   cannot ``import`` (the harness forbids a top-level ``import``), so it keeps
   its own inline copies of ``normalizeArgs`` and ``planIsEmpty``. That
   importable ES module is the tested source of truth for the same logic; the
   test shells out to ``node`` to exercise it. It skips when ``node`` is absent
   so a node-less CI does not fail, but it runs for real wherever node exists.

Run with: `uv run --with pytest pytest -q`
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / "skills" / "orchestrate" / "orchestrate.workflow.js"
ENGINE_HELPERS = REPO_ROOT / "lib" / "orchestrate" / "engine-helpers.mjs"


# --- structural: single top-level export, no top-level import ----------------


def _top_level_lines(source: str, keyword: str) -> list[str]:
    """Every line that begins the given keyword at column 0 (no indentation).

    The Workflow harness is line/column sensitive: a top-level statement is one
    flush against the left margin, so a naive column-0 scan matches the harness'
    own view rather than a full parse."""

    return [line for line in source.splitlines() if line.startswith(f"{keyword} ")]


def test_workflow_has_exactly_one_top_level_export() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    exports = _top_level_lines(source, "export")
    assert len(exports) == 1, f"expected exactly one top-level export, found: {exports}"
    assert exports[0].startswith("export const meta"), exports[0]


def test_workflow_has_no_top_level_import() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert _top_level_lines(source, "import") == []


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
    assert out["norm_json"] == {"waves": [[1]], "merge": True}
    assert out["norm_object"] == {"waves": [], "keep": 1}
    assert out["norm_malformed"] == {}
    assert out["norm_undefined"] == {}
    assert out["norm_null"] == {}

    # planIsEmpty: no waves or an empty waves list is empty; a real wave is not.
    assert out["empty_empty"] is True
    assert out["empty_waves_empty"] is True
    assert out["empty_waves_full"] is False
