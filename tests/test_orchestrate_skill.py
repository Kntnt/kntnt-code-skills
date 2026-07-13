"""Structural tests for the orchestrate SKILL.md guidance (issues #19, #24).

These read ``skills/orchestrate/SKILL.md`` as text and assert three things the
skill's prose must carry:

1. The single confirm gate sizes the run to its cost — an agent/token estimate
   *formula* (issue count folded over the default panel, fix rounds, and the
   integrator), a chunking recommendation naming a slice size, and a required
   explicit cap above a stated run size. The estimate is pinned to the engine's
   LEAN defaults (one broad reviewer, one fix round) so it reflects real cost,
   not the heavier defaults it replaced.

2. The closing/reporting guidance confirms each closure by querying that issue's
   own state with ``gh issue view <n>``, and explicitly does NOT trust a
   ``gh issue list`` re-query — GitHub's list endpoint is eventually consistent
   and reads stale right after a close.

3. The finalize step prunes the run's leftover worktree scaffolding branches
   (issue #24), targeting only this run's own ``worktree-<runId>-*`` prefix with
   a scoped ``git branch -D`` — so it never deletes a feature branch or touches
   another run's scaffolding, and leaves #14's worktree teardown and its
   feature-branch ref preservation unchanged.

Run with: `uv run --with pytest pytest -q`
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_MD = REPO_ROOT / "skills" / "orchestrate" / "SKILL.md"


def _skill_text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _section(text: str, start_pattern: str, end_pattern: str) -> str:
    """Slice from the heading matching ``start_pattern`` up to (excluding) the
    next heading matching ``end_pattern`` — the whole file's tail if none."""

    start = re.search(start_pattern, text, re.MULTILINE)
    assert start is not None, f"section start not found: {start_pattern!r}"
    rest = text[start.start() :]
    end = re.search(end_pattern, rest[1:], re.MULTILINE)
    return rest if end is None else rest[: end.start() + 1]


def _confirm_section() -> str:
    """The '### 3. Confirm (single gate)' section and its subsections."""

    return _section(_skill_text(), r"^###\s+3\.\s+Confirm", r"^###\s+4\.")


def _finalize_section() -> str:
    """The '### 5. Finalize' section, up to '## Model and effort'."""

    return _section(_skill_text(), r"^###\s+5\.\s+Finalize", r"^##\s+Model and effort")


def _build_section() -> str:
    """The '### 4. Build (engine)' section, up to '### 5. Finalize'."""

    return _section(_skill_text(), r"^###\s+4\.\s+Build", r"^###\s+5\.")


# --- frontmatter guard -------------------------------------------------------


def test_frontmatter_name_is_orchestrate() -> None:
    assert re.search(r"^name:\s*orchestrate\s*$", _skill_text(), re.MULTILINE)


# --- confirm gate: cost estimate formula -------------------------------------


def test_confirm_gate_has_agent_cost_estimate_formula() -> None:
    section = _confirm_section().lower()
    # An estimate is presented at the gate.
    assert "estimate" in section
    assert "≈" in section or "formula" in section
    # A closed-form referencing the issue count multiplied by the per-issue factor.
    assert re.search(r"n\s*[×x*]\s*4", section), "expected a closed form like 'N × 4'"
    # The multiplicative factors are named: panel/reviewer, fix round, integrator.
    assert "sub-agent" in section
    assert "fix round" in section
    assert "panel" in section or "lens" in section or "reviewer" in section
    assert "integrat" in section


def test_estimate_translates_to_a_token_order_of_magnitude() -> None:
    section = _confirm_section().lower()
    assert "token" in section
    assert "thousand" in section or "million" in section or "order" in section


# --- confirm gate: chunking recommendation -----------------------------------


def test_confirm_gate_recommends_chunking_in_slices() -> None:
    section = _confirm_section().lower()
    assert "slice" in section
    assert re.search(r"8\s*[-–—]\s*10", section), "expected a slice size like 8–10"
    # The durability claim behind slicing is mode-qualified — default-branch under
    # --merge, per-issue PRs otherwise — not stated as always landing on main.
    assert "--merge" in section
    assert "pr" in section


# --- confirm gate: required cap names the REAL engine controls ---------------


def test_confirm_gate_requires_a_cap_above_a_stated_size() -> None:
    section = _confirm_section().lower()
    # A stated threshold, e.g. ~10 issues.
    assert "10 issues" in section
    # The cap is required, not optional.
    assert "cap" in section
    assert "require" in section or "must" in section
    # The named levers are the REAL engine controls: budgetFloor and slicing.
    assert "budgetfloor" in section
    assert "slic" in section  # slice / slicing
    # NOT a fictional max-agents cap the engine has no knob for.
    assert "max-agents" not in section


def test_budgetfloor_is_documented_as_a_settable_engine_arg() -> None:
    # The cap must be actionable: budgetFloor appears as an engine `args` knob in
    # the Build step, with its real default, so "require a cap" is something the
    # operator can actually set.
    build = _build_section().lower()
    assert "budgetfloor" in build
    assert "60000" in build or "60,000" in build


# --- confirm gate: estimate reflects the LEAN defaults -----------------------


