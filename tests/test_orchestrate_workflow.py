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


# --- linear, incremental integration (issue #16, #21) ------------------------

# Two invariants reach the default branch differently now. (1) Integration keeps
# feature branches LINEAR: it fast-forwards the DEFAULT branch to the feature
# branch's tip (`git merge --ff-only <feature>`, issue #21) — it must NEVER merge
# the default branch INTO the feature branch or create a merge commit there. A
# rebase of the feature branch is NOT the landing path; it is only the rare,
# effectively-unreachable fallback for the moment the default moved under the
# feature branch. (2) Each verified-green issue is integrated the MOMENT it goes
# green — inside the per-issue processing loop, before the next issue's build
# begins — so a mid-run stop leaves every prior issue durably landed, not batched
# to the end and lost. These are structural.


def test_integrate_fast_forwards_and_forbids_merging_default_into_feature() -> None:
    # AC-2 (issue #21): the merge path lands by fast-forwarding the DEFAULT branch
    # to the feature tip ONLY, and must explicitly forbid the inverse — merging the
    # default branch INTO the feature branch, which would create a merge commit and
    # break linear history. The explicit forbid clause is what was missing.
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "integrate")
    lowered = block.lower()

    # Fast-forwarding the default branch is the landing path — NOT a rebase of the
    # feature branch, which #21 demoted to a rare, effectively-unreachable fallback.
    # (The non-checkout `merge --ff-only` form itself is pinned by the AC-1 test.)
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


# --- integrate fast-forwards the default without checking out the feature (issue #21) ---

# Every code-touching agent now runs in a PERSISTED git worktree, so the feature
# branch is still checked out in the implementer's (or a fix round's) worktree when
# integrate runs — and git refuses to check out one branch in two worktrees at
# once. The merge-mode integrate instruction must therefore advance the DEFAULT
# branch to the feature branch's tip WITHOUT checking out the feature branch: from
# the default-branch checkout, `git merge --ff-only <feature>` fast-forwards the
# default and never needs the feature branch checked out. Without this, a `git
# checkout <feature>` would fail mechanically and block integration for a
# non-conflict reason — the exact worktree-lock failure isolation set out to kill,
# resurfacing at the integrate step. These are structural, read off the source.


def test_integrate_fast_forwards_default_without_checking_out_the_feature_branch() -> (
    None
):
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "integrate")
    lowered = block.lower()

    # The pinned landing form is the non-checkout fast-forward: from the default
    # branch, `git merge --ff-only <feature>` advances the default to the feature
    # tip and needs no checkout of the feature branch.
    assert "merge --ff-only" in lowered, (
        "integrate must fast-forward the default branch to the feature tip with "
        "`git merge --ff-only <feature>` — the non-checkout landing form"
    )

    # It must NEVER instruct a checkout of the feature branch (in any flag form): a
    # worktree still holds it locked, so `git checkout <feature>` would fail
    # mechanically — the exact failure this issue removes.
    assert (
        re.search(r"git checkout(?:\s+-\S+)*\s+\$\{record\.branch\}", block) is None
    ), (
        "integrate must NOT tell the integrator to check out the feature branch — "
        "a worktree still holds it and git refuses one branch in two worktrees"
    )

    # The prompt must state WHY it never checks the feature branch out — a worktree
    # still holds it — so the integrator understands the constraint, not just obeys it.
    assert "worktree" in lowered, (
        "integrate must explain that the feature branch is still held by a worktree"
    )


def test_integrate_conflict_parks_the_issue_with_a_blocker() -> None:
    # AC-3 (issue #21): a genuine conflict must NEVER be forced into a merge — the
    # integrator reports it as a blocker, and the engine parks the otherwise-green
    # issue with that blocker rather than landing it. This pins both halves: the
    # prompt clause that instructs the report, and the code path that parks on a
    # non-integration so an unreported failure cannot silently look integrated.
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "integrate")
    lowered = block.lower()

    # The prompt tells the integrator that a genuine conflict is not to be merged —
    # it is reported as a blocker.
    assert "conflict" in lowered, "integrate must address the genuine-conflict case"
    assert "do not merge" in lowered, (
        "integrate must forbid forcing a merge when a conflict makes landing unsafe"
    )
    assert "report it as a blocker" in lowered, (
        "integrate must tell the integrator to report a genuine conflict as a blocker"
    )

    # The engine parks the otherwise-green issue when the integrator does not land
    # it, folding the reported blocker into the record — never returning it green.
    assert "if (!result.integrated) return" in block, (
        "integrate must park the issue when the integrator did not land it"
    )
    assert "status: 'parked'" in block, (
        "a non-integrated issue must be recorded as parked, not left green"
    )
    assert "result.blocker" in block, (
        "the integrator's reported blocker must be folded into the parked record"
    )


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


# --- empty verifier panel (--max-lenses=0) + in-situ hazard escalation -------
# (ADR-0003 §2/§5, issue #32)

# The planner (#31) can produce an EXPLICITLY empty `issues[].lenses` array
# (`--max-lenses=0`). That is distinct from an ABSENT `lenses` field: absent
# falls back to the single broad DEFAULT_LENSES reviewer (unchanged), but
# explicitly empty means "skip the per-issue verify stage entirely" — implement
# -> integrate, no independent adversarial lens for that one issue. Neither
# red-before-green (checked deterministically, not by a lens) nor the mandatory
# integration review (not a lens) is ever suppressed by this. The ONE sanctioned
# exception is in-situ escalation: when the implementer's three-bucket report
# flags a genuine, previously-unseen hazard (a write path, a permission gate, an
# irreversible delete) on a zero-panel issue, the engine dispatches exactly ONE
# verify lens for that issue and folds its verdict in normally. The escalation
# decision itself is a pure helper, `shouldEscalateInSitu`, tested here in its
# `lib/orchestrate/engine-helpers.mjs` source of truth and drift-guarded against
# its inline workflow copy exactly like the other extracted helpers.


def test_engine_helpers_exports_should_escalate_in_situ() -> None:
    # The escalation decision is a pure predicate, so it lives in the tested
    # source of truth alongside the other engine helpers — the drift guard then
    # holds its inline workflow copy byte-identical automatically.
    helpers = ENGINE_HELPERS.read_text(encoding="utf-8")
    names = _exported_const_names(helpers)
    assert "shouldEscalateInSitu" in names, (
        "engine-helpers.mjs must export `shouldEscalateInSitu` as the tested "
        "source of truth for the ADR-0003 §5 in-situ hazard escalation decision"
    )


_ESCALATE_HARNESS = """
import { shouldEscalateInSitu } from "__MODULE_URL__";
const out = {
  hazard_empty_panel: shouldEscalateInSitu({ inSituHazard: 'found a live write path to /etc' }, []),
  no_hazard_empty_panel: shouldEscalateInSitu({ inSituHazard: '' }, []),
  absent_hazard_empty_panel: shouldEscalateInSitu({}, []),
  whitespace_hazard_empty_panel: shouldEscalateInSitu({ inSituHazard: '   ' }, []),
  null_report_empty_panel: shouldEscalateInSitu(null, []),
  hazard_nonempty_panel: shouldEscalateInSitu({ inSituHazard: 'found a write path' }, ['some lens']),
  hazard_multi_lens_panel: shouldEscalateInSitu({ inSituHazard: 'found a write path' }, ['a', 'b']),
};
process.stdout.write(JSON.stringify(out));
"""


