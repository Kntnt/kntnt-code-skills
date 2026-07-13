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


def _exported_const_names(source: str) -> list[str]:
    """Every ``export const <name> = `` name in a module, in source order.

    Driving the drift guard off this list means a newly extracted helper is
    compared automatically — the guard never silently narrows to a stale pair."""

    return re.findall(r"^export const (\w+) = ", source, flags=re.MULTILINE)


def test_inline_copies_match_engine_helpers() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    helpers = ENGINE_HELPERS.read_text(encoding="utf-8")

    # The guard compares every helper the module exports, not a hardcoded pair,
    # so an added pure helper (like `blockingFindings`) is drift-checked too.
    names = _exported_const_names(helpers)
    assert "blockingFindings" in names, (
        "engine-helpers.mjs must export `blockingFindings` as the tested source "
        "of truth for the integrate-only-when-cleared logic"
    )
    for name in names:
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
    <name> = `` line up to the next *top-level boundary* — the next line at column
    zero that opens a new top-level construct (``const ``/``export ``/``return ``
    or a ``//`` comment). It deliberately does NOT stop at a blank line, so a
    readability blank line *inside* an agent function no longer truncates the
    block; the whole ``agent(…)`` call and its options are captured, which is all
    these assertions inspect. Everything inside a block is indented, so only a
    genuine column-zero dedent — never an inner statement — ends it."""

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
        if re.match(r"^(const |export |return |//)", line):
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


def test_fix_agent_reconciles_the_branch_lock() -> None:
    # A worktree-isolated `fix` gets a FRESH worktree, but its target branch is
    # still checked out in the implementer's (or a prior fix round's) persisted
    # worktree, and git forbids checking out one branch in two worktrees at once.
    # The prompt must tell `fix` to free that other worktree first, keeping the
    # branch ref, before it takes the branch over — otherwise the checkout fails
    # and the fixes are lost.
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "fix")
    lowered = block.lower()
    assert "git worktree list --porcelain" in block, (
        "the `fix` prompt must locate the other worktree holding the target branch"
    )
    assert "git worktree remove --force" in block, (
        "the `fix` prompt must free the worktree that still holds the target branch"
    )
    assert "branch ref" in lowered, (
        "freeing the lock must preserve the branch ref (remove keeps it)"
    )
    assert "git branch -d" in lowered, (
        "the `fix` prompt must forbid deleting the branch"
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

    # Anchor on the `finally {` block itself, not the bare word (which also
    # appears in explanatory comments). The try that pairs with it is the nearest
    # `try {` before it, and the wave loop must sit between them so teardown
    # always runs — clean or parked.
    finally_idx = source.index("finally {")
    try_idx = source.rindex("try {", 0, finally_idx)
    wave_idx = source.index("for (let index = 0; index < waves.length")
    assert try_idx < wave_idx < finally_idx, (
        "the wave-dispatch loop must be inside the try that pairs with the "
        "teardown finally, so teardown runs on both the clean and parked paths"
    )


def test_teardown_agent_prunes_worktrees_and_preserves_branch_refs() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    tail = source[source.index("finally {") :]

    # The teardown agent enumerates, removes (keeping the ref), and prunes.
    assert "git worktree list --porcelain" in tail
    assert "git worktree remove --force" in tail
    assert "git worktree prune" in tail

    # It must preserve every branch ref and never touch the main worktree.
    lowered = tail.lower()
    assert "branch ref" in lowered, "teardown must be told to preserve branch refs"
    assert "git branch -d" in lowered, "teardown must be told never to delete a branch"
    assert "main worktree" in lowered, "teardown must never touch the main worktree"


# --- shared safe-state constraints (issue #15) -------------------------------

# Every code-touching sub-agent must be forbidden — in ONE place, reused, never
# copy-pasted divergently — from closing the GitHub issue, pushing to a remote,
# merging into the default branch, or running destructive git that can lose
# committed work (`git reset --hard` on a feature branch), and handed one safe
# clean-start recipe instead. The forbidding text lives in a single module-level
# constant interpolated into the implement, fix, and verify prompts; integrate is
# deliberately excluded because merging/pushing to the default branch is its job.

CONSTRAINTS_NAME = "AGENT_CONSTRAINTS"


def test_agent_constraints_declared_exactly_once() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    decls = re.findall(
        rf"^const {re.escape(CONSTRAINTS_NAME)} = ", source, flags=re.MULTILINE
    )
    assert len(decls) == 1, (
        f"expected exactly one top-level `const {CONSTRAINTS_NAME} =`, found "
        f"{len(decls)} — the forbidding text must be defined once and reused, "
        f"not copy-pasted divergently"
    )


def test_agent_constraints_text_covers_the_forbidden_actions() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, CONSTRAINTS_NAME)
    lowered = block.lower()

    # It forbids the three shared-state mutations reserved for the orchestrator
    # and the integrate step.
    assert "close" in lowered, "constraints must forbid closing the issue"
    assert "push" in lowered, "constraints must forbid pushing to a remote"
    assert "merge" in lowered, "constraints must forbid merging into the default branch"

    # It forbids the destructive git that silently loses committed work, and
    # gives the one non-destructive clean-start recipe in its place.
    assert "git reset --hard" in block, (
        "constraints must forbid `git reset --hard` on a feature branch"
    )
    assert "git checkout -f" in block, (
        "constraints must give the safe clean-start checkout"
    )
    assert "git checkout -- ." in block, (
        "constraints must discard only tracked working-tree changes"
    )


def test_code_touching_prompts_reference_the_constraints() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    reference = "${" + CONSTRAINTS_NAME + "}"
    for name in ("implement", "fix", "verify", "reverifyFindings"):
        block = _agent_block(source, name)
        assert reference in block, (
            f"the `{name}` prompt must interpolate {reference} so the shared "
            f"forbidding text reaches the sub-agent"
        )


def test_integrate_prompt_excludes_the_constraints() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    reference = "${" + CONSTRAINTS_NAME + "}"
    block = _agent_block(source, "integrate")
    assert reference not in block, (
        "the `integrate` agent must NOT carry the forbidding text — merging and "
        "pushing to the default branch is precisely its job"
    )


def test_agent_block_spans_an_internal_blank_line() -> None:
    # `verify` carries a readability blank line inside its arrow body; the block
    # extractor must still return the WHOLE function — from the `const` header to
    # its final statement — rather than truncating at that blank line. Otherwise
    # reinserting a blank line inside any agent function (a routine edit in the
    # next engine issue) would silently break the reference and negative
    # assertions above without anything actually being wrong.
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "verify")
    assert "" in [line.strip() for line in block.splitlines()], (
        "this guard is only meaningful while `verify` actually holds a blank line"
    )
    assert block.startswith("const verify = "), block[:40]
    assert "verdicts.filter(Boolean)" in block, (
        "the block must reach the end of the function, past the internal blank "
        "line — proof the extractor no longer truncates on blanks"
    )


# --- linear, incremental integration (issue #16) -----------------------------

# Two invariants reach the default branch differently now. (1) Integration keeps
# feature branches LINEAR: it rebases the branch onto the up-to-date default
# branch and fast-forwards — it must NEVER merge the default branch INTO the
# feature branch or create a merge commit there. (2) Each verified-green issue is
# integrated the MOMENT it goes green — inside the per-issue processing loop,
# before the next issue's build begins — so a mid-run stop leaves every prior
# issue durably landed, not batched to the end and lost. These are structural.


def test_integrate_rebases_and_forbids_merging_default_into_feature() -> None:
    # AC-1: the merge path must rebase the feature branch onto the up-to-date
    # default branch and fast-forward ONLY, and must explicitly forbid the inverse
    # — merging the default branch INTO the feature branch, which would create a
    # merge commit and break linear history. The explicit forbid clause is what
    # was missing.
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "integrate")
    lowered = block.lower()

    # Rebase-then-fast-forward is the only landing path.
    assert "rebase" in lowered, "integrate must rebase the feature branch"
    assert "fast-forward" in lowered, (
        "integrate must fast-forward, not create a merge commit"
    )

    # The inverse is explicitly, unmistakably forbidden.
    assert "never merge the default branch into" in lowered, (
        "integrate must explicitly forbid merging the default branch INTO the "
        "feature branch"
    )
    assert "merge commit" in lowered, (
        "integrate must explicitly forbid creating a merge commit on the feature branch"
    )
    assert "linear" in lowered, "integrate must state the history stays linear"


def test_each_green_issue_integrates_immediately_not_batched() -> None:
    # AC-2/AC-3: integration is per-issue and inline, not a post-build batch. The
    # old engine built an ENTIRE wave concurrently (`parallel(wave.map(...))`) and
    # only then integrated the green ones in a second loop — so a green issue did
    # not land until the whole wave finished, and a mid-wave stop lost every
    # already-green-but-not-yet-integrated issue. The rewrite processes issues
    # serially: each issue is built, and if green integrated, before the next
    # issue's build begins.
    source = WORKFLOW.read_text(encoding="utf-8")

    # The wave-level batch build is gone: no whole-wave concurrent build precedes
    # integration.
    assert "parallel(wave.map(" not in source, (
        "the wave-level batch build `parallel(wave.map(...))` must be gone — "
        "building a whole wave before integrating defers each green issue's land"
    )

    # Issues are processed one at a time in a per-issue loop that both builds and
    # integrates.
    assert "for (const number of" in source, (
        "expected a per-issue processing loop over the wave's issue numbers"
    )
    per_issue_idx = source.index("for (const number of")
    finally_idx = source.index("finally {")
    region = source[per_issue_idx:finally_idx]

    # Inside that per-issue loop, the issue is built and — when green —
    # integrated, with no batch parallelism sitting between build and land.
    assert "buildAndVerify(number)" in region, (
        "each issue must be built individually inside the per-issue loop"
    )
    assert "integrate(" in region, (
        "each green issue must be integrated inside the per-issue loop, before "
        "the next issue's build begins"
    )
    assert "parallel(" not in region, (
        "no batch parallelism may sit between per-issue build and integrate — "
        "integration must be immediate, not deferred to a post-build batch"
    )


def test_empty_plan_guard_precedes_the_try_finally() -> None:
    # The loud empty-plan guard must still return before the try/finally wave loop
    # (a misdelivered plan must never masquerade as a clean zero-agent run), and
    # the serial per-issue rewrite must not disturb that ordering.
    source = WORKFLOW.read_text(encoding="utf-8")
    guard_idx = source.index("if (planIsEmpty(config))")
    # Anchor on the try that pairs with the teardown finally (the nearest `try {`
    # before it), not the earlier `try {` inside `normalizeArgs`.
    finally_idx = source.index("finally {")
    try_idx = source.rindex("try {", 0, finally_idx)
    assert guard_idx < try_idx, (
        "the loud empty-plan guard must return before the try/finally wave loop"
    )
    assert "status: 'empty-plan'" in source, (
        "the empty-plan guard must return a non-success status"
    )


def test_budget_floor_parks_without_dispatch_in_per_issue_loop() -> None:
    # The budget-floor behaviour must survive the serial rewrite: before an
    # issue's build starts, a nearly-spent budget parks it (and, because the
    # budget only falls, the rest) without dispatching, so the run ends with a
    # clean report rather than a hard cut-off.
    source = WORKFLOW.read_text(encoding="utf-8")
    per_issue_idx = source.index("for (const number of")
    finally_idx = source.index("finally {")
    region = source[per_issue_idx:finally_idx]
    assert "budget.total && budget.remaining() < budgetFloor" in region, (
        "the per-issue loop must check the budget floor before dispatching a build"
    )
    assert "token budget exhausted before dispatch" in region, (
        "a budget-parked issue must be recorded as parked, not dispatched"
    )


def test_null_build_record_parks_rather_than_silently_dropping() -> None:
    # Anti-silent-failure: a null buildAndVerify result must be parked WITH a
    # reason, not `continue`d away — a silently dropped issue would not even
    # appear in the report. `buildAndVerify` never returns null today, but the
    # defensive branch must fail loud, not vanish the issue.
    source = WORKFLOW.read_text(encoding="utf-8")
    per_issue_idx = source.index("for (const number of")
    finally_idx = source.index("finally {")
    region = source[per_issue_idx:finally_idx]
    assert "if (record == null) continue" not in region, (
        "a null build record must not be silently dropped with a bare continue"
    )
    assert "buildAndVerify returned nothing" in region, (
        "the null-record branch must park the issue with a reason so it still "
        "appears in the report"
    )


# --- lean verification defaults (issue #17) ----------------------------------

# Verification is lean by default: the DEFAULT verifier panel is a SINGLE broad
# adversarial reviewer (correctness against intent + acceptance criteria, test
# quality, AND any security/data-safety hazard — one lens); maxFixRounds defaults
# to 1; and a fix round re-verifies ONLY the fixed findings via a targeted
# single-agent `reverifyFindings` rather than re-running the whole panel. The
# per-issue `lenses` override still lets planning raise a genuinely high-risk
# issue to 2–3 lenses. These are structural.


def _default_lenses(source: str) -> list[str]:
    """The string entries of the ``const DEFAULT_LENSES = [ … ]`` array literal.

    Finds the array's opening bracket, walks to its balanced close, and returns
    the quoted string lines inside — one per lens, in the repo's
    one-lens-per-line array style."""

    match = re.search(r"^const DEFAULT_LENSES = \[", source, flags=re.MULTILINE)
    assert match is not None, "`const DEFAULT_LENSES = [` not found"
    open_idx = source.index("[", match.start())
    depth = 0
    close_idx = None
    for index in range(open_idx, len(source)):
        if source[index] == "[":
            depth += 1
        elif source[index] == "]":
            depth -= 1
            if depth == 0:
                close_idx = index
                break
    assert close_idx is not None, "unbalanced brackets in DEFAULT_LENSES"
    body = source[open_idx + 1 : close_idx]
    return [line.strip() for line in body.splitlines() if line.strip().startswith("'")]


def test_default_lenses_is_one_broad_adversarial_reviewer() -> None:
    # AC-1: the default panel is ONE broad lens folding correctness + acceptance
    # criteria, test quality, and security/data-safety into a single reviewer.
    source = WORKFLOW.read_text(encoding="utf-8")
    lenses = _default_lenses(source)
    assert len(lenses) == 1, (
        f"the default verifier panel must be a SINGLE broad adversarial reviewer, "
        f"found {len(lenses)} lenses: {lenses}"
    )
    text = lenses[0].lower()
    assert "correctness" in text, "the broad lens must cover correctness"
    assert "acceptance criteria" in text, (
        "the broad lens must cover the acceptance criteria"
    )
    assert "test" in text, "the broad lens must cover test quality"
    assert "security" in text or "data-safety" in text or "data safety" in text, (
        "the broad lens must cover any security/data-safety hazard"
    )


def test_per_issue_lenses_override_still_scales_risk() -> None:
    # AC-1: the risk-scaling mechanism stays — a per-issue `lenses` array still
    # overrides the single-lens default so a high-risk issue can request 2–3.
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "lensesFor")
    assert "issue?.lenses" in block, (
        "lensesFor must still read a per-issue `lenses` override"
    )
    assert "DEFAULT_LENSES" in block, (
        "lensesFor must fall back to the single broad DEFAULT_LENSES"
    )


def test_max_fix_rounds_defaults_to_one() -> None:
    # AC-2: the fix<->verify cap defaults to 1, not 2.
    source = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"const maxFixRounds = config\.maxFixRounds \?\? (\d+)", source)
    assert match is not None, "the maxFixRounds default assignment was not found"
    assert match.group(1) == "1", (
        f"maxFixRounds must default to 1, found `?? {match.group(1)}`"
    )


def test_fix_round_reverifies_only_fixed_findings_not_full_panel() -> None:
    # AC-3: after a fix, re-verify ONLY the fixed findings via the targeted
    # single-agent reverifyFindings — the full-panel verify() runs once, before
    # the loop, and is NEVER re-called inside it.
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "buildAndVerify")

    # The targeted re-verify agent is used.
    assert "reverifyFindings(" in block, (
        "the fix loop must re-verify via the targeted reverifyFindings agent"
    )

    # The full panel runs once, before the fix loop; split at the loop header.
    loop_idx = block.index("for (")
    before, loop = block[:loop_idx], block[loop_idx:]
    assert "verify(" in before, (
        "the full-panel verify() must run once, before the fix loop"
    )
    assert "reverifyFindings(" in loop, (
        "the fix round must call reverifyFindings inside the loop"
    )
    assert "verify(" not in loop, (
        "the fix loop must NOT re-run the full-panel verify() — it re-verifies "
        "only the fixed findings via reverifyFindings"
    )


def test_reverify_findings_is_a_single_agent_not_a_panel() -> None:
    # AC-3: reverifyFindings is ONE targeted adversarial agent, not a parallel
    # panel, and it returns the VERDICT_SCHEMA a verifier does over specific
    # findings.
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "reverifyFindings")
    assert "parallel(" not in block, (
        "reverifyFindings must be a single agent, never a parallel panel"
    )
    assert "VERDICT_SCHEMA" in block, (
        "reverifyFindings must return the same VERDICT_SCHEMA a verifier does"
    )
    assert "findings" in block, (
        "reverifyFindings must be handed the specific findings to re-check"
    )


def test_reverify_findings_is_read_only_and_carries_constraints() -> None:
    # Like verify, reverifyFindings is a read-only reviewer that did NOT write the
    # code, needs no worktree, and is bound by the shared AGENT_CONSTRAINTS.
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "reverifyFindings")
    assert "${" + CONSTRAINTS_NAME + "}" in block, (
        "reverifyFindings must interpolate the shared AGENT_CONSTRAINTS"
    )
    assert "isolation" not in block, (
        "reverifyFindings is a read-only reviewer and needs no worktree isolation"
    )


def test_verifier_agent_count_is_lower_under_lean_defaults() -> None:
    # AC-4: for a default (non-high-risk) issue with one finding, the worst-case
    # number of verifier agents spawned is demonstrably lower than under the
    # previous defaults. Read the real values from the source and compute both.
    source = WORKFLOW.read_text(encoding="utf-8")
    new_lenses = len(_default_lenses(source))
    match = re.search(r"const maxFixRounds = config\.maxFixRounds \?\? (\d+)", source)
    assert match is not None
    new_fix_rounds = int(match.group(1))

    # NEW logic: the panel runs once (new_lenses agents), then each fix round
    # spawns ONE targeted re-verify agent.
    new_agents = new_lenses + new_fix_rounds * 1

    # DOCUMENTED previous defaults: a 3-lens panel re-run in full on the initial
    # pass and every fix round, with 2 fix rounds → 3 * (1 + 2) = 9.
    old_lenses = 3
    old_fix_rounds = 2
    old_agents = old_lenses * (1 + old_fix_rounds)

    assert new_agents < old_agents, (
        f"worst-case verifier agents must drop: new={new_agents} old={old_agents}"
    )
    # Pin the concrete reduction: 2 under the lean defaults, 9 under the old ones.
    assert (new_agents, old_agents) == (2, 9), (
        f"expected the reduction 2 vs 9, got {new_agents} vs {old_agents}"
    )


# --- mandatory adversarial integration review + hotfix loop (issue #18) ------

# After the wave loop and inside the teardown try, whenever the run integrated at
# least one issue (verdicts.length > 0 — the only case a combined change set
# exists), a MANDATORY adversarial integration review examines the real combined
# change set for cross-issue defects with a verifier's full rigor (never a smoke
# test): in merge mode the combined diff on the default branch, in PR mode the
# union of the run's feature branches against the default branch (nothing landed
# there). Its clear decision runs through blockingFindings, so a dead / not-clear
# / empty-findings review cannot pass silently. In merge mode a real finding
# drives a BOUNDED hotfix + re-review — a code-touching agent that carries
# worktree isolation and the shared constraints and creates its branch fresh off
# the default — not a mere report; in PR mode the finding is parked for the human
# (no auto-hotfix). A finding still unresolved at the cap is parked, never
# dropped. These are structural, read off the workflow source.


def test_integration_review_agent_is_adversarial_read_only_reviewer() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "integrationReview")
    lowered = block.lower()

    # Adversarial over the COMBINED diff, with a per-issue verifier's rigor.
    assert "combined diff" in lowered, (
        "the integration review must review the COMBINED diff of the run"
    )
    assert "adversarial" in lowered, "the integration review must be adversarial"
    assert "cross-issue" in lowered, (
        "the integration review must hunt cross-issue defects a per-issue lens misses"
    )
    assert "smoke test" in lowered, (
        "the integration review must state it is NOT a token smoke test"
    )

    # Read-only: it did not write the code, so it needs no worktree.
    assert "isolation" not in block, (
        "the integration reviewer is read-only and must not carry worktree isolation"
    )

    # Bound by the shared constraints and returns the verifier schema.
    assert "${" + CONSTRAINTS_NAME + "}" in block, (
        "the integration reviewer must interpolate the shared AGENT_CONSTRAINTS"
    )
    assert "VERDICT_SCHEMA" in block, (
        "the integration reviewer must return the same VERDICT_SCHEMA a verifier does"
    )


def test_integration_review_is_gated_on_verdicts_and_uses_blocking_findings() -> None:
    # The review runs only when the run integrated at least one issue, and its
    # clear decision goes through the #17 blockingFindings helper so a dead or
    # not-clear review cannot pass silently.
    source = WORKFLOW.read_text(encoding="utf-8")
    guard = "if (verdicts.length > 0)"
    assert guard in source, (
        "the integration review must be gated on verdicts.length > 0 (a combined "
        "diff exists only when the run integrated at least one issue)"
    )
    guard_idx = source.index(guard)
    finally_idx = source.index("finally {")
    region = source[guard_idx:finally_idx]
    assert "integrationReview(" in region, (
        "the integration review must be dispatched in the post-wave region"
    )
    assert "blockingFindings(" in region, (
        "the integration review's clear decision must go through blockingFindings, "
        "so a dead / clear:false / empty-findings review never passes silently"
    )


def test_integration_review_targets_branch_union_in_pr_mode() -> None:
    # In the default PR mode the run opens PRs and lands NOTHING on the default
    # branch, so a review of "the diff on the default branch" would see nothing and
    # clear — the exact silent-pass this review exists to kill, in the default
    # mode. The review must be mode-aware: PR mode reviews the UNION of the run's
    # feature branches against the default branch, so it references the branches.
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "integrationReview")
    lowered = block.lower()
    assert ".branch" in block, (
        "the integration review must reference the run's feature branches so PR "
        "mode reviews the branch union, not an empty default-branch diff"
    )
    assert "union of" in lowered or "feature branch" in lowered, (
        "the integration review prompt must describe the PR-mode branch union"
    )
    assert "merge" in lowered, "the integration review must be mode-aware (merge vs PR)"


def test_integration_review_runs_after_wave_loop_and_before_teardown() -> None:
    # The review sits AFTER the wave loop but INSIDE the try that pairs with the
    # teardown finally, so teardown still fires and any hotfix worktree is torn
    # down too.
    source = WORKFLOW.read_text(encoding="utf-8")
    wave_loop_idx = source.index("for (let index = 0; index < waves.length")
    guard_idx = source.index("if (verdicts.length > 0)")
    finally_idx = source.index("finally {")
    try_idx = source.rindex("try {", 0, finally_idx)
    assert try_idx < wave_loop_idx < guard_idx < finally_idx, (
        "the integration review must run after the wave loop and before the "
        "teardown finally, all inside the teardown try"
    )


def test_integration_hotfix_is_worktree_isolated_and_carries_constraints() -> None:
    # The hotfix is code-touching: it MUST run in its own worktree (#14 — this is
    # the future hotfix agent that comment anticipated) and carry the shared
    # constraints (#15 — it must not merge, push, or close).
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "integrationHotfix")
    assert "isolation: 'worktree'" in block, (
        "the integrationHotfix agent touches code and MUST carry isolation: 'worktree'"
    )
    assert "${" + CONSTRAINTS_NAME + "}" in block, (
        "the integrationHotfix agent must interpolate the shared AGENT_CONSTRAINTS"
    )


def test_integration_hotfix_creates_branch_fresh_off_default() -> None:
    # Each hotfix round uses a distinct branch name, so the copied-from-`fix`
    # worktree handoff could never fire within a run and risked building on a
    # stale ref left by a prior run. The hotfix now creates its branch FRESH off
    # the up-to-date default branch with `git checkout -B`, which resets any stale
    # ref to the current default tip. It keeps worktree isolation and the shared
    # constraints.
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "integrationHotfix")
    assert "git checkout -B" in block, (
        "the integrationHotfix prompt must create its branch fresh off the default "
        "with `git checkout -B` so a stale ref cannot make it build on an old base"
    )
    assert "isolation: 'worktree'" in block, (
        "the integrationHotfix agent must keep isolation: 'worktree'"
    )
    assert "${" + CONSTRAINTS_NAME + "}" in block, (
        "the integrationHotfix agent must keep the shared AGENT_CONSTRAINTS"
    )


def test_integration_hotfix_loop_is_bounded_by_a_cap() -> None:
    # The hotfix loop must be bounded by a documented cap; the hotfix branch must
    # be tracked in builtBranches so teardown removes its worktree too.
    source = WORKFLOW.read_text(encoding="utf-8")
    assert re.search(
        r"const maxIntegrationRounds = config\.maxIntegrationRounds \?\?", source
    ), "the hotfix loop must be bounded by a documented maxIntegrationRounds cap"

    guard_idx = source.index("if (verdicts.length > 0)")
    finally_idx = source.index("finally {")
    region = source[guard_idx:finally_idx]
    assert "integrationHotfix(" in region, (
        "the hotfix agent must be dispatched inside the bounded integration loop"
    )
    assert "maxIntegrationRounds" in region, (
        "the hotfix loop must be capped by maxIntegrationRounds"
    )
    assert "builtBranches.add" in region, (
        "the hotfix branch must be tracked in builtBranches so teardown removes it"
    )


def test_integration_hotfix_loop_is_gated_on_merge_mode() -> None:
    # The bounded auto-hotfix + re-review runs ONLY in merge mode, where landing is
    # authorised and the default branch actually holds the changes a hotfix
    # branched off it can see. In PR mode the finding is parked for the human, not
    # auto-hotfixed — matching the conservative leave-the-merge-to-you posture. So
    # the hotfix loop header must gate on `merge`.
    source = WORKFLOW.read_text(encoding="utf-8")
    guard_idx = source.index("if (verdicts.length > 0)")
    finally_idx = source.index("finally {")
    region = source[guard_idx:finally_idx]
    loop_idx = region.index("for (let round = 1;")
    header = region[loop_idx : region.index("\n", loop_idx)]
    assert "merge" in header, (
        "the hotfix loop header must gate on merge mode so PR-mode findings are "
        "parked for the human, not auto-hotfixed"
    )


def test_unresolved_integration_finding_is_parked_not_dropped() -> None:
    # When the cap is hit with the review still not clear, the unresolved finding
    # must be recorded into the report (parked), never silently dropped.
    source = WORKFLOW.read_text(encoding="utf-8")
    guard_idx = source.index("if (verdicts.length > 0)")
    finally_idx = source.index("finally {")
    region = source[guard_idx:finally_idx]
    assert "parked.push(" in region, (
        "an unresolved integration finding after the cap must be parked into the report"
    )


def test_integration_outcome_is_returned_to_the_caller() -> None:
    # The returned result keeps the { verdicts, parked } shape working and adds the
    # integration outcome so the caller/report can see it.
    source = WORKFLOW.read_text(encoding="utf-8")
    ret_idx = source.rindex("return { verdicts, parked")
    tail = source[ret_idx : ret_idx + 120]
    assert "integration" in tail, (
        "the final return must surface the integration outcome alongside "
        "verdicts and parked"
    )


# --- graceful missing-brief fallback in the prompts (issue #18) --------------

# The implement, verify, and reverify prompts must fall back cleanly when an issue
# has no Agent Brief: if a brief exists it is authoritative, OTHERWISE the issue
# body and its acceptance criteria are the contract. The old "treat the Agent
# Brief as authoritative" wording (brief-only) must be gone from these prompts.


def test_brief_prompts_use_the_fallback_wording_not_brief_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    for name in ("implement", "verify", "reverifyFindings"):
        block = _agent_block(source, name)
        lowered = block.lower()
        assert "otherwise" in lowered, (
            f"the `{name}` prompt must fall back with 'otherwise' when no brief exists"
        )
        assert "acceptance criteria" in lowered, (
            f"the `{name}` prompt must name the acceptance criteria as the fallback"
        )
        assert "body" in lowered, (
            f"the `{name}` prompt must name the issue body as the fallback contract"
        )
        assert 'treat the "agent brief" comment as authoritative' not in lowered, (
            f"the `{name}` prompt must not treat the Agent Brief as the only contract"
        )


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


# `blockingFindings` decides integration: the change lands ONLY when the panel
# explicitly cleared. An empty/absent panel (a dead verifier filtered to nothing)
# and a not-clear verdict carrying no `findings` array both block — the two
# silent-integration escapes the lean single-lens default would otherwise widen.
_BLOCKING_HARNESS = """
import { blockingFindings } from "__MODULE_URL__";
const out = {
  empty: blockingFindings([]),
  not_array: blockingFindings(undefined),
  one_clear: blockingFindings([{ clear: true, summary: 'ok' }]),
  not_clear_no_findings: blockingFindings([{ clear: false, summary: 'x' }]),
  not_clear_with_findings: blockingFindings([{ clear: false, summary: 'x', findings: [{ title: 't', detail: 'd' }] }]),
  mixed: blockingFindings([{ clear: true }, { clear: false, summary: 'y' }]),
};
process.stdout.write(JSON.stringify(out));
"""


def test_blocking_findings_behaviour() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available on this machine")

    harness = _BLOCKING_HARNESS.replace(
        "__MODULE_URL__", ENGINE_HELPERS.resolve().as_uri()
    )
    result = subprocess.run(
        [node, "--input-type=module"],
        input=harness,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    out = json.loads(result.stdout)

    # An empty or non-array panel is never "done": one synthetic blocking finding,
    # so a dead verifier can never integrate unverified.
    assert len(out["empty"]) == 1
    assert len(out["not_array"]) == 1

    # A single explicit clear integrates: no blocking findings.
    assert out["one_clear"] == []

    # A not-clear verdict with no findings still blocks, its detail drawn from the
    # verdict summary rather than vanishing.
    assert len(out["not_clear_no_findings"]) == 1
    assert out["not_clear_no_findings"][0]["detail"] == "x"

    # A not-clear verdict with findings contributes exactly those findings.
    assert out["not_clear_with_findings"] == [{"title": "t", "detail": "d"}]

    # A mixed panel (one clear, one not) blocks on the not-clear verdict.
    assert len(out["mixed"]) == 1


# --- behavioural: toRecord threads the feature branch onto every record ------

# `toRecord` shapes an implementer result into the per-issue record the run
# returns. Downstream, `integrate` reads `record.branch` (the merge/PR prompt) and
# the mandatory integration review reads `verdict.branch` (its PR-mode branch
# union). If `toRecord` drops `impl.branch`, every record carries `branch:
# undefined`: integrate prompts "branch undefined", and the integration review's
# branch-union prompt renders an EMPTY list and clears silently — the exact silent
# pass that review exists to prevent. This test exercises `toRecord`'s real logic
# through node (a stub `titleOf` stands in for the module-level lookup) and asserts
# a DONE record actually CARRIES its branch — a source grep for `.branch` would
# pass even with the field dropped, so the behaviour is checked, not the text.


def _extract_arrow_object_def(source: str, name: str) -> str:
    """Extract a ``const <name> = (…) => ({ … })`` definition whose body is a
    parenthesised object literal.

    Walks balanced ``()[]{}`` from the arrow's first opening bracket to its
    matching close, skipping string literals so a bracket inside a quoted string
    could never end the scan early. This handles the expression-bodied
    object-returning arrow that ``_extract_def`` (single-line / block-bodied) does
    not."""

    match = re.search(rf"^const {re.escape(name)} = ", source, flags=re.MULTILINE)
    assert match is not None, f"`const {name} =` not found"
    start = match.start()

    index = source.index("=>", start) + 2
    while source[index] not in "([{":
        index += 1

    depth = 0
    in_string: str | None = None
    while index < len(source):
        char = source[index]
        if in_string is not None:
            if char == "\\":
                index += 2
                continue
            if char == in_string:
                in_string = None
        elif char in "'\"`":
            in_string = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
        index += 1
    raise AssertionError(f"unbalanced brackets while extracting `{name}`")


# The harness stubs `titleOf` (a module-level lookup in the real engine), injects
# the extracted `toRecord`, and prints a DONE record built from an impl that
# carries a branch plus a PARKED record built from a null impl (optional chaining
# must not throw). `branch ?? null` makes an undefined branch explicit as JSON
# null so the Python side can assert on it rather than see the key vanish.
_TORECORD_HARNESS = """
const titleOf = (number) => `issue ${number}`;
__TORECORD_DEF__;
const impl = {
  branch: 'issue-x',
  gatesSummary: 'gates green',
  gatesPassed: true,
  remainingForHuman: ['r'],
  assumptions: ['a'],
  blockers: [],
};
const done = toRecord(7, impl, 'done', 'verified');
const parked = toRecord(9, null, 'parked', 'implementer returned nothing');
process.stdout.write(JSON.stringify({
  done_branch: done.branch ?? null,
  done_number: done.number,
  done_status: done.status,
  done_title: done.title,
  done_gates: done.gates,
  parked_branch: parked.branch ?? null,
  parked_status: parked.status,
}));
"""


def test_to_record_carries_the_feature_branch() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available on this machine")

    source = WORKFLOW.read_text(encoding="utf-8")
    harness = _TORECORD_HARNESS.replace(
        "__TORECORD_DEF__", _extract_arrow_object_def(source, "toRecord")
    )
    result = subprocess.run(
        [node, "--input-type=module"],
        input=harness,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    out = json.loads(result.stdout)

    # The defect: a DONE record must CARRY impl.branch, or integrate and the
    # integration review both receive `undefined`.
    assert out["done_branch"] == "issue-x", (
        "a done record must carry impl.branch so integrate and the integration "
        "review receive the real feature branch, not undefined"
    )

    # The rest of the record's shape is unchanged: number, status, the stubbed
    # title, and the gates summary all thread through as before.
    assert out["done_number"] == 7
    assert out["done_status"] == "done"
    assert out["done_title"] == "issue 7"
    assert out["done_gates"] == "gates green"

    # A parked record built from a null impl must not throw — branch is sourced
    # through optional chaining, so it is simply absent (null), never an error.
    assert out["parked_branch"] is None
    assert out["parked_status"] == "parked"


# --- skip (park) an issue whose in-scope prerequisite did not land (issue #20) -

# The engine dispatches issues in wave ORDER but must also honour wave OUTCOME:
# before it builds an issue, it consults that issue's in-scope prerequisites and,
# if any did not land (parked, blocked, or failed to integrate), it parks this
# issue with a reason naming the unlanded prerequisite instead of building it on
# an incomplete base. Because a parked issue never enters the `landed` set, the
# skip CASCADES to every downstream dependent transitively. Only IN-SCOPE
# prerequisites count — a `blocked_by` entry outside this run's plan is assumed
# already on the default branch and never blocks. The decision rests on the pure
# `unlandedPrerequisites` helper (tested through node, drift-guarded against its
# inline copy above) plus the engine wiring that feeds it a `landed` set which
# only integrated issues ever enter.


def test_engine_helpers_exports_unlanded_prerequisites() -> None:
    # The skip decision is a pure predicate, so it lives in the tested source of
    # truth alongside the other engine helpers — the drift guard then holds its
    # inline workflow copy byte-identical automatically.
    helpers = ENGINE_HELPERS.read_text(encoding="utf-8")
    names = _exported_const_names(helpers)
    assert "unlandedPrerequisites" in names, (
        "engine-helpers.mjs must export `unlandedPrerequisites` as the tested "
        "source of truth for the skip-when-prerequisite-unlanded decision"
    )


def test_prerequisite_skip_is_consulted_before_the_build_and_parks() -> None:
    # In the per-issue loop the engine must consult unlandedPrerequisites BEFORE
    # dispatching buildAndVerify, and when a prerequisite is unlanded it must park
    # the issue (toRecord + parked.push + continue) rather than build it.
    source = WORKFLOW.read_text(encoding="utf-8")
    per_issue_idx = source.index("for (const number of")
    build_idx = source.index("buildAndVerify(number)")
    prereq_idx = source.index("unlandedPrerequisites(", per_issue_idx)
    assert per_issue_idx < prereq_idx < build_idx, (
        "the engine must consult unlandedPrerequisites inside the per-issue loop "
        "and before buildAndVerify — an unlanded prerequisite must skip the build"
    )
    region = source[prereq_idx:build_idx]
    assert "parked.push(" in region, (
        "a prerequisite-skipped issue must be parked into the report"
    )
    assert "toRecord(" in region, (
        "a prerequisite-skipped issue must be recorded via toRecord so its report "
        "shape matches every other parked issue"
    )
    assert "continue" in region, (
        "a prerequisite-skipped issue must NOT fall through to the build"
    )


def test_prerequisite_park_reason_names_the_unlanded_prerequisite() -> None:
    # The park reason must NAME the unlanded prerequisite(s), not merely say the
    # issue was skipped, so the report points at the real cause.
    source = WORKFLOW.read_text(encoding="utf-8")
    prereq_idx = source.index("unlandedPrerequisites(", source.index("for (const number of"))
    build_idx = source.index("buildAndVerify(number)")
    region = source[prereq_idx:build_idx]
    assert "prerequisite" in region.lower(), (
        "the park reason must mention the prerequisite"
    )
    assert "missing.map(" in region or "${missing" in region, (
        "the park reason must interpolate the unlanded prerequisite numbers"
    )


def test_only_integrated_issues_enter_the_landed_set() -> None:
    # A `landed` set tracks the issues that actually integrated; the skip cascade
    # depends on a parked issue NEVER entering it. So `landed` must be declared and
    # must gain a member ONLY on the successful-integration path (paired with
    # verdicts.push), never on any parked path — enforced by there being exactly
    # one `landed.add(` in the whole engine, on the done branch.
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "const landed = new Set()" in source, (
        "the engine must declare a `landed` set to track integrated issues"
    )
    assert source.count("landed.add(") == 1, (
        "the engine must add to `landed` in exactly one place — the successful "
        "integration path — so a parked issue never counts as landed"
    )
    push_idx = source.index("verdicts.push(integrated)")
    assert "landed.add(" in source[push_idx : push_idx + 140], (
        "an issue must be marked landed on the same path that pushes it to "
        "verdicts — the successful-integration path"
    )


# The predicate itself, exercised through node over a table: an absent/empty
# blocked_by yields no unlanded prerequisites; an out-of-scope blocker is ignored;
# an in-scope blocker counts only while it is not in `landed`.
_UNLANDED_HARNESS = """
import { unlandedPrerequisites } from "__MODULE_URL__";
const inScope = new Set([1, 2, 3, 4]);
const out = {
  no_blocked_by: unlandedPrerequisites(undefined, inScope, new Set()),
  empty_blocked_by: unlandedPrerequisites([], inScope, new Set([1])),
  all_landed: unlandedPrerequisites([1, 2], inScope, new Set([1, 2])),
  one_unlanded: unlandedPrerequisites([1, 2], inScope, new Set([1])),
  out_of_scope_ignored: unlandedPrerequisites([99], inScope, new Set()),
  mixed_scope: unlandedPrerequisites([1, 99], inScope, new Set()),
};
process.stdout.write(JSON.stringify(out));
"""


def test_unlanded_prerequisites_behaviour() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available on this machine")

    harness = _UNLANDED_HARNESS.replace(
        "__MODULE_URL__", ENGINE_HELPERS.resolve().as_uri()
    )
    result = subprocess.run(
        [node, "--input-type=module"],
        input=harness,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    out = json.loads(result.stdout)

    # No prerequisite, or none in this run's scope: nothing blocks the build.
    assert out["no_blocked_by"] == []
    assert out["empty_blocked_by"] == []
    assert out["out_of_scope_ignored"] == []

    # Every in-scope prerequisite already landed: nothing blocks the build.
    assert out["all_landed"] == []

    # An in-scope prerequisite still unlanded is returned (named), so the caller
    # parks the dependent; an out-of-scope blocker alongside it is ignored.
    assert out["one_unlanded"] == [2]
    assert out["mixed_scope"] == [1]


# The engine's park/land decision, simulated over a real dependency graph with the
# REAL helper: an issue builds only when it has no unlanded prerequisite, and only
# a built-and-integrated issue enters `landed`. This demonstrates the emergent
# cascade a pure predicate table cannot: a failed prerequisite skips its dependent,
# and the dependent's own dependents skip transitively.
_CASCADE_HARNESS = """
import { unlandedPrerequisites } from "__MODULE_URL__";
const issues = {
  1: { blocked_by: [] },     // A: prerequisite that FAILS to integrate
  2: { blocked_by: [1] },    // B: depends on A -> skipped
  3: { blocked_by: [2] },    // C: depends on B -> cascade skip
  4: { blocked_by: [] },     // D: no prerequisite -> unaffected
  5: { blocked_by: [] },     // E: prerequisite that DOES land
  6: { blocked_by: [5] },    // F: depends on E (all landed) -> builds
  7: { blocked_by: [99] },   // G: only an out-of-scope prerequisite -> builds
};
const order = [1, 2, 3, 4, 5, 6, 7];
const inScope = new Set(order);
const landed = new Set();
const skipped = [];
// The issues that would fail to land when built (parked/blocked/failed integrate).
const failsToLand = new Set([1]);
for (const number of order) {
  const missing = unlandedPrerequisites(issues[number].blocked_by, inScope, landed);
  if (missing.length > 0) {
    skipped.push({ number, missing });
    continue;
  }
  if (!failsToLand.has(number)) landed.add(number);
}
process.stdout.write(JSON.stringify({ skipped, landed: [...landed].sort((a, b) => a - b) }));
"""


def test_prerequisite_skip_cascades_in_a_simulated_run() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available on this machine")

    harness = _CASCADE_HARNESS.replace(
        "__MODULE_URL__", ENGINE_HELPERS.resolve().as_uri()
    )
    result = subprocess.run(
        [node, "--input-type=module"],
        input=harness,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    out = json.loads(result.stdout)
    skipped = {entry["number"]: entry["missing"] for entry in out["skipped"]}

    # B is parked because its prerequisite A did not land, naming A.
    assert skipped.get(2) == [1], (
        "an issue whose in-scope prerequisite failed must be skipped, naming it"
    )

    # C is parked transitively: B was skipped, so B never landed, so C sees B
    # unlanded and skips in turn — the cascade.
    assert skipped.get(3) == [2], (
        "the skip must cascade: a dependent of a skipped issue is itself skipped"
    )

    # No false skips: D (no prerequisite), F (prerequisite E landed), and G (only
    # an out-of-scope prerequisite) all build and land.
    assert 4 not in skipped and 6 not in skipped and 7 not in skipped, (
        "an issue with no unlanded in-scope prerequisite must not be skipped"
    )
    assert out["landed"] == [4, 5, 6, 7], (
        "exactly the issues with all prerequisites satisfied must land"
    )