def test_estimate_reflects_lean_defaults() -> None:
    section = _confirm_section().lower()
    # One broad reviewer, one fix round.
    assert "single" in section or "one broad reviewer" in section
    assert "one fix round" in section or "1 fix round" in section
    # NOT the heavier defaults it replaced.
    assert "three lenses" not in section
    assert "two fix rounds" not in section
    # The per-issue ×4 must NOT be described as implement/verify/fix/integrate —
    # that spelling silently drops the re-verify agent the engine always runs.
    assert "implement/verify/fix/integrate" not in section


def test_estimate_distinguishes_typical_from_worst_case() -> None:
    section = _confirm_section().lower()
    # The closed form is labelled typical/expected, not the worst case.
    assert "typical" in section or "average" in section
    # The honest per-issue range is 3–5 sub-agents.
    assert re.search(r"3\s*[-–—]\s*5", section), "expected the 3–5 per-issue range"
    # The re-verify agent dispatched after a fix round is acknowledged, not dropped.
    assert "re-verify" in section or "reverify" in section
    # Per-run overhead is stated for both modes (PR ≈2, merge up to ≈5).
    assert "pr mode" in section
    assert "merge mode" in section


# --- closing: verify each issue individually with `gh issue view` ------------


def test_closing_verifies_each_issue_with_gh_issue_view() -> None:
    section = _finalize_section().lower()
    assert "gh issue view" in section
    assert "state" in section or "closed" in section


def test_closing_warns_against_trusting_the_list_requery() -> None:
    section = _finalize_section()
    # The warning must sit on one physical line (repo markdown rule) carrying the
    # list command, the stale framing, and a negation together.
    warn_lines = [
        ln.lower() for ln in section.splitlines() if "gh issue list" in ln.lower()
    ]
    assert warn_lines, "closing guidance must mention gh issue list to warn against it"
    assert any(("stale" in ln or "eventually consistent" in ln) for ln in warn_lines), (
        "the gh issue list mention must be framed as stale / eventually consistent"
    )
    assert any(
        re.search(r"\b(not|never|rather than|instead of)\b", ln) for ln in warn_lines
    ), "the guidance must say not to rely on the list re-query"


# --- prune the run's leftover worktree scaffolding branches (issue #24) -------

# The Workflow harness names each per-worktree scaffolding branch
# ``worktree-<runId>-<n>``. #14's teardown removes the worktrees and preserves
# every feature-branch ref, but the harness's own scaffolding branches are left
# behind as orphaned refs that accumulate across runs. The orchestrator — which
# knows the runId from the Workflow launch — must prune exactly those run-scoped
# branches at the end of the run, confined to the run's own runId so no feature
# branch or unrelated branch is ever touched. The engine cannot enumerate the
# scaffolding names from ``git worktree list`` once the agents check out their
# feature branches, so the driver/finalize step in SKILL.md is the documented
# home. These tests are structural over that section.


def _prune_lines() -> list[str]:
    """Finalize-section paragraphs that tie the scaffolding prefix to the runId.

    A repo-markdown paragraph is a single physical line, so the whole prune
    instruction — its pattern, its confinement clause, and the delete command —
    sits on the one line these assertions inspect."""

    section = _finalize_section()
    return [
        ln
        for ln in section.splitlines()
        if "worktree-" in ln.lower() and "runid" in ln.lower()
    ]


def test_finalize_prunes_run_scoped_scaffolding_branches() -> None:
    section = _finalize_section().lower()
    # The finalize step prunes the leftover scaffolding branches at end of run.
    assert "prune" in section, (
        "finalize must document pruning the leftover worktree scaffolding branches"
    )
    # It names the run-scoped prefix the harness creates, so the match is anchored
    # to this run's runId — `worktree-<runId>-*`, not a bare `worktree-` glob.
    assert re.search(r"worktree-[<${]*runid", section), (
        "the prune step must target the run-scoped `worktree-<runId>-*` prefix"
    )


def test_prune_is_confined_to_the_exact_runid() -> None:
    lines = _prune_lines()
    assert lines, "no prune guidance tying `worktree-` to the runId was found"
    joined = " ".join(lines).lower()
    # The match is confined to this run's own runId ...
    assert "only" in joined or "exact" in joined or "confine" in joined, (
        "the prune must be confined to the run's own runId, not a loose match"
    )
    # ... so a feature branch or any unrelated branch is never deleted.
    assert "feature branch" in joined, (
        "the prune must promise never to delete a feature branch"
    )
    assert re.search(r"\bnever\b", joined), (
        "the prune must state it never touches a branch outside the run's prefix"
    )


def test_prune_uses_a_scoped_branch_delete() -> None:
    joined = " ".join(_prune_lines()).lower()
    # The prune is a real, scoped branch delete — the ONE authorised branch delete
    # (the teardown agent is forbidden any), so the delete command must appear on
    # the run-scoped line, never as a blanket `git branch -D`.
    assert "git branch -d" in joined, (
        "the prune step must give the run-scoped branch-delete command"
    )


def test_prune_preserves_issue_14_teardown() -> None:
    section = _finalize_section()
    lowered = section.lower()
    # The prune is additive: #14's worktree teardown and its preservation of every
    # feature-branch ref are left unchanged.
    assert "#14" in section or "feature-branch ref" in lowered, (
        "the prune step must state it leaves #14's teardown / ref preservation "
        "unchanged"
    )