def test_should_escalate_in_situ_behaviour() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available on this machine")

    harness = _ESCALATE_HARNESS.replace(
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

    # AC: a hazard-flagged report on a zero panel escalates one lens.
    assert out["hazard_empty_panel"] is True, (
        "a hazard-flagged report on a zero panel must escalate one lens"
    )

    # AC: a non-hazard report on a zero panel escalates none.
    assert out["no_hazard_empty_panel"] is False, (
        "a blank `inSituHazard` on a zero panel must NOT escalate"
    )
    assert out["absent_hazard_empty_panel"] is False, (
        "an absent `inSituHazard` on a zero panel must NOT escalate"
    )
    assert out["whitespace_hazard_empty_panel"] is False, (
        "a whitespace-only `inSituHazard` is not a real hazard flag"
    )
    assert out["null_report_empty_panel"] is False, (
        "a null/missing report must never escalate"
    )

    # AC: a non-zero panel is untouched by this decision, whatever the report says.
    assert out["hazard_nonempty_panel"] is False, (
        "a non-empty (already-reviewed) panel must never be escalated further "
        "by this decision"
    )
    assert out["hazard_multi_lens_panel"] is False, (
        "a multi-lens panel must never be escalated further by this decision"
    )


def test_engine_helpers_exports_with_in_situ_hazard() -> None:
    # The hazard fold is a pure mapper over a lens panel, so it lives in the
    # tested source of truth alongside the other engine helpers — the drift
    # guard then holds its inline workflow copy byte-identical automatically.
    helpers = ENGINE_HELPERS.read_text(encoding="utf-8")
    names = _exported_const_names(helpers)
    assert "withInSituHazard" in names, (
        "engine-helpers.mjs must export `withInSituHazard` as the tested "
        "source of truth for folding the implementer's flagged in-situ hazard "
        "into the escalated lens's brief (ADR-0003 §5)"
    )


_HAZARD_FOLD_HARNESS = """
import { withInSituHazard } from "__MODULE_URL__";
const out = {
  string_lens: withInSituHazard(
    ['review for correctness'],
    'discovered live write to /etc/passwd',
  ),
  object_lens: withInSituHazard(
    [{ brief: 'review for correctness', agentType: 'security-reviewer' }],
    'discovered live write to /etc/passwd',
  ),
  multi_lens: withInSituHazard(['lens one', 'lens two'], 'a flagged surface'),
};
process.stdout.write(JSON.stringify(out));
"""


def test_with_in_situ_hazard_behaviour() -> None:
    # AC: the escalated lens's own reviewer is told the SPECIFIC surface the
    # implementer flagged, not left with only the generic broad brief.
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available on this machine")

    harness = _HAZARD_FOLD_HARNESS.replace(
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

    # AC: a plain string lens comes back as a string still carrying its own
    # original brief, with the flagged hazard appended.
    [folded_string] = out["string_lens"]
    assert isinstance(folded_string, str), "a string lens must fold to a string"
    assert "review for correctness" in folded_string, (
        "the fold must keep the lens's own original brief"
    )
    assert "discovered live write to /etc/passwd" in folded_string, (
        "the fold must append the implementer's specific flagged hazard"
    )

    # AC: an { brief, agentType } lens keeps its routing and its own brief,
    # with the hazard appended to `brief` only.
    [folded_object] = out["object_lens"]
    assert folded_object["agentType"] == "security-reviewer", (
        "the fold must preserve a named lens's `agentType` routing untouched"
    )
    assert "review for correctness" in folded_object["brief"], (
        "the fold must keep the named lens's own original brief"
    )
    assert "discovered live write to /etc/passwd" in folded_object["brief"], (
        "the fold must append the implementer's specific flagged hazard to "
        "the named lens's brief"
    )

    # AC: every lens in a multi-lens panel gets the same hazard folded in, each
    # keeping its own distinct original brief.
    first, second = out["multi_lens"]
    assert "lens one" in first and "a flagged surface" in first
    assert "lens two" in second and "a flagged surface" in second


_LENSES_FOR_HARNESS = """
const DEFAULT_LENSES = ['DEFAULT_LENS'];
__LENSES_FOR_DEF__;
const out = {
  absent: lensesFor({}),
  no_issue: lensesFor(undefined),
  explicit_empty: lensesFor({ lenses: [] }),
  explicit_override: lensesFor({ lenses: ['a', 'b'] }),
};
process.stdout.write(JSON.stringify(out));
"""


def test_lenses_for_treats_explicit_empty_array_as_skip_not_default() -> None:
    # AC: an EXPLICITLY empty `lenses` array (the plan produced 0) must be
    # distinguished from an ABSENT one — only the absent case falls back to
    # DEFAULT_LENSES; the explicit empty case passes through as empty, the
    # signal buildAndVerify reads to skip the per-issue verify stage.
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available on this machine")

    source = WORKFLOW.read_text(encoding="utf-8")
    harness = _LENSES_FOR_HARNESS.replace(
        "__LENSES_FOR_DEF__", _extract_braced_const(source, "lensesFor")
    )
    result = subprocess.run(
        [node, "--input-type=module"],
        input=harness,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    out = json.loads(result.stdout)
    assert out["absent"] == ["DEFAULT_LENS"], (
        "an absent `lenses` field must fall back to DEFAULT_LENSES"
    )
    assert out["no_issue"] == ["DEFAULT_LENS"], (
        "a missing issue lookup must fall back to DEFAULT_LENSES"
    )
    assert out["explicit_empty"] == [], (
        "an EXPLICITLY empty `lenses` array (--max-lenses=0) must pass through "
        "empty, NOT fall back to DEFAULT_LENSES"
    )
    assert out["explicit_override"] == ["a", "b"], (
        "a non-empty per-issue override must still pass through unchanged"
    )


def test_build_and_verify_consults_the_panel_and_the_escalation_helper() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "buildAndVerify")
    assert "lensesFor(issuesByNumber.get(number))" in block, (
        "buildAndVerify must resolve the issue's panel via lensesFor before "
        "deciding whether to skip the per-issue verify stage"
    )
    assert "shouldEscalateInSitu(" in block, (
        "buildAndVerify must consult the pure shouldEscalateInSitu helper to "
        "decide the one sanctioned in-situ escalation"
    )


def test_empty_panel_skips_verify_unless_escalated() -> None:
    # AC: an issue whose `lenses` is empty runs implement -> integrate with NO
    # per-issue verify sub-agent dispatched, UNLESS the in-situ escalation fires.
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "buildAndVerify")

    escalate_idx = block.index("shouldEscalateInSitu(")
    verify_idx = block.index("await verify(")
    assert escalate_idx < verify_idx, (
        "the escalation decision must be made BEFORE verify() is ever dispatched"
    )

    # The guard and its early return must both sit BEFORE the verify() dispatch,
    # so an empty, non-escalated panel never reaches the agent call. The guarded
    # early return must land the issue as 'done' (implement -> integrate), never
    # parked or blocked, so a zero-panel non-hazard issue still proceeds to
    # integration and the mandatory integration review.
    region = block[:verify_idx]
    assert "panel.length === 0" in region, (
        "the skip must be guarded on the panel being EXPLICITLY empty (length "
        "0), not merely falsy"
    )
    assert "return toRecord(number, impl, 'done'" in region, (
        "an explicitly empty, non-escalated panel must return a 'done' record "
        "so the issue still proceeds to integrate — never parked or blocked"
    )


def test_escalation_dispatches_one_lens_normal_panel_unaffected() -> None:
    # AC: on escalation the engine dispatches exactly ONE verify lens — never
    # the still-empty plan panel itself. AC: absent the ADR-0003 fields (a
    # normal >= 1 panel) the lifecycle is unchanged — the panel passes straight
    # through to verify(), untouched by the hazard fold.
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "buildAndVerify")
    match = re.search(r"^\s*const lenses = (.*)$", block, flags=re.MULTILINE)
    assert match is not None, (
        "buildAndVerify must resolve the dispatched lenses into a `lenses` "
        "variable before calling verify(number, impl, lenses)"
    )
    lenses_expr = match.group(1).strip()
    assert (
        lenses_expr
        == "panel.length > 0 ? panel : withInSituHazard(DEFAULT_LENSES, impl.inSituHazard)"
    ), (
        f"expected the plan's own panel to pass through unchanged when "
        f"non-empty, and fall back to the single DEFAULT_LENSES lens folded "
        f"with the implementer's flagged in-situ hazard only on escalation, "
        f"got: {lenses_expr!r}"
    )
    assert "await verify(number, impl, lenses)" in block, (
        "buildAndVerify must call verify(number, impl, lenses) with the "
        "resolved lenses variable"
    )


def test_implement_prompt_asks_the_agent_to_flag_an_in_situ_hazard() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "implement")
    assert "inSituHazard" in block, (
        "the implement prompt must ask the agent to flag a genuine, "
        "previously-unseen in-situ hazard in `inSituHazard`, the field "
        "shouldEscalateInSitu reads"
    )


def test_fix_and_hotfix_prompts_unchanged_by_the_hazard_field() -> None:
    # AC: fix and integrationHotfix prompts stay unchanged — the change is
    # confined to the verify-stage selection.
    source = WORKFLOW.read_text(encoding="utf-8")
    for name in ("fix", "integrationHotfix"):
        block = _agent_block(source, name)
        assert "inSituHazard" not in block, (
            f"the `{name}` prompt must NOT mention inSituHazard — only "
            f"`implement` reports it"
        )
        assert "shouldEscalateInSitu" not in block, (
            f"the `{name}` agent must not itself decide escalation"
        )


def test_implement_schema_carries_the_in_situ_hazard_field() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    schema_start = source.index("const IMPLEMENT_SCHEMA")
    schema_end = source.index("const VERDICT_SCHEMA")
    schema = source[schema_start:schema_end]
    assert "inSituHazard" in schema, (
        "IMPLEMENT_SCHEMA must carry the optional `inSituHazard` field so the "
        "implementer can flag a genuine in-situ hazard for shouldEscalateInSitu"
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
    # issue was skipped, so the report points at the real cause. Crucially it must
    # land in the record's `blockers` — the ONLY field render_report surfaces for a
    # parked issue (it shows `verify` only for a done issue), so a reason placed
    # solely in `verify` would render as "no reason recorded".
    source = WORKFLOW.read_text(encoding="utf-8")
    prereq_idx = source.index(
        "unlandedPrerequisites(", source.index("for (const number of")
    )
    build_idx = source.index("buildAndVerify(number)")
    region = source[prereq_idx:build_idx]
    assert "prerequisite" in region.lower(), (
        "the park reason must mention the prerequisite"
    )
    assert "missing.map(" in region or "${missing" in region, (
        "the park reason must interpolate the unlanded prerequisite numbers"
    )
    assert "blockers:" in region, (
        "the naming reason must be placed in the record's `blockers` field, which "
        "is where render_report surfaces a parked issue's reason"
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


# --- PR mode must not build a dependent on an unmerged prerequisite (issue #23) ---

# Issue #20 parks a dependent whose in-scope prerequisite did not LAND, where
# "landed" means the prerequisite's code is on the base a dependent builds from. But
# a successful integration lands the prerequisite there only in --merge mode: in the
# conservative default PR mode `integrate` merely OPENS a pull request and merges
# nothing, so a PR-opened prerequisite is absent from the base. The engine must
# therefore mark an issue landed ONLY when the run actually merged it (merge mode),
# and in PR mode park any dependent with an in-scope prerequisite — pointing the
# human at --merge — reusing #20's transitive cascade. These pin the two halves: the
# merge-gated `landed.add` (the engine wiring, read off the source) and the
# mode-aware park reason, plus a behavioural run showing the two modes diverge.


def _enclosing_if_condition(source: str, needle: str) -> str:
    """The full condition of the nearest ``if (…)`` that guards ``needle``.

    Walks back from ``needle`` to the closest preceding ``if (`` and returns the
    balanced text between its parentheses. Reading the WHOLE condition — rather
    than substring-matching on ``needle``'s physical line — makes the guard robust
    in both directions: a widened escape hatch such as ``merge || force`` is
    visible (the condition no longer equals ``merge``), and moving the guarded
    statement onto its own line inside an ``if (merge) { … }`` block reads the same
    condition instead of falsely failing."""

    needle_idx = source.index(needle)
    open_idx = source.rindex("if (", 0, needle_idx) + len("if (") - 1
    depth = 0
    for index in range(open_idx, len(source)):
        char = source[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return source[open_idx + 1 : index]
    raise AssertionError(f"unbalanced parentheses in the `if` guarding {needle!r}")


def test_only_merge_mode_marks_a_prerequisite_landed() -> None:
    # The sole `landed.add(` must be guarded by EXACTLY `merge`: only a merge-mode
    # integration puts the issue on the base. In PR mode integrate only opens a PR,
    # so a PR-opened issue must NOT enter `landed`, or its dependents would build on
    # a base missing it — the #23 bug. Reading the whole guard condition (not a bare
    # `merge` substring on the same physical line) is what makes this robust: it
    # rejects a widened `merge || force` escape hatch and does not falsely fail when
    # the add moves onto its own line inside an `if (merge) { … }` block. (The
    # single-add / on-the-done-branch invariants stay pinned by
    # test_only_integrated_issues_enter_the_landed_set.)
    source = WORKFLOW.read_text(encoding="utf-8")
    assert source.count("landed.add(") == 1, (
        "the engine must still add to `landed` in exactly one place"
    )
    condition = _enclosing_if_condition(source, "landed.add(").strip()
    assert condition == "merge", (
        "the sole `landed.add(` must be guarded by exactly `merge` (not a widened "
        "`merge || …` escape hatch) so a PR-opened issue is never treated as landed "
        f"onto the base — in PR mode nothing merges; found guard `{condition}`"
    )


def test_pr_mode_prerequisite_park_reason_points_at_merge() -> None:
    # AC-1: in PR mode the park reason must name the prerequisite AND point the human
    # at --merge (re-running merges the base). AC-3: the merge-mode reason (#20) is
    # unchanged, so the region must still carry its "did not land" wording. The two
    # coexisting in one region means the reason is mode-aware.
    source = WORKFLOW.read_text(encoding="utf-8")
    prereq_idx = source.index(
        "unlandedPrerequisites(", source.index("for (const number of")
    )
    build_idx = source.index("buildAndVerify(number)")
    region = source[prereq_idx:build_idx]
    assert "--merge" in region, (
        "the PR-mode park reason must recommend re-running with --merge"
    )
    assert "did not land" in region, (
        "the merge-mode park reason (#20) must stay unchanged in the mode-aware reason"
    )
    assert "prerequisite" in region.lower(), (
        "the park reason must still name the prerequisite in both modes"
    )


# The engine's park/land decision run over ONE dependency graph in BOTH modes with
# the REAL helper. The only difference between the two runs is the mode: every built
# issue integrates successfully (none fails), so any divergence is purely the
# PR-vs-merge landing rule. In merge mode a dependent of a landed prerequisite builds
# (#20 unchanged); in PR mode the prerequisite is only an open PR, never on the base,
# so the dependent parks and the skip cascades to its own dependents.
_PR_VS_MERGE_HARNESS = """
import { unlandedPrerequisites } from "__MODULE_URL__";
const issues = {
  1: { blocked_by: [] },     // A: builds and integrates (a PR in PR mode)
  2: { blocked_by: [1] },    // B: depends on A
  3: { blocked_by: [2] },    // C: depends on B
  4: { blocked_by: [] },     // D: no prerequisite
  5: { blocked_by: [99] },   // E: only an out-of-scope prerequisite
};
const order = [1, 2, 3, 4, 5];
const inScope = new Set(order);

// Simulate the engine's per-issue loop: build only when no in-scope prerequisite is
// unlanded, and enter `landed` ONLY when the run merged the issue onto the base —
// which happens in merge mode alone. A PR-mode integration opens a PR and merges
// nothing, so it never lands.
function run(merge) {
  const landed = new Set();
  const skipped = [];
  const built = [];
  for (const number of order) {
    const missing = unlandedPrerequisites(issues[number].blocked_by, inScope, landed);
    if (missing.length > 0) { skipped.push({ number, missing }); continue; }
    built.push(number);
    if (merge) landed.add(number);
  }
  return { skipped, built, landed: [...landed].sort((a, b) => a - b) };
}

process.stdout.write(JSON.stringify({ pr: run(false), merge: run(true) }));
"""


def test_pr_mode_parks_dependent_of_open_pr_while_merge_mode_builds_it() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available on this machine")

    harness = _PR_VS_MERGE_HARNESS.replace(
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
    pr, merge = out["pr"], out["merge"]

    # Merge mode (#20 unchanged): every dependent of a landed prerequisite builds, so
    # the whole chain lands.
    assert merge["built"] == [1, 2, 3, 4, 5]
    assert merge["skipped"] == []
    assert merge["landed"] == [1, 2, 3, 4, 5]

    # PR mode (#23): the prerequisite is only an open PR, never on the base, so its
    # dependent parks — naming it — and the skip cascades to the dependent's own
    # dependents. Nothing enters `landed` because nothing merged.
    pr_skipped = {entry["number"]: entry["missing"] for entry in pr["skipped"]}
    assert pr_skipped.get(2) == [1], (
        "in PR mode a dependent of an only-a-PR prerequisite must be parked, naming it"
    )
    assert pr_skipped.get(3) == [2], (
        "the PR-mode skip must cascade: a dependent of a skipped issue is skipped too"
    )
    assert pr["landed"] == [], "in PR mode nothing merges, so nothing lands"

    # No false parks in either mode: an issue with no in-scope prerequisite (D) or
    # only an out-of-scope one (E) builds regardless of mode.
    assert 4 in pr["built"] and 5 in pr["built"], (
        "an issue with no unlanded in-scope prerequisite must build even in PR mode"
    )
    assert 2 not in pr["built"] and 3 not in pr["built"], (
        "a PR-mode dependent of an unmerged prerequisite must not be built"
    )


# --- per-role model/effort derived from the --level dial (issue #25) ----------

# The `--level` ambition dial makes every sub-agent's model and reasoning effort a
# function of one dial instead of everything inheriting the session tier. The
# ORCHESTRATOR resolves `--level` → a per-role `(model, effort)` against the live
# model list (the engine has no primitive to enumerate models) and passes it in as
# `args.roles = { judgment, implementer, mechanical }`. The ENGINE only APPLIES
# what it is handed: it reads the resolution off the normalized config and spreads
# a `roleTuning(...)` opts fragment into each sub-agent — judgment onto verify /
# reverifyFindings / integrationReview, implementer onto implement / fix /
# integrationHotfix, mechanical onto integrate and the teardown agent. An absent
# role or field yields NO override, so the agent inherits the session model and a
# plan produced before the dial existed still runs unchanged. The resolution
# helper is pure and drift-guarded against its inline copy, like the others.


def test_engine_helpers_exports_role_tuning() -> None:
    # The apply-a-resolution logic is a pure fragment builder, so it lives in the
    # tested source of truth alongside the other engine helpers — the drift guard
    # then holds its inline workflow copy byte-identical automatically.
    helpers = ENGINE_HELPERS.read_text(encoding="utf-8")
    names = _exported_const_names(helpers)
    assert "roleTuning" in names, (
        "engine-helpers.mjs must export `roleTuning` as the tested source of truth "
        "for turning a resolved per-role (model, effort) into an agent opts fragment"
    )


def test_engine_reads_roles_from_config() -> None:
    # The engine must read the per-role resolution off the NORMALIZED config (never
    # the raw args), and default it to an empty object so an absent `args.roles`
    # means every role dispatches with no override.
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "const roles = config.roles || {}" in source, (
        "the engine must read `config.roles` (normalized) and default it to {} so "
        "an absent resolution adds no model/effort override to any agent"
    )


def test_judgment_agents_carry_judgment_role_tuning() -> None:
    # Judgment = the adversarial reviewers (per-issue verify, the targeted
    # re-verify, and the mandatory integration review). Each must spread the
    # judgment role's resolved tuning into its agent opts.
    source = WORKFLOW.read_text(encoding="utf-8")
    for name in ("verify", "reverifyFindings", "integrationReview"):
        block = _agent_block(source, name)
        assert "...roleTuning(roles.judgment)" in block, (
            f"the `{name}` agent (a judgment role) must spread "
            f"roleTuning(roles.judgment) into its opts so its model/effort derives "
            f"from the level"
        )


def test_implementer_agents_carry_implementer_role_tuning() -> None:
    # Implementer = the code-writing agents (implement, its fix round, and the
    # integration hotfix). Each must spread the implementer role's resolved tuning.
    source = WORKFLOW.read_text(encoding="utf-8")
    for name in ("implement", "fix", "integrationHotfix"):
        block = _agent_block(source, name)
        assert "...roleTuning(roles.implementer)" in block, (
            f"the `{name}` agent (an implementer role) must spread "
            f"roleTuning(roles.implementer) into its opts"
        )


def test_integrate_agent_carries_mechanical_role_tuning() -> None:
    # Integrate is a mechanical leaf — it lands a green branch, no reasoning — so it
    # must spread the mechanical role's resolved tuning (the cheapest tier).
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "integrate")
    assert "...roleTuning(roles.mechanical)" in block, (
        "the `integrate` agent (a mechanical leaf) must spread "
        "roleTuning(roles.mechanical) into its opts"
    )


def test_teardown_agent_carries_mechanical_role_tuning() -> None:
    # The end-of-run teardown agent is the other mechanical leaf. It is dispatched
    # inline in the teardown `finally`, not as a named const, so assert on the tail.
    source = WORKFLOW.read_text(encoding="utf-8")
    tail = source[source.index("finally {") :]
    assert "...roleTuning(roles.mechanical)" in tail, (
        "the teardown agent (a mechanical leaf) must spread "
        "roleTuning(roles.mechanical) into its opts"
    )


def test_role_tuning_is_the_only_model_effort_source() -> None:
    # The engine stores no model-name table and applies model/effort ONLY through
    # roleTuning — never a hardcoded `model:`/`effort:` literal in an agent's opts.
    # A stray literal would be an un-derived override the level could not move.
    source = WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"\bmodel:\s*'", source) is None, (
        "no agent opts may hardcode a `model: '...'` literal — model/effort must "
        "flow only through the derived roleTuning fragment"
    )
    assert re.search(r"\beffort:\s*'", source) is None, (
        "no agent opts may hardcode an `effort: '...'` literal — model/effort must "
        "flow only through the derived roleTuning fragment"
    )


# The pure fragment builder, exercised through node over a table: an absent role
# (or field) yields an EMPTY fragment so the spread is a no-op and the agent
# inherits the session model; a present field is copied verbatim. This is the
# behaviour AC-2 rests on — a plan with no `roles` still runs unchanged.
_ROLE_TUNING_HARNESS = """
import { roleTuning } from "__MODULE_URL__";
const out = {
  absent: roleTuning(undefined),
  nul: roleTuning(null),
  non_object: roleTuning('opus'),
  empty: roleTuning({}),
  model_only: roleTuning({ model: 'sonnet' }),
  effort_only: roleTuning({ effort: 'high' }),
  both: roleTuning({ model: 'opus', effort: 'xhigh' }),
  extra_ignored: roleTuning({ model: 'haiku', effort: 'low', mode: 'executes' }),
};
process.stdout.write(JSON.stringify(out));
"""


def test_role_tuning_behaviour() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available on this machine")

    harness = _ROLE_TUNING_HARNESS.replace(
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

    # An absent, null, or non-object role degrades to an EMPTY fragment: spread into
    # an agent's opts it adds no model/effort key, so the agent inherits the session
    # model — the pre-dial plan runs unchanged.
    assert out["absent"] == {}
    assert out["nul"] == {}
    assert out["non_object"] == {}
    assert out["empty"] == {}

    # Only the fields the orchestrator actually resolved are copied — a role that
    # set just the model (or just the effort) overrides only that.
    assert out["model_only"] == {"model": "sonnet"}
    assert out["effort_only"] == {"effort": "high"}
    assert out["both"] == {"model": "opus", "effort": "xhigh"}

    # A resolution carrying extra keys (e.g. an advisory `mode`) contributes only
    # the two opts the harness understands — model and effort, nothing else.
    assert out["extra_ignored"] == {"model": "haiku", "effort": "low"}


# --- implementation-planning overlay + sliding implementer (issue #29) --------

# ADR-0002 settles the sliding implementer and the per-issue implementation plan.
# The PLANNING pass that authors the plan lives in the orchestrator, not here — on
# the ENGINE side (issue #29) the job is CONSUMPTION. The engine reads a run-level
# `implementerMode ∈ { execute, balanced, autonomous }` marker and a per-issue
# `issues[].plan` string, and layers an additive "how" overlay onto the `implement`
# prompt ONLY: the fixed mode framing (three inline templates, modeled the way
# DEFAULT_LENSES / AGENT_CONSTRAINTS are — inline fixed text, so no top-level export
# is added) plus the plan text. Both degrade cleanly and INDEPENDENTLY: an absent
# marker adds NO framing and an absent/blank plan adds NO plan text, so a legacy or
# hand-launched run (neither field) yields exactly today's prompt. `fix` and
# `integrationHotfix` keep their finding-driven prompts unchanged. The composition
# is the inline-only `planOverlay` helper (the `toRecord` pattern: workflow-local,
# not an engine-helpers extraction, exercised through node), so the drift guard and
# the single-top-level-export invariant are untouched. These are structural +
# behavioural, read off the workflow source.


def _extract_braced_const(source: str, name: str) -> str:
    """Extract a ``const <name> = …`` whose value is a brace-delimited literal — an
    object ``{ … }`` or a block-bodied arrow ``(…) => { … }``.

    Walks balanced ``{}`` from the first ``{`` after the ``const``, skipping string
    literals (single, double, backtick, with backslash escapes) AND ``//`` line /
    ``/* */`` block comments, so a brace — or a stray apostrophe or quote — inside a
    quoted string, a ``${…}`` template interpolation, or a comment can never end the
    scan early. Handles what ``_extract_def`` (no string/comment skip) and
    ``_extract_arrow_object_def`` (parenthesised object body) do not: a
    template-literal-and-comment-bearing arrow body and an object-literal const."""

    match = re.search(rf"^const {re.escape(name)} = ", source, flags=re.MULTILINE)
    assert match is not None, f"`const {name} =` not found"
    start = match.start()
    index = source.index("{", start)

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
            index += 1
            continue
        pair = source[index : index + 2]
        if pair == "//":
            index = source.index("\n", index) + 1
            continue
        if pair == "/*":
            index = source.index("*/", index) + 2
            continue
        if char in "'\"`":
            in_string = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
        index += 1
    raise AssertionError(f"unbalanced braces while extracting `{name}`")


def test_engine_reads_implementer_mode_from_config() -> None:
    # AC: the run-level mode marker is CONSUMED off the NORMALIZED config (never the
    # raw args), so an absent field is simply undefined and selects no framing —
    # today's behaviour. This is the engine consuming, not authoring, the marker.
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "const implementerMode = config.implementerMode" in source, (
        "the engine must read the run-level `config.implementerMode` marker off the "
        "normalized config so it can select the mode framing"
    )


def test_implementer_mode_framings_are_one_inline_const() -> None:
    # AC: the three mode framings live in the engine as ONE fixed inline const,
    # modeled the way DEFAULT_LENSES / AGENT_CONSTRAINTS are — not an extracted or
    # imported helper, which would add a top-level export/import the harness rejects.
    source = WORKFLOW.read_text(encoding="utf-8")
    decls = re.findall(
        r"^const IMPLEMENTER_MODE_FRAMINGS = ", source, flags=re.MULTILINE
    )
    assert len(decls) == 1, (
        "the three mode framings must be exactly one inline "
        "`const IMPLEMENTER_MODE_FRAMINGS =` (fixed template text), like DEFAULT_LENSES"
    )


# The fixed framing table, exercised through node: the three ADR-0002 §4 modes,
# each carrying its wording verbatim, and an absent/unrecognized marker selecting
# nothing (the degradation the no-mode path relies on).
_FRAMINGS_HARNESS = """
__FRAMINGS_DEF__;
process.stdout.write(JSON.stringify({
  keys: Object.keys(IMPLEMENTER_MODE_FRAMINGS).sort(),
  execute: IMPLEMENTER_MODE_FRAMINGS.execute,
  balanced: IMPLEMENTER_MODE_FRAMINGS.balanced,
  autonomous: IMPLEMENTER_MODE_FRAMINGS.autonomous,
  absent: IMPLEMENTER_MODE_FRAMINGS[undefined] ?? null,
  unknown: IMPLEMENTER_MODE_FRAMINGS['bogus'] ?? null,
}));
"""


def test_implementer_mode_framings_carry_the_adr_text() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available on this machine")

    source = WORKFLOW.read_text(encoding="utf-8")
    harness = _FRAMINGS_HARNESS.replace(
        "__FRAMINGS_DEF__",
        _extract_braced_const(source, "IMPLEMENTER_MODE_FRAMINGS"),
    )
    result = subprocess.run(
        [node, "--input-type=module"],
        input=harness,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)

    # Exactly the three ADR-0002 §4 modes, keyed by the marker.
    assert out["keys"] == ["autonomous", "balanced", "execute"]

    # Each framing carries ADR-0002 §4's wording verbatim.
    assert out["execute"] == (
        "This plan is the settled *how*. Follow it test-first. Deviate only if it "
        "is demonstrably wrong, and record why. Do not re-derive the approach."
    )
    assert out["balanced"] == (
        "Follow the spec's shape, fill in the routine *how* yourself, and respect "
        "the decisions it calls out."
    )
    assert out["autonomous"] == (
        "Here are the goals and constraints (or, at `XL`, the brief). Reason out "
        "the *how* yourself, test-first; the tests are your guide. You own the "
        "approach."
    )

    # An absent or unrecognized marker selects NO framing — the degradation the
    # no-mode path relies on.
    assert out["absent"] is None
    assert out["unknown"] is None


def test_plan_overlay_selects_framing_and_interpolates_the_plan() -> None:
    # AC: the overlay is where the framing is mode-selected and the per-issue plan
    # is interpolated. It reads the framing from the fixed table by the marker and
    # interpolates the plan string.
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "planOverlay")
    assert "IMPLEMENTER_MODE_FRAMINGS[mode]" in block, (
        "planOverlay must select the framing from the fixed table by the mode marker"
    )
    assert "${plan}" in block, (
        "planOverlay must interpolate the per-issue plan string into the overlay"
    )


# The overlay composition, exercised through node over a table. Distinct plan
# tokens make interpolation visible; the two halves must degrade independently.
_PLAN_OVERLAY_HARNESS = """
__FRAMINGS_DEF__;
__OVERLAY_DEF__;
const out = {
  none: planOverlay(undefined, undefined),
  mode_only_autonomous: planOverlay('autonomous', undefined),
  plan_only: planOverlay(undefined, 'PLANBODY_ALPHA'),
  execute_with_plan: planOverlay('execute', 'PLANBODY_BETA'),
  balanced_with_plan: planOverlay('balanced', 'PLANBODY_GAMMA'),
  autonomous_with_plan: planOverlay('autonomous', 'PLANBODY_DELTA'),
  unknown_mode: planOverlay('bogus', 'PLANBODY_EPSILON'),
  blank_plan: planOverlay('execute', '   '),
};
process.stdout.write(JSON.stringify(out));
"""


def test_plan_overlay_composition_and_clean_degradation() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available on this machine")

    source = WORKFLOW.read_text(encoding="utf-8")
    harness = _PLAN_OVERLAY_HARNESS.replace(
        "__FRAMINGS_DEF__",
        _extract_braced_const(source, "IMPLEMENTER_MODE_FRAMINGS"),
    ).replace("__OVERLAY_DEF__", _extract_braced_const(source, "planOverlay"))
    result = subprocess.run(
        [node, "--input-type=module"],
        input=harness,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)

    execute_text = "This plan is the settled *how*."
    balanced_text = "Follow the spec's shape"
    autonomous_text = "Reason out the *how* yourself"

    # Clean degradation: neither field present → empty overlay → the implement
    # prompt degrades byte-for-byte to today's behaviour.
    assert out["none"] == "", (
        "with no mode and no plan the overlay must be empty, so the implement "
        "prompt degrades byte-for-byte to today's behaviour"
    )

    # A mode with no plan (the XL-like case: autonomous carries no plan) adds the
    # framing but NO plan block.
    assert autonomous_text in out["mode_only_autonomous"]
    assert "PLANBODY" not in out["mode_only_autonomous"]
    assert "Implementation plan" not in out["mode_only_autonomous"], (
        "with no plan there must be no plan block header"
    )

    # A plan with no mode adds the plan but NO framing — each half degrades
    # independently, never inferring the mode from the plan's presence.
    assert "PLANBODY_ALPHA" in out["plan_only"]
    assert execute_text not in out["plan_only"]
    assert balanced_text not in out["plan_only"]
    assert autonomous_text not in out["plan_only"]

    # Each mode selects its OWN framing, and the plan text is interpolated.
    assert execute_text in out["execute_with_plan"]
    assert "PLANBODY_BETA" in out["execute_with_plan"]
    assert balanced_text in out["balanced_with_plan"]
    assert "PLANBODY_GAMMA" in out["balanced_with_plan"]
    assert autonomous_text in out["autonomous_with_plan"]
    assert "PLANBODY_DELTA" in out["autonomous_with_plan"]

    # An unrecognized mode selects no framing (degrades); the plan still shows.
    assert execute_text not in out["unknown_mode"]
    assert balanced_text not in out["unknown_mode"]
    assert autonomous_text not in out["unknown_mode"]
    assert "PLANBODY_EPSILON" in out["unknown_mode"]

    # A blank/whitespace plan adds no plan block, but the framing still applies.
    assert execute_text in out["blank_plan"]
    assert "Implementation plan" not in out["blank_plan"]


def test_implement_consumes_the_plan_and_mode_via_overlay() -> None:
    # AC: the `implement` prompt builds its overlay from the run-level marker and
    # the per-issue `issues[].plan`, and interpolates the result into the prompt.
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "implement")
    assert "planOverlay(implementerMode," in block, (
        "the implement prompt must build its overlay from the run-level mode marker"
    )
    assert "?.plan" in block, (
        "the implement prompt must pass the per-issue issues[].plan to the overlay"
    )
    assert "${planOverlay(" in block, (
        "the composed overlay must be interpolated into the implement prompt"
    )


def test_plan_overlay_is_consumed_only_by_implement() -> None:
    # AC: the plan + framing apply to `implement` ONLY. The overlay is invoked
    # exactly once in the whole engine, and that sole call sits in the implement
    # block (between it and the following `fix` const).
    source = WORKFLOW.read_text(encoding="utf-8")
    assert source.count("planOverlay(implementerMode") == 1, (
        "the plan overlay must be consumed in exactly one place — the implement agent"
    )
    call_idx = source.index("planOverlay(implementerMode")
    impl_idx = source.index("const implement = ")
    fix_idx = source.index("const fix = ")
    assert impl_idx < call_idx < fix_idx, (
        "the sole plan-overlay call must live inside the implement agent block"
    )


def test_fix_prompt_is_unchanged_by_the_plan_overlay() -> None:
    # ADR-0002 §4: `fix` is targeted at specific findings regardless of mode, so it
    # must NOT consume the plan or the mode framing — its prompt stays unchanged.
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "fix")
    assert "planOverlay" not in block, "the `fix` prompt must not consume the overlay"
    assert "implementerMode" not in block, (
        "the `fix` prompt must not consume the run-level mode marker"
    )
    assert "IMPLEMENTER_MODE_FRAMINGS" not in block, (
        "the `fix` prompt must not consume the mode framing"
    )


def test_integration_hotfix_prompt_is_unchanged_by_the_plan_overlay() -> None:
    # ADR-0002 §4: `integrationHotfix` is cross-issue, so no single issue's plan
    # applies — it must NOT consume the plan or the mode framing.
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "integrationHotfix")
    assert "planOverlay" not in block, (
        "the `integrationHotfix` prompt must not consume the overlay"
    )
    assert "implementerMode" not in block, (
        "the `integrationHotfix` prompt must not consume the run-level mode marker"
    )
    assert "IMPLEMENTER_MODE_FRAMINGS" not in block, (
        "the `integrationHotfix` prompt must not consume the mode framing"
    )


# The framing lookup is a bracket access on a plain object literal, so a `mode`
# string that collides with an Object.prototype member ('constructor', 'toString',
# '__proto__', 'hasOwnProperty', 'valueOf', …) resolves to a truthy INHERITED
# non-string — a function, or the prototype object — not `undefined`. A bare
# `framing ?` guard would treat that as a real framing and coerce it into a garbage
# line ("function Object() { [native code] }" / "[object Object]") injected into the
# implement prompt. Unreachable through the real contract (the orchestrator emits the
# closed execute|balanced|autonomous enum or omits the field), so it is minor — but
# the lookup must require an actual framing STRING before anything reaches the prompt.
_PLAN_OVERLAY_PROTO_HARNESS = """
__FRAMINGS_DEF__;
__OVERLAY_DEF__;
const out = {
  constructor_no_plan: planOverlay('constructor', undefined),
  tostring_no_plan: planOverlay('toString', undefined),
  proto_no_plan: planOverlay('__proto__', undefined),
  hasownproperty_no_plan: planOverlay('hasOwnProperty', undefined),
  valueof_no_plan: planOverlay('valueOf', undefined),
  tostring_with_plan: planOverlay('toString', 'PLANBODY_ZETA'),
};
process.stdout.write(JSON.stringify(out));
"""


def test_plan_overlay_hardens_against_prototype_key_collision() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available on this machine")

    source = WORKFLOW.read_text(encoding="utf-8")
    harness = _PLAN_OVERLAY_PROTO_HARNESS.replace(
        "__FRAMINGS_DEF__",
        _extract_braced_const(source, "IMPLEMENTER_MODE_FRAMINGS"),
    ).replace("__OVERLAY_DEF__", _extract_braced_const(source, "planOverlay"))
    result = subprocess.run(
        [node, "--input-type=module"],
        input=harness,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)

    # A prototype-colliding mode with no plan must select NO framing, so the whole
    # overlay is empty — never a coerced inherited-member framing line.
    for key in (
        "constructor_no_plan",
        "tostring_no_plan",
        "proto_no_plan",
        "hasownproperty_no_plan",
        "valueof_no_plan",
    ):
        assert out[key] == "", (
            f"a prototype-colliding mode ({key}) with no plan must yield an empty "
            f"overlay, never a coerced inherited-member framing line"
        )

    # With a plan the plan block still shows, but the colliding mode contributes no
    # framing and no coerced-member text ("[native code]" / "[object Object]" /
    # "function") leaks into the prompt.
    assert "PLANBODY_ZETA" in out["tostring_with_plan"]
    assert "native code" not in out["tostring_with_plan"]
    assert "[object Object]" not in out["tostring_with_plan"]
    assert "function" not in out["tostring_with_plan"]


# --- #46: merge-mode branches fork from the current default tip + reconcile ---

# A merge-mode run integrates issues serially, fast-forwarding the default branch
# to each verified feature tip. The implementer landed in a Workflow worktree
# whose HEAD is the harness's run-start scaffolding ref, pinned at run start; the
# old `implement` prompt said only "work on a fresh branch off the current
# integration base", so every issue after the first forked from that STALE base
# and, once the default advanced under it, could no longer `--ff-only` — verified
# work was parked en masse (issue #46). The fix has three parts, all structural:
#   1. `implement` creates its branch FRESH off the up-to-date default tip with
#      `git checkout -B`, mirroring `integrationHotfix`, so the ff-only invariant
#      holds for real in the serial design.
#   3. the `integrate` prompt no longer asserts the false "nothing landed between
#      the build and now" invariant — it ties the fast-forward to the branch
#      having been cut off the then-current tip.
#   2. a genuine rebase content conflict on a VERIFIED branch is not parked
#      outright: a bounded reconcile stage (rebase+resolve → targeted re-verify of
#      ONLY the resolution → land) repairs it, parking only when the re-verify
#      blocks or the round cap is hit. Merge mode only.


def test_implement_creates_branch_fresh_off_current_default_tip() -> None:
    # #46 fix 1: the implementer must create its feature branch FRESH off the
    # up-to-date default tip (mirroring integrationHotfix) so the harness's stale
    # run-start scaffolding base cannot make it build on an old base.
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "implement")
    assert "git checkout -B" in block, (
        "the implement prompt must create the feature branch fresh off the "
        "up-to-date default tip with `git checkout -B`, like integrationHotfix"
    )
    lowered = block.lower()
    assert "stale" in lowered, (
        "the implement prompt must explain the stale run-start base it guards against"
    )
    assert "default branch" in lowered, (
        "the fresh branch must be created off the up-to-date default branch"
    )
    # Worktree isolation and the in-situ hazard flag survive the reword.
    assert "isolation: 'worktree'" in block
    assert "inSituHazard" in block


def test_integrate_prompt_no_longer_asserts_the_false_nothing_landed_invariant() -> (
    None
):
    # #46 fix 3: the false "nothing landed between the build and now" claim is gone;
    # the ff-only guarantee is tied to the branch being cut off the then-current tip.
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "integrate")
    lowered = block.lower()
    assert "nothing landed between" not in lowered, (
        "the integrate prompt must no longer assert the false 'nothing landed "
        "between the build and now' invariant"
    )
    assert (
        "then-current default" in lowered
        or "current default tip" in lowered
        or "current tip" in lowered
    ), (
        "the integrate prompt must tie the fast-forward to the branch having been "
        "created off the then-current default tip"
    )
    # The core landing invariants are untouched by the reword.
    assert "merge --ff-only" in lowered
    assert "never merge the default branch into" in lowered
    assert "linear" in lowered


def test_engine_helpers_exports_is_reconcilable_conflict() -> None:
    helpers = ENGINE_HELPERS.read_text(encoding="utf-8")
    names = _exported_const_names(helpers)
    assert "isReconcilableConflict" in names, (
        "engine-helpers.mjs must export `isReconcilableConflict` as the tested "
        "source of truth for the #46 reconcile decision"
    )


_RECONCILE_HARNESS = """
import { isReconcilableConflict } from "__MODULE_URL__";
const out = {
  parked_conflict: isReconcilableConflict({ status: 'parked', conflict: true }),
  parked_no_conflict: isReconcilableConflict({ status: 'parked', conflict: false }),
  parked_absent_conflict: isReconcilableConflict({ status: 'parked' }),
  done_conflict: isReconcilableConflict({ status: 'done', conflict: true }),
  blocked_conflict: isReconcilableConflict({ status: 'blocked', conflict: true }),
  null_record: isReconcilableConflict(null),
  undefined_record: isReconcilableConflict(undefined),
};
process.stdout.write(JSON.stringify(out));
"""


def test_is_reconcilable_conflict_behaviour() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available on this machine")

    harness = _RECONCILE_HARNESS.replace(
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

    # Only a PARKED record carrying the integrator's genuine-conflict flag reconciles.
    assert out["parked_conflict"] is True
    assert out["parked_no_conflict"] is False, (
        "a parked record without the conflict flag is some other failure — never reconcile"
    )
    assert out["parked_absent_conflict"] is False, (
        "an absent conflict flag must not reconcile"
    )
    assert out["done_conflict"] is False, "a landed issue is never reconciled"
    assert out["blocked_conflict"] is False, (
        "a design-blocked issue is never reconciled"
    )
    assert out["null_record"] is False
    assert out["undefined_record"] is False


def test_integrate_schema_carries_conflict_field() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    schema = _extract_braced_const(source, "INTEGRATE_SCHEMA")
    assert "conflict" in schema, (
        "INTEGRATE_SCHEMA must carry a `conflict` boolean so the integrator can "
        "signal a genuine rebase content conflict the reconcile stage repairs"
    )


def test_integrate_threads_the_conflict_flag_onto_the_parked_record() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "integrate")
    assert "result.conflict" in block, (
        "integrate must read the integrator's `conflict` flag and thread it onto "
        "the parked record so the reconcile stage can decide"
    )
    # The integrate prompt asks the integrator to set the flag on a genuine conflict.
    assert "conflict: true" in block.lower() or "`conflict`" in block, (
        "the integrate prompt must ask the integrator to flag a genuine conflict"
    )


def test_reconcile_agent_is_worktree_isolated_and_frees_the_branch_lock() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "reconcile")
    assert "isolation: 'worktree'" in block, (
        "the reconcile agent touches code and MUST carry isolation: 'worktree'"
    )
    assert "${" + CONSTRAINTS_NAME + "}" in block, (
        "the reconcile agent must interpolate the shared AGENT_CONSTRAINTS"
    )
    # Like fix, it frees the worktree still holding the branch before taking it over.
    assert "git worktree remove --force" in block, (
        "reconcile must free the worktree that still holds the target branch"
    )
    lowered = block.lower()
    assert "rebase" in lowered, "reconcile must rebase the branch onto the default"
    assert "both" in lowered, (
        "reconcile must keep BOTH sides' concerns when resolving the conflict"
    )


def test_reverify_reconcile_is_a_single_read_only_verdict_agent() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "reverifyReconcile")
    assert "parallel(" not in block, (
        "reverifyReconcile must be a single targeted agent, never a parallel panel"
    )
    assert "VERDICT_SCHEMA" in block, (
        "reverifyReconcile must return the same VERDICT_SCHEMA a verifier does"
    )
    assert "isolation" not in block, (
        "reverifyReconcile is a read-only reviewer and needs no worktree isolation"
    )
    assert "${" + CONSTRAINTS_NAME + "}" in block, (
        "reverifyReconcile must interpolate the shared AGENT_CONSTRAINTS"
    )
    assert "only" in block.lower(), (
        "reverifyReconcile must review ONLY the conflict resolution, not the whole change"
    )


def test_wave_loop_reconciles_a_conflicted_verified_branch_before_parking() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    per_issue_idx = source.index("for (const number of")
    finally_idx = source.index("finally {")
    region = source[per_issue_idx:finally_idx]
    assert re.search(r"merge && isReconcilableConflict\(", region), (
        "the wave loop must attempt a bounded reconcile — merge mode only — when "
        "integrate parked a verified branch on a genuine conflict"
    )
    assert "reconcileAndIntegrate(" in region, (
        "the wave loop must call reconcileAndIntegrate to repair a conflicted branch"
    )


def test_reconcile_loop_is_bounded_and_tracks_its_branch_for_teardown() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "reconcileAndIntegrate")
    assert "maxFixRounds" in block, (
        "the reconcile loop must be bounded by the per-issue maxFixRounds cap"
    )
    assert "reconcile(" in block, "the loop must rebase+resolve via reconcile"
    assert "reverifyReconcile(" in block, (
        "the loop must re-verify ONLY the resolution via reverifyReconcile"
    )
    assert "integrate(" in block, "the loop must land via the same integrate step"
    assert "blockingFindings(" in block, (
        "the re-verify verdict must go through blockingFindings so a dead / "
        "not-clear review never lands the reconciled branch"
    )
    assert "builtBranches.add" in block, (
        "the reconciled branch must be tracked in builtBranches so teardown removes it"
    )


# --- #36: implementer ripple report + verifier consistency lens --------------

# When an implementer changes a shared symbol's contract or effective behaviour
# but updates only some callers, the diff is locally consistent; a per-issue
# verifier is bound to the diff and structurally cannot see the unchanged
# callers, so the class was previously caught only by the mandatory integration
# review — a full extra review + remediation cycle. Two fixes, both prompt-text,
# mirroring how AGENT_CONSTRAINTS is a single shared constant rather than
# copy-pasted: (1) a `RIPPLE_REPORT_INSTRUCTION` interpolated into `implement`
# and `fix` tells the implementer to enumerate affected call sites and report
# which were updated and which were not under `assumptions`; (2) a
# `CONSISTENCY_LENS_INSTRUCTION` folded into every lens `verify` dispatches
# tells the reviewer to also check a changed shared symbol's UNCHANGED callers,
# scoped to fire only when the diff touches such a symbol — confined to the
# initial panel, never the narrowly-scoped targeted re-verifies or the
# mandatory integration review, which stays the unchanged backstop.

RIPPLE_NAME = "RIPPLE_REPORT_INSTRUCTION"
CONSISTENCY_NAME = "CONSISTENCY_LENS_INSTRUCTION"


def test_ripple_report_instruction_declared_exactly_once() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    decls = re.findall(
        rf"^const {re.escape(RIPPLE_NAME)} = ", source, flags=re.MULTILINE
    )
    assert len(decls) == 1, (
        f"expected exactly one top-level `const {RIPPLE_NAME} =`, found "
        f"{len(decls)} — the ripple-report text must be defined once and reused"
    )


def test_ripple_report_instruction_covers_the_required_content() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, RIPPLE_NAME)
    lowered = block.lower()
    assert "shared symbol" in lowered, (
        "the ripple report must name a shared symbol's contract/behaviour change"
    )
    assert "call site" in lowered or "caller" in lowered, (
        "the ripple report must ask for the affected call sites/callers"
    )
    assert "assumptions" in lowered, (
        "the ripple report must say to report under `assumptions`"
    )
    assert "updated" in lowered, (
        "the ripple report must ask which call sites were updated (and which were not)"
    )


def test_implement_and_fix_prompts_reference_the_ripple_report_instruction() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    reference = "${" + RIPPLE_NAME + "}"
    for name in ("implement", "fix"):
        block = _agent_block(source, name)
        assert reference in block, (
            f"the `{name}` prompt must interpolate {reference} so the ripple-"
            f"report instruction reaches the implementer"
        )


def test_ripple_report_instruction_excluded_from_non_implementer_prompts() -> None:
    # AC: only `implement` and `fix` gain the ripple-report instruction — the
    # verifier's job is the consistency LENS below, not the implementer's report,
    # and the hotfix/reconcile agents are cross-issue/rebase-scoped, out of scope.
    source = WORKFLOW.read_text(encoding="utf-8")
    reference = "${" + RIPPLE_NAME + "}"
    for name in (
        "verify",
        "reverifyFindings",
        "integrate",
        "integrationReview",
        "integrationHotfix",
        "reconcile",
        "reverifyReconcile",
    ):
        block = _agent_block(source, name)
        assert reference not in block, (
            f"the `{name}` prompt must NOT carry the ripple-report instruction"
        )


def test_consistency_lens_instruction_declared_exactly_once() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    decls = re.findall(
        rf"^const {re.escape(CONSISTENCY_NAME)} = ", source, flags=re.MULTILINE
    )
    assert len(decls) == 1, (
        f"expected exactly one top-level `const {CONSISTENCY_NAME} =`, found "
        f"{len(decls)} — the consistency-lens text must be defined once and reused"
    )


def test_consistency_lens_instruction_covers_the_required_content() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, CONSISTENCY_NAME)
    lowered = block.lower()
    assert "shared" in lowered, (
        "the consistency lens must scope to a shared (multi-caller) symbol"
    )
    assert "unchanged" in lowered, (
        "the consistency lens must check the symbol's UNCHANGED callers"
    )
    assert "consisten" in lowered, (
        "the consistency lens must name the consistency check itself"
    )
    assert "skip" in lowered or "only when" in lowered or "no such" in lowered, (
        "the consistency lens must be conditional: it fires only when a shared "
        "symbol is touched, so an ordinary diff pays nothing extra"
    )


def test_verify_prompt_references_the_consistency_lens_instruction() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    block = _agent_block(source, "verify")
    reference = "${" + CONSISTENCY_NAME + "}"
    assert reference in block, (
        f"the `verify` prompt must interpolate {reference} so every dispatched "
        f"lens carries the conditional consistency check"
    )


def test_consistency_lens_instruction_excluded_from_narrow_or_mandatory_reviews() -> (
    None
):
    # AC: the lens is confined to the INITIAL per-issue panel. The targeted
    # fix-round and reconcile re-verifies are already narrowly scoped to their own
    # findings/resolution, and the mandatory integration review stays the
    # unchanged backstop (out of scope for #36) — none of them gain this text.
    source = WORKFLOW.read_text(encoding="utf-8")
    reference = "${" + CONSISTENCY_NAME + "}"
    for name in ("reverifyFindings", "reverifyReconcile", "integrationReview"):
        block = _agent_block(source, name)
        assert reference not in block, (
            f"the `{name}` prompt must NOT carry the consistency-lens instruction"
        )
