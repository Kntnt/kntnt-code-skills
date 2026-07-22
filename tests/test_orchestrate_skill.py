"""Structural tests for the orchestrate SKILL.md guidance (issues #19, #24, #25, #28, #30, #33).

These read ``skills/orchestrate/SKILL.md`` as text and assert several things the
skill's prose must carry — among them (issues #19/#24):

1. The single confirm gate sizes the run to its cost — an agent/token estimate
   *formula* (issue count folded over the verifier panel, the fix-round cap, and
   the integrator), a chunking recommendation naming a slice size, and a required
   explicit cap above a stated run size. Since #30 the estimate is **level-aware**:
   the per-issue factor scales with the level's panel size and fix-round cap
   (ADR-0001 §5), reducing to the lean ``N × 4 + 3`` at the default M level rather
   than a fixed ``× 4``.

2. The closing/reporting guidance confirms each closure by querying that issue's
   own state with ``gh issue view <n>``, and explicitly does NOT trust a
   ``gh issue list`` re-query — GitHub's list endpoint is eventually consistent
   and reads stale right after a close.

3. The finalize step prunes the run's leftover worktree scaffolding branches
   (issue #24), targeting only this run's own ``worktree-<runId>-*`` prefix with
   a scoped ``git branch -D`` — so it never deletes a feature branch or touches
   another run's scaffolding, and leaves #14's worktree teardown and its
   feature-branch ref preservation unchanged.

4. Since #33, the skill is reconciled with ADR-0003 (decoupling per-issue rigor
   from the ``--level`` dial): ``--max-lenses=N`` in §Arguments, mirroring
   ``--max-fix-rounds``, with ``N = 0`` as the sole route to a zero per-issue
   verifier panel while test-first, red-before-green, and the mandatory
   integration review still hold; ``--pr`` as the explicit conservative partner
   of ``--merge`` (precedence explicit flag > policy > PR default, ``--pr`` +
   ``--merge`` together an error, merge authority never inferred); the ADR-0003
   §5 risk precedence (plan-time hazard → gate, in-situ hazard → one automatic
   lens, no mid-run pause, ``--yes`` stays gate-only); the ``--max-lenses=0``
   use-case (a large homogeneous-trivial batch) and non-use-case (a small
   trivial task calls for a lighter tool); the decision-boundary map rows for
   both flags; and the amended §5 floor prose — the per-issue-lens floor is
   breachable only by an explicit ``--max-lenses=0``, never by a level, a
   policy, or ``--yes``.

Run with: `uv run --with pytest pytest -q`
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_MD = REPO_ROOT / "skills" / "orchestrate" / "SKILL.md"

# Load scripts/orchestrate.py by path so the marker-consistency test can bind the
# SKILL-documented template to the real `parse_landed_marker` (issue #49).
_SCRIPT = REPO_ROOT / "scripts" / "orchestrate.py"
_spec = importlib.util.spec_from_file_location("orchestrate", _SCRIPT)
assert _spec is not None and _spec.loader is not None
orchestrate = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = orchestrate
_spec.loader.exec_module(orchestrate)


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


def _arguments_section() -> str:
    """The '## Arguments' section, up to '## The operating contract'."""

    return _section(_skill_text(), r"^##\s+Arguments", r"^##\s+The operating contract")


def _model_effort_section() -> str:
    """The '## Model and effort' section, up to the next '## ' heading."""

    return _section(_skill_text(), r"^##\s+Model and effort", r"^##\s+\S")


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


# --- confirm gate: estimate reflects the ADR-0004 two-tier ladder ------------

# Since ADR-0004 rigor saturates at M: XS/S remain the lean fast lane (1 broad
# lens, 1 fix round), while the default M level — and L/XL with it — sits at the
# full 3-lens, 2-round top tier. The cost prose must present BOTH tiers honestly,
# not the old flat "M is lean" framing.


def test_estimate_presents_both_the_lean_fast_lane_and_the_m_default() -> None:
    section = _confirm_section().lower()
    # The lean XS/S fast lane is still a single broad reviewer, one fix round.
    assert "single" in section or "one broad reviewer" in section
    assert "one fix round" in section or "1 fix round" in section
    assert "fast lane" in section, (
        "the cost prose must frame XS/S as the lean fast lane, not M"
    )
    # The default M level is NO LONGER lean — rigor saturates at M: 3 lenses, 2
    # fix rounds. The prose must state that increase honestly.
    assert "5" in section and re.search(r"5\s*[-–—]\s*9", section), (
        "the M-tier per-issue range (5–9 sub-agents) must be stated"
    )
    assert "saturat" in section, (
        "the cost prose must state rigor saturates at M (so L/XL cost the same)"
    )
    # The per-issue ×N must NOT be described as implement/verify/fix/integrate —
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


# --- #30 / ADR-0004: the cost estimate is level-aware ------------------------

# Since #30 the per-issue cost is no longer a fixed × 4: the `--level` dial sets
# both the verifier panel size and the fix-round cap (ADR-0001 §5), so a higher
# level raises the per-issue sub-agent count. Since ADR-0004 the tiers are XS/S
# (`P=1`, `F=1` → `N × 4 + 3`) and M/L/XL (`P=3`, `F=2` → `N × 7 + 3`); the
# estimate must scale with `P` and `F` and name the default M instance at N × 7.


def test_estimate_is_level_aware() -> None:
    section = _confirm_section().lower()
    # The estimate is explicitly level-aware, keyed on the panel size and cap.
    assert "level-aware" in section
    assert "panel size" in section
    assert "fix-round cap" in section
    # The closed form is parameterized by the panel size (a factor the level sets),
    # e.g. N × (P + F + 2), not a bare N × 4.
    assert re.search(r"n\s*[×x*]\s*\(", section), (
        "the level-aware form must parameterize the per-issue factor, e.g. N × (P + F + 2)"
    )
    # The honest per-issue worst case folds the re-verify agent: P + 2F + 2.
    assert re.search(r"p\s*\+\s*2f", section), (
        "the per-issue worst case must be P + 2F + 2 (panel once, then fix + re-verify each round)"
    )
    # A higher level raises the per-issue sub-agent count.
    assert "higher level" in section
    # The lean XS/S fast lane reduces to N × 4 ...
    assert re.search(r"n\s*[×x*]\s*4", section), (
        "the XS/S fast-lane instance must reduce to the lean N × 4"
    )
    # ... and the default M level, with rigor saturated, reduces to N × 7.
    assert re.search(r"n\s*[×x*]\s*7", section), (
        "the default-M instance must reduce to N × 7 (P=3, F=2 since ADR-0004)"
    )


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


# --- the --level ambition dial (issue #25) -----------------------------------

# One semantic ambition dial — `--level`, fixed vocabulary XS|S|M|L|XL, default
# M — makes the model and reasoning effort of every sub-agent a function of the
# dial instead of everything inheriting the session tier. §Arguments documents the
# dial; §Model and effort documents that the ORCHESTRATOR derives the per-role
# (model, effort) from the level against the harness's LIVE model list (the engine
# stores no model-name table), shows the ADR §4 ladder as an illustrative,
# NON-durable instantiation, and states the two guardrails: only dispatchable
# models, and judgment roles never below the session tier unless dialed down.


def test_arguments_documents_the_level_dial() -> None:
    section = _arguments_section()
    lowered = section.lower()
    # The dial itself is named as a flag.
    assert "--level" in section, "§Arguments must document the `--level` flag"
    # Its fixed t-shirt vocabulary is spelled out.
    for size in ("XS", "S", "M", "L", "XL"):
        assert re.search(rf"\b{size}\b", section), (
            f"§Arguments must list the `{size}` level in the dial's vocabulary"
        )
    # The default is M.
    assert "default" in lowered and re.search(r"default[^.]*\bm\b", lowered), (
        "§Arguments must state the dial defaults to M"
    )


def test_model_effort_derives_per_role_from_the_level() -> None:
    section = _model_effort_section()
    lowered = section.lower()
    # The derivation is the orchestrator's, keyed on the level, per role.
    assert "--level" in section or "level" in lowered, (
        "§Model and effort must tie the per-role model/effort to the level"
    )
    assert "orchestrator" in lowered, (
        "§Model and effort must say the ORCHESTRATOR does the resolution — the "
        "engine has no primitive to enumerate live models"
    )
    assert "per-role" in lowered or "per role" in lowered, (
        "§Model and effort must describe a PER-ROLE (model, effort) resolution"
    )
    assert "effort" in lowered and "model" in lowered, (
        "the resolution carries both a model and a reasoning effort"
    )


def test_model_effort_resolves_against_the_live_model_list() -> None:
    section = _model_effort_section()
    lowered = section.lower()
    # The mapping is derived at runtime against the harness's live model list, so it
    # self-updates as models change — no literal model-name table is the contract.
    assert "live model" in lowered or "live models" in lowered, (
        "§Model and effort must say the resolution is against the harness's LIVE "
        "model list, so the mapping self-updates as models change"
    )
    assert "table" in lowered or "non-durable" in lowered or "not durable" in lowered, (
        "§Model and effort must state the concrete mapping is not the durable "
        "contract (no stored model-name table)"
    )


def test_model_effort_shows_the_illustrative_ladder() -> None:
    section = _model_effort_section().lower()
    # The ADR §4 ladder appears as an ILLUSTRATIVE, non-durable instantiation.
    assert "illustrative" in section or "as of" in section, (
        "§Model and effort must present the ladder as an illustrative instantiation"
    )
    # A ladder is shown: some concrete model names the derivation produces today.
    named_models = sum(
        1 for model in ("opus", "sonnet", "haiku", "fable") if model in section
    )
    assert named_models >= 2, (
        "§Model and effort must show a concrete illustrative ladder naming the "
        "models the derivation produces today (e.g. Opus / Sonnet / Haiku)"
    )


def test_illustrative_ladder_efforts_stay_on_the_stated_scale() -> None:
    # The section states the effort scale is `low < medium < high < xhigh < max`.
    # The illustrative ladder must not name a phantom effort off that scale without
    # disambiguating it. Today the cheapest tier is written `Haiku · thinking`, and
    # `thinking` is NOT a rung on the stated scale — so if it appears it must carry
    # the ADR-0001 §4 gloss (Thinking = Haiku with light extended thinking), or a
    # reader deriving efforts against the ladder hits a self-contradiction.
    section = _model_effort_section().lower()
    assert "low < medium < high < xhigh < max" in section, (
        "§Model and effort must state the effort ladder low < medium < high < xhigh < max"
    )
    if "thinking" in section:
        assert "extended thinking" in section, (
            "the ladder names the effort `thinking`, which is not on the stated "
            "low < medium < high < xhigh < max scale; it must be glossed (ADR-0001 "
            "§4: Thinking = Haiku with light extended thinking) so the section does "
            "not contradict its own effort scale"
        )


def test_model_effort_states_the_two_guardrails() -> None:
    section = _model_effort_section().lower()
    # Guardrail 1: only models the harness can actually dispatch are chosen.
    assert "dispatch" in section, (
        "§Model and effort must state guardrail 1 — only dispatchable models are picked"
    )
    # Guardrail 2: judgment roles never drop below the session tier unless the
    # maintainer explicitly dialed down.
    assert "judgment" in section or "judgement" in section, (
        "§Model and effort must name the judgment roles for guardrail 2"
    )
    assert "session" in section, (
        "guardrail 2 pins judgment roles to the session tier as a floor"
    )
    assert "dial" in section and (
        "below" in section or "never" in section or "floor" in section
    ), (
        "guardrail 2 must state judgment roles never drop below the session tier "
        "unless the maintainer dialed down"
    )


# --- #30: rigor baseline + sliding implementer folded into §Model and effort --

# ADR-0001 §1 says the `--level` dial carries BOTH halves of ambition — the
# per-role (model, effort) AND the verification-rigor baseline. ADR-0002 adds the
# sliding implementer: a per-issue implementation plan whose detail scales
# inversely with the level, and a run-level `implementerMode` framing. §Model and
# effort must document both, so the section matches the IMPLEMENTED derivation
# rather than the old flat "single reviewer, one fix round".


def test_model_effort_documents_the_level_derived_rigor_baseline() -> None:
    section = _model_effort_section()
    lowered = section.lower()
    # The dial carries the rigor baseline alongside model/effort ...
    assert "rigor" in lowered
    assert "lens" in lowered and "fix round" in lowered
    # ... the panel scales with the level (1 broad at the low end, focused higher) ...
    assert "broad" in lowered and "focused" in lowered
    # ... per-issue risk escalates it, escalate-only ...
    assert "risk" in lowered and "escalat" in lowered
    # ... and an inviolable floor holds, with 0 rounds reachable only via the flag.
    assert "floor" in lowered
    assert "--max-fix-rounds" in section, (
        "§Model and effort must state 0 fix rounds is reachable only via --max-fix-rounds=0"
    )


def test_model_effort_documents_the_sliding_implementer_and_plan_pass() -> None:
    section = _model_effort_section()
    lowered = section.lower()
    # ADR-0002 is cited and its two mechanisms described.
    assert "adr-0002" in lowered, (
        "§Model and effort must cite ADR-0002 for the sliding implementer + plan pass"
    )
    # The per-issue implementation plan whose detail scales inversely with the level.
    assert "plan" in lowered
    assert "recipe" in lowered, "the XS/S plan shape (a recipe) must be named"
    # The run-level implementerMode framing marker and its three values.
    assert "implementermode" in lowered
    assert "execute" in lowered and "balanced" in lowered and "autonomous" in lowered, (
        "the three implementerMode framings must be named"
    )


def test_build_step_launch_args_include_implementer_mode_and_plan() -> None:
    # ADR-0002's two new engine args — the run-level `implementerMode` framing
    # marker and each issue's per-issue `plan` overlay — must ride the same launch
    # instruction as #25's `roles`, or a session assembling the payload from this
    # list ships neither and the sliding implementer silently reverts to today's
    # flat implement prompt.
    build = _build_section()
    launch_lines = [ln for ln in build.splitlines() if "as `args`" in ln]
    assert launch_lines, (
        "the Build step must carry a launch instruction passing the plan `as args`"
    )
    launch = " ".join(launch_lines).lower()
    assert "implementermode" in launch, (
        "the launch args must list `implementerMode` (ADR-0002 §4)"
    )
    assert "plan" in launch, (
        "the launch args must list each issue's per-issue implementation `plan` (ADR-0002 §5)"
    )


def test_build_step_launch_args_include_roles() -> None:
    # Step 4's launch instruction is the closed enumeration of what the orchestrator
    # passes to the engine as `args` — the natural procedural checklist a session
    # builds the payload from. #25 added `roles` (the per-role (model, effort) the
    # --level dial resolved) as a new engine arg, and §Model and effort says the
    # orchestrator "hands it to the engine as args.roles". If step 4 omits `roles`,
    # a session that assembles the payload from this list ships no roles; the engine
    # then sees config.roles undefined, every roleTuning() returns {}, and every
    # sub-agent reverts to the session model — the exact 'everything runs on Opus'
    # cost problem #25 was created to end. So the launch args must list `roles`
    # alongside the other resolved knobs.
    build = _build_section()
    launch_lines = [ln for ln in build.splitlines() if "as `args`" in ln]
    assert launch_lines, (
        "the Build step must carry a launch instruction passing the plan `as args`"
    )
    launch = " ".join(launch_lines).lower()
    for knob in (
        "merge",
        "maxfixrounds",
        "maxintegrationrounds",
        "budgetfloor",
        "lenses",
    ):
        assert knob in launch, f"the launch args enumeration must name `{knob}`"
    assert "roles" in launch, (
        "the Build step's launch args enumeration must list `roles` (the per-role "
        "(model, effort) the --level dial resolved), so the orchestrator actually "
        "threads it into the engine; without it config.roles is undefined and every "
        "sub-agent reverts to the session model"
    )


# --- #28: --yes != merge authority; per-project merge policy; safety floor ----

# ADR-0001 §7 separates `--yes` (yes to the single confirm gate, and nothing more)
# from merge authority (`--merge` OR a once-per-project/global policy; plugin
# default = PR), and §8's decision-boundary map surfaces merge-vs-PR at the single
# gate while `--yes` waives only the go/no-go. SKILL.md must carry that separation,
# name where the project merge policy is recorded and read, and restate the
# inviolable safety floor. These tests are structural over that prose.


def _operating_contract_section() -> str:
    """The '## The operating contract' section, up to the decision-boundary map
    (or '## Flow' when the map is absent)."""

    return _section(
        _skill_text(),
        r"^##\s+The operating contract",
        r"^##\s+(?:The decision-boundary map|Flow)",
    )


def _decision_map_section() -> str:
    """The '## The decision-boundary map' section, up to '## Flow'."""

    return _section(_skill_text(), r"^##\s+The decision-boundary map", r"^##\s+Flow")


def _argument_line(flag: str) -> str:
    """The single physical line for an argument bullet — the repo markdown rule
    keeps each list item on one physical line, so the whole bullet is one line."""

    for line in _arguments_section().splitlines():
        if line.lstrip().startswith(f"- `{flag}`"):
            return line
    raise AssertionError(f"no argument bullet found for {flag}")


def test_yes_argument_waives_only_the_gate_not_merge() -> None:
    line = _argument_line("--yes").lower()
    # --yes is scoped to the single confirm gate and nothing more.
    assert "nothing more" in line, (
        "the --yes argument must be scoped to the confirm gate and nothing more"
    )
    # It explicitly does NOT grant merge authority.
    assert "merge authority" in line and re.search(
        r"\b(not|never|does not|doesn't)\b", line
    ), "the --yes argument must state it does NOT grant merge authority"


def test_merge_argument_names_authority_sources_and_pr_default() -> None:
    line = _argument_line("--merge").lower()
    # --merge grants merge authority ...
    assert "merge authority" in line
    # ... the other source being a once-per-project (or global) policy ...
    assert "policy" in line
    assert "project" in line or "global" in line
    # ... and the plugin default is PR.
    assert "default" in line and ("pr" in line or "pull request" in line)


def test_operating_contract_separates_yes_from_merge_authority() -> None:
    section = _operating_contract_section().lower()
    # The contract binds --yes to the gate only, not to writing the default branch.
    assert "--yes" in section
    assert "merge authority" in section
    assert (
        "nothing more" in section
        or "go/no-go" in section
        or "default branch" in section
    )
    # Merge authority = --merge OR a once-per-project/global policy; default PR.
    assert "--merge" in section
    assert "policy" in section
    assert "pr" in section or "pull request" in section


def test_operating_contract_specifies_where_merge_policy_lives() -> None:
    section = _operating_contract_section().lower()
    # The policy is a marker in the project's own agent config ...
    assert "merge-policy" in section or "merge policy" in section
    assert "agents.md" in section or "claude.md" in section
    # ... read by the orchestrator at plan time, not a deterministic code path.
    assert (
        "plan time" in section or "profile and gather" in section or "step 1" in section
    )


def _safety_floor_bullets() -> list[str]:
    """The nested sub-bullets under 'The inviolable safety floor'.

    Each ADR-0001 §7 floor element is its own physical sub-bullet, so a dropped
    element leaves its whole line absent — not merely its tokens, several of which
    (``default branch``, ``verif``/``integrat``, ``adr``+``park``, ``budget``)
    recur in other bullets of the section. Pinning each element to the floor
    sub-bullets is what lets a dropped floor element turn the test red."""

    bullets: list[str] = []
    collecting = False
    for line in _operating_contract_section().splitlines():
        if "inviolable safety floor" in line.lower():
            collecting = True
            continue
        if not collecting:
            continue
        stripped = line.lstrip()
        # An indented list item is a floor sub-bullet; a blank line is skipped;
        # anything else (a top-level bullet, prose) ends the floor list.
        if line != stripped and stripped.startswith("- "):
            bullets.append(stripped.lower())
        elif stripped:
            break
    return bullets


def test_operating_contract_restates_the_inviolable_safety_floor() -> None:
    section = _operating_contract_section().lower()
    assert "safety floor" in section or "inviolable" in section

    floor = _safety_floor_bullets()
    assert floor, "the safety floor must be a nested list of per-element bullets"

    def has(*needles: str) -> bool:
        """True when one floor sub-bullet carries every needle."""

        return any(all(n in bullet for n in needles) for bullet in floor)

    # Each ADR-0001 §7 floor element is pinned to its OWN sub-bullet, so dropping
    # any single element turns this red even when its tokens recur elsewhere.
    assert has("force-push", "refus") or has("force push", "refus"), (
        "floor must carry the never-force-push element (a force push is refused)"
    )
    assert has("default branch"), (
        "floor must carry the never-merge-to-default-without-authority element"
    )
    assert has("gh issue view", "verif", "integrat"), (
        "floor must carry the close-only-after-verify-and-integrate element"
    )
    assert has("rigor", "budget"), (
        "floor must carry the rigor-floor + budget-bound element"
    )
    assert has("adr", "park"), (
        "floor must carry the never-override-an-ADR (park + report) element"
    )
    assert has("bump") or has("tag") or has("release"), (
        "floor must carry the never-bump/tag/release element"
    )
    # The run-scoped scaffolding-branch prune confinement (ADR §7's last floor
    # bullet): confined to worktree-<runId>-* and skipped when runId is unresolved.
    assert has("worktree-", "runid"), (
        "floor must restate the run-scoped scaffolding-branch prune confinement "
        "(worktree-<runId>-*), completing the ADR §7 restatement"
    )


def test_confirm_gate_surfaces_the_merge_vs_pr_decision() -> None:
    section = _confirm_section().lower()
    assert "merge" in section
    assert "pr" in section or "pull request" in section
    # The gate SHOWS the merge decision — settled before it by --merge or policy.
    assert "policy" in section
    assert "decision" in section


def test_confirm_gate_yes_waives_only_the_go_no_go() -> None:
    lines = [
        ln.lower() for ln in _confirm_section().splitlines() if "--yes" in ln.lower()
    ]
    assert lines, "the confirm gate must mention --yes"
    joined = " ".join(lines)
    # --yes waives ONLY the go/no-go, not the merge decision.
    assert "go/no-go" in joined or "go / no-go" in joined
    assert "only" in joined
    assert "merge" in joined


# --- #30: the decision-boundary map (ADR-0001 §8) ----------------------------

# ADR-0001 §8 collapses the whole run to one map: almost every decision is silent
# (autonomous), and only THREE surface at the single gate — merge authority, the
# cost cap, and the go/no-go — with the per-issue `Risk:` marker as the one
# optional human lever. SKILL.md must carry that map end-to-end.


def test_decision_boundary_map_exists_and_names_the_three_gate_decisions() -> None:
    section = _decision_map_section()
    lowered = section.lower()
    # The map cites ADR-0001 §8.
    assert "§8" in section or "adr-0001" in lowered, (
        "the decision-boundary map must cite ADR-0001 §8"
    )
    # Almost everything is silent / autonomous.
    assert "silent" in lowered or "autonomous" in lowered
    # The three gate-surfaced decisions.
    assert "merge authority" in lowered, (
        "the map must surface merge authority at the gate"
    )
    assert "cost cap" in lowered, "the map must surface the cost cap at the gate"
    assert "go/no-go" in lowered or "whether to run" in lowered, (
        "the map must surface the go/no-go at the gate"
    )


def test_decision_boundary_map_marks_defaults_silent_and_risk_optional() -> None:
    section = _decision_map_section().lower()
    # The silent-by-default decisions the map must list.
    for decision in ("scope", "model/effort", "rigor", "fix"):
        assert decision in section, f"the map must list the silent decision: {decision}"
    # The per-issue `Risk:` marker is the one OPTIONAL human lever, never required.
    assert "risk" in section
    assert "optional" in section or "never required" in section, (
        "the map must mark the per-issue Risk marker as optional / never required"
    )


# --- #33: reconcile SKILL.md with ADR-0003 (--max-lenses, --pr) --------------

# ADR-0003 decouples per-issue rigor from the `--level` dial: a new per-run
# `--max-lenses=N` override (mirroring `--max-fix-rounds`) caps the per-issue
# verifier panel, and `N = 0` is the sole, explicit route to a zero panel —
# the only amendment to ADR-0001 §5's inviolable lens floor. A new `--pr` flag
# is the explicit conservative partner of `--merge`. §5 also defines the risk
# precedence under `--max-lenses=0`: a plan-time hazard surfaces at the gate
# (the flag still holds), an in-situ hazard escalates exactly one automatic
# lens, and there is never a mid-run pause. These tests are structural over
# SKILL.md's §Arguments, §Model and effort (which folds in the rigor-baseline
# subsection), and the decision-boundary map.


def test_arguments_documents_max_lenses_override() -> None:
    line = _argument_line("--max-lenses=N").lower()
    # Mirrors --max-fix-rounds exactly, as a per-run override only.
    assert "--max-fix-rounds" in line, (
        "the --max-lenses argument must state it mirrors --max-fix-rounds"
    )
    assert "per-run" in line, (
        "the --max-lenses argument must state it is a per-run override, never "
        "a policy default"
    )
    # N = 0 is the only route to a zero panel.
    assert re.search(r"n\s*=\s*0", line), (
        "the --max-lenses argument must document N = 0 as the zero-panel case"
    )
    # What a zero panel still keeps: test-first, red-before-green, integration review.
    assert "test-first" in line, (
        "the --max-lenses=0 case must state test-first still holds"
    )
    assert "red-before-green" in line, (
        "the --max-lenses=0 case must state red-before-green still holds"
    )
    assert "integration review" in line and "mandatory" in line, (
        "the --max-lenses=0 case must state the mandatory integration review still holds"
    )


def test_arguments_documents_pr_flag() -> None:
    line = _argument_line("--pr").lower()
    # The explicit conservative partner of --merge.
    assert "--merge" in line
    assert "conservative" in line, (
        "the --pr argument must be framed as the conservative partner of --merge"
    )
    # Precedence: explicit flag > policy > PR default.
    assert "precedence" in line
    assert "policy" in line
    # --pr and --merge together is an error.
    assert "error" in line, (
        "the --pr argument must state --pr + --merge together is an error"
    )
    # Merge authority is never inferred.
    assert "never" in line and "infer" in line, (
        "the --pr argument must state merge authority is never inferred"
    )


def test_rigor_baseline_documents_adr0003_risk_precedence() -> None:
    section = _model_effort_section().lower()
    assert "adr-0003" in section, (
        "the rigor section must cite ADR-0003 for the risk-precedence amendment"
    )
    assert "plan-time" in section, (
        "the risk precedence must name the plan-time-hazard channel (surfaced at the gate)"
    )
    assert "in-situ" in section, (
        "the risk precedence must name the in-situ-hazard channel (one automatic lens)"
    )
    assert re.search(r"\bone\b[^.]*\blens\b", section), (
        "the in-situ channel must escalate exactly ONE automatic lens"
    )
    assert "mid-run pause" in section, (
        "the risk precedence must state there is no mid-run pause"
    )
    assert "--yes" in section, (
        "the risk precedence must restate --yes stays gate-only under --max-lenses=0"
    )


def test_rigor_baseline_states_max_lenses_zero_use_case_and_non_use_case() -> None:
    section = _model_effort_section().lower()
    # The use-case: a large, homogeneous, low-risk batch.
    assert "batch" in section
    assert "homogeneous" in section or "homogeneous-trivial" in section
    # The non-use-case: a small trivial task reaches for a lighter tool, not a
    # verification-off orchestrate run.
    assert "lighter tool" in section, (
        "the non-use-case must point a small trivial task at a lighter tool"
    )


def test_rigor_floor_prose_reflects_max_lenses_zero_amendment() -> None:
    section = _model_effort_section().lower()
    # The floor is now breachable, but only by the explicit flag.
    assert "breachable only" in section, (
        "the §5 floor prose must state the per-issue-lens floor is breachable ONLY"
    )
    assert "--max-lenses=0" in section, (
        "the floor amendment must name the exact breaching flag --max-lenses=0"
    )
    # Never by a level, a policy, or --yes.
    assert "never" in section
    assert "policy" in section
    assert "--yes" in section


def test_decision_boundary_map_has_max_lenses_row() -> None:
    section = _decision_map_section().lower()
    assert "--max-lenses" in section, (
        "the decision-boundary map must gain a row for --max-lenses"
    )
    assert "=0" in section or "= 0" in section, (
        "the --max-lenses row must name 0 as the floor-breaching value"
    )


def test_decision_boundary_map_has_pr_row_and_never_inferred_note() -> None:
    section = _decision_map_section().lower()
    assert "--pr" in section, "the decision-boundary map must gain a row for --pr"
    assert "never" in section and "infer" in section, (
        "the decision-boundary map must note merge authority is never inferred"
    )


# --- #34: implicit issue relationships beyond Blocked-by edges ---------------

# The deterministic planner (`orchestrate.py plan`) computes only the explicit
# `Blocked by` edge graph and stays prose-blind by design — unchanged by this
# issue. The orchestrator's own read of every in-scope issue and brief (step 1)
# must additionally assess two implicit relationships the issue text can
# reveal that the helper does not compute: same-wave file/module overlap
# (-> serialize the colliding pair) and a cross-reference to another in-scope
# issue's not-yet-built deliverable (-> order the referrer after the provider,
# or flag the missing edge). Both are surfaced at the confirm gate, the plan's
# `soft_notes` is read as first-class input to the overlap assessment, and the
# "issues in one wave are independent" claim is qualified to
# dependency-independence only. These tests are structural over SKILL.md's
# step 2 (Plan) and step 3 (Confirm, including Cost and chunking).


def _plan_section() -> str:
    """The '### 2. Plan (deterministic)' section and its subsections."""

    return _section(_skill_text(), r"^###\s+2\.\s+Plan", r"^###\s+3\.")


def test_wave_independence_wording_is_qualified_to_dependency_independence() -> None:
    section = _plan_section().lower()
    # The bare claim "independent" must be qualified to dependency-independence
    # only — it is not a promise the pair shares no other coupling.
    assert (
        "dependency-independent" in section or "dependency independence" in section
    ), "the wave-independence claim must be qualified to dependency-independence"


def test_plan_step_assesses_same_wave_file_overlap_and_serializes() -> None:
    section = _plan_section().lower()
    assert "overlap" in section
    assert "same-wave" in section or "same wave" in section
    assert "serialize" in section
    # The concrete corrective actions the brief names.
    assert "one-issue-per-slice" in section or "soft-order" in section


def test_plan_step_reads_soft_notes_as_first_class_input_to_overlap() -> None:
    section = _plan_section().lower()
    assert "soft_notes" in section, (
        "the plan step must name `soft_notes` as input to the overlap assessment"
    )
    assert "first-class input" in section or "first class input" in section, (
        "soft_notes must be read as first-class input, not merely an audit-trail note"
    )


def test_plan_step_detects_deliverable_cross_reference_and_orders_it() -> None:
    section = _plan_section().lower()
    assert "deliverable" in section
    assert "command" in section and "symbol" in section and "file" in section
    assert "missing" in section and ("hard edge" in section or "blocked by" in section)
    assert "order the referrer" in section or (
        "referrer" in section and "provider" in section
    )


def test_plan_step_states_relationships_are_silent_but_surfaced_at_gate() -> None:
    section = _plan_section().lower()
    assert "confirm gate" in section or "step 3" in section
    assert "reorder" in section
    assert "serializ" in section
    assert "why" in section


def test_confirm_gate_shows_reordering_and_serialization_with_reasons() -> None:
    section = _confirm_section().lower()
    assert "reorder" in section or "serializ" in section
    assert (
        "overlap" in section or "cross-reference" in section or "deliverable" in section
    )


def test_cost_chunking_names_both_facets_as_serialize_or_order_reasons() -> None:
    section = _confirm_section().lower()
    assert "overlap" in section
    assert "cross-reference" in section or "deliverable" in section
    assert "serialize" in section or "reorder" in section
    assert "one-issue-per-slice" in section
    assert "tightly-coupled" in section or "tightly coupled" in section


# --- #36: implementer ripple report + verifier consistency lens --------------

# When an implementer changes a shared symbol's contract or effective behaviour
# but updates only some callers, the diff is locally consistent; a per-issue
# verifier is bound to the diff and structurally cannot see the unchanged
# callers, so the class was previously caught only by the mandatory integration
# review — a full extra review + remediation cycle. Two prose additions: (1) the
# operating contract's three-bucket handoff description (Assumptions &
# blockers) now instructs the implementer to enumerate affected call sites and
# report which were updated and which were not; (2) step 4's Verify description
# documents the conditional consistency lens every dispatched reviewer carries,
# scoped to fire only when the diff touches a shared, multi-caller symbol.


def test_operating_contract_three_bucket_instructs_the_ripple_report() -> None:
    section = _operating_contract_section().lower()
    assert "assumptions & blockers" in section or "assumptions and blockers" in section
    assert "shared symbol" in section, (
        "the three-bucket description must instruct reporting a shared-symbol "
        "contract/behaviour change"
    )
    assert "call site" in section or "caller" in section, (
        "the three-bucket description must ask for the affected call sites"
    )
    assert "updated" in section, (
        "the three-bucket description must ask which call sites were updated "
        "(and which were not)"
    )


def test_verify_step_documents_the_conditional_consistency_lens() -> None:
    build = _build_section().lower()
    assert "unchanged" in build, (
        "step 4's Verify description must document checking a shared symbol's "
        "UNCHANGED callers"
    )
    assert "shared" in build and (
        "multi-caller" in build or "multiple caller" in build
    ), "the consistency lens must be scoped to a shared, multi-caller symbol"
    assert "consisten" in build, (
        "step 4's Verify description must name the consistency check"
    )
    assert "only when" in build or "scoped to fire" in build or "no such" in build, (
        "the consistency lens must be explicitly conditional — it fires only "
        "when a shared symbol is touched, so an ordinary diff pays nothing extra"
    )


# --- durable landed-markers + interrupt-safe restart (issue #49) --------------


def _restart_section() -> str:
    """The '## Restarting a stopped run' section, up to '## Model and effort'."""

    return _section(
        _skill_text(),
        r"^##\s+Restarting a stopped run",
        r"^##\s+Model and effort",
    )


def test_skill_documents_the_landed_marker_templates_that_round_trip() -> None:
    # AC: a consistency test binds the marker template SKILL.md tells the integrate
    # step to post to the real `parse_landed_marker`. The exact canonical templates
    # must appear in the skill, and substituting concrete values must round-trip
    # through the parser — so the documented format can never drift from the code.
    text = _skill_text()

    landed_template = "orchestrate: landed <sha> on <branch>, run <runId>"
    pr_template = "orchestrate: opened PR #<pr>, run <runId>"
    assert landed_template in text, (
        "SKILL.md must document the canonical landed-marker template verbatim"
    )
    assert pr_template in text, (
        "SKILL.md must document the canonical PR-marker template verbatim"
    )

    # The documented template, with concrete values substituted, must parse.
    landed = (
        landed_template.replace("<sha>", "deadbeef")
        .replace("<branch>", "main")
        .replace("<runId>", "wf_consistency")
    )
    parsed = orchestrate.parse_landed_marker(landed)
    assert parsed is not None and parsed.verb == "landed", (
        "the landed-marker template SKILL tells integrate to post must round-trip "
        "through parse_landed_marker"
    )
    assert parsed.sha == "deadbeef" and parsed.branch == "main"

    pr = pr_template.replace("<pr>", "42").replace("<runId>", "wf_consistency")
    parsed_pr = orchestrate.parse_landed_marker(pr)
    assert parsed_pr is not None and parsed_pr.verb == "opened-pr", (
        "the PR-marker template SKILL tells integrate to post must round-trip "
        "through parse_landed_marker"
    )
    assert parsed_pr.pr == 42


def test_skill_states_workflow_resume_is_same_session_only() -> None:
    section = _restart_section()
    lowered = section.lower()
    assert "same-session" in lowered or "same session" in lowered, (
        "the restart section must state Workflow resume is same-session-only"
    )
    assert "resumefromrunid" in lowered, (
        "the restart section must name resumeFromRunId as the same-session-only "
        "mechanism"
    )


def test_skill_prescribes_the_cross_session_restart_protocol() -> None:
    section = _restart_section()
    lowered = section.lower()
    # Re-plan against reality, launch a fresh run over the remainder — never blind
    # resume — and lean on the preflight guard for idempotence.
    assert "orchestrate.py plan" in section, (
        "the restart protocol must prescribe re-running orchestrate.py plan"
    )
    assert "never blind-resume" in lowered or "never blind resume" in lowered, (
        "the restart protocol must forbid a blind cross-session resume"
    )
    assert "preflight" in lowered, (
        "the restart protocol must point at the preflight idempotence guard as the "
        "safety net"
    )


def test_skill_corrects_the_completion_notification_resume_advice() -> None:
    # The completion-notification advice must no longer steer a cross-session
    # operator into a silent full re-run: wherever the skill mentions resuming via
    # runId, it must qualify it as same-session-only.
    text = _skill_text()
    assert "resumable via its `runId`" not in text, (
        "the old unqualified 'resumable via its runId' claim must be corrected — it "
        "led a cross-session operator into a silent full re-run"
    )
    # The build step must carry the same-session-only qualification.
    build = _build_section()
    assert "same-session-only" in build.lower(), (
        "the build step must qualify Workflow resume as same-session-only"
    )


def test_skill_documents_close_at_integrate_and_the_narrow_exception() -> None:
    text = _skill_text()
    build = _build_section()
    # Merge mode closes the issue at integrate time (D1), posting the durable marker.
    assert "close" in build.lower() and "integrate" in build.lower(), (
        "the build step must state the issue is closed at integrate time in merge mode"
    )
    # The narrow single-mutator exception is named (only integrate may close/mark).
    lowered = text.lower()
    assert "narrow exception" in lowered, (
        "the skill must name the narrow integrate-only exception for the marker+close"
    )


# --- ADR-0005 (issue #49) -----------------------------------------------------

ADR_0005 = (
    REPO_ROOT / "docs" / "adr" / "0005-durable-landed-markers-and-close-at-integrate.md"
)


def test_adr0005_exists_and_amends_adr0001_by_reference() -> None:
    assert ADR_0005.exists(), "ADR-0005 must exist"
    text = ADR_0005.read_text(encoding="utf-8")
    lowered = text.lower()

    # It amends ADR-0001 §5/§7 by reference (not by rewriting them).
    assert "adr-0001" in lowered or "0001" in text
    assert "§5" in text and "§7" in text, (
        "ADR-0005 must name the ADR-0001 sections it amends (§5 and §7)"
    )

    # It records the orchestrator-blocked-mid-run constraint and the narrow
    # integrate-only exception.
    assert "blocked on the single workflow call" in lowered, (
        "ADR-0005 must capture the orchestrator-blocked-mid-run constraint that "
        "forces the narrow integrate exception"
    )
    assert "narrow exception" in lowered or "single narrow exception" in lowered

    # It records that the verify-then-integrate floor is preserved.
    assert (
        "floor is preserved" in lowered
        or "floor holds" in lowered
        or ("verify-then-integrate floor is preserved" in lowered)
    ), "ADR-0005 must state the inviolable floor is preserved"


def test_adr0001_header_notes_the_adr0005_amendment() -> None:
    text = (REPO_ROOT / "docs" / "adr" / "0001-orchestrate-control-model.md").read_text(
        encoding="utf-8"
    )
    assert "Amended by [ADR-0005]" in text, (
        "ADR-0001's header must cross-reference the ADR-0005 amendment"
    )


# --- mid-run milestone heartbeat + the reporter role (issue #48) --------------

# Every canonical milestone-comment template SKILL.md tells the reporter to post,
# each paired with the concrete-value substitution that must round-trip through
# `parse_landed_marker` — so the documented grammar can never drift from the code.
MILESTONE_TEMPLATES: list[tuple[str, dict[str, str], str]] = [
    ("orchestrate: started #<n>, run <runId>", {"<n>": "47"}, "started"),
    (
        "orchestrate: implementation green #<n>, run <runId>",
        {"<n>": "47"},
        "implementation-green",
    ),
    (
        "orchestrate: verification cleared #<n>, run <runId>",
        {"<n>": "47"},
        "verification-cleared",
    ),
    (
        "orchestrate: fix round <k> #<n>, run <runId>",
        {"<k>": "2", "<n>": "47"},
        "fix-round",
    ),
    (
        "orchestrate: parked #<n> (<reason>), run <runId>",
        {"<n>": "47", "<reason>": "cap hit"},
        "parked",
    ),
]


def test_skill_documents_the_milestone_templates_that_round_trip() -> None:
    # The SKILL↔parser consistency test, extended to the #48 milestone verbs: each
    # canonical template must appear verbatim in SKILL.md and, with concrete values
    # substituted, round-trip through the single-source-of-truth parser.
    text = _skill_text()
    for template, substitutions, expected_verb in MILESTONE_TEMPLATES:
        assert template in text, (
            f"SKILL.md must document the canonical milestone template verbatim: "
            f"{template!r}"
        )
        concrete = template.replace("<runId>", "wf_consistency")
        for token, value in substitutions.items():
            concrete = concrete.replace(token, value)
        parsed = orchestrate.parse_landed_marker(concrete)
        assert parsed is not None and parsed.verb == expected_verb, (
            f"the milestone template SKILL tells the reporter to post must "
            f"round-trip through parse_landed_marker: {template!r}"
        )
        # The hard #49 non-regression, documented and enforced together: a
        # milestone verb is never a landed marker and carries no SHA.
        assert parsed.verb != "landed" and parsed.sha is None


def test_skill_documents_the_reporter_role_in_the_lifecycle() -> None:
    text = _skill_text().lower()
    assert "reporter" in text, (
        "SKILL.md must introduce the reporter sub-agent in the lifecycle"
    )
    # It is mechanical-tier and comment-only — never a mutator.
    assert "mechanical" in text and "comment-only" in text, (
        "SKILL.md must describe the reporter as a mechanical-tier, comment-only writer"
    )


def test_skill_operating_contract_names_two_authorized_writers() -> None:
    section = _operating_contract_section().lower()
    # The widened operating-contract bullet: two authorized outward writers now —
    # integrate (mutating) and the reporter (comment-only).
    assert "reporter" in section, (
        "the operating contract must name the reporter as the second authorized writer"
    )
    assert "comment-only" in section or "comment only" in section, (
        "the operating contract must state the reporter's write is comment-only"
    )
    assert "integrate" in section, (
        "the operating contract must still name integrate as the mutating writer"
    )


def test_skill_documents_out_of_band_progress_watching() -> None:
    text = _skill_text().lower()
    assert "out-of-band" in text or "out of band" in text, (
        "SKILL.md must document watching progress out of band"
    )
    # Watch the issue comments / GitHub notifications — never the TUI.
    assert (
        "notification" in text
        or "issue's comments" in text
        or "comment timeline" in text
    ), "SKILL.md must point the maintainer at the issue comments / notifications"


# --- ADR-0006 (issue #48) -----------------------------------------------------

ADR_0006_GLOB = "0006-*.md"


def _adr0006_path() -> Path:
    matches = sorted((REPO_ROOT / "docs" / "adr").glob(ADR_0006_GLOB))
    assert matches, "ADR-0006 (docs/adr/0006-*.md) must exist"
    return matches[0]


def test_adr0006_exists_and_records_the_reporter_decision() -> None:
    text = _adr0006_path().read_text(encoding="utf-8")
    lowered = text.lower()

    # Title: mid-run milestone heartbeat and the reporter writer role.
    assert "heartbeat" in lowered and "reporter" in lowered, (
        "ADR-0006's title/body must name the mid-run heartbeat and the reporter role"
    )

    # It amends ADR-0005 §3 and ADR-0001 §7 — a second, strictly weaker writer.
    assert "adr-0005" in lowered and "§3" in text, (
        "ADR-0006 must name that it amends ADR-0005 §3"
    )
    assert "§7" in text, "ADR-0006 must name ADR-0001 §7 as amended"
    assert "second" in lowered and ("weaker" in lowered or "comment-only" in lowered), (
        "ADR-0006 must record a second, strictly weaker (comment-only) writer"
    )

    # The three decisions: the milestone vocabulary, the reporter role, and the
    # boundary of the exception (integrate stays the sole mutating writer).
    assert "vocabulary" in lowered or "milestone verb" in lowered, (
        "ADR-0006 must record the milestone-vocabulary decision"
    )
    assert "sole" in lowered and "mutat" in lowered, (
        "ADR-0006 must record that integrate remains the sole mutating writer"
    )
    # The §7 floor is preserved — the reporter never closes.
    assert (
        "never close" in lowered
        or "reporter never" in lowered
        or ("floor" in lowered and "reporter" in lowered)
    ), "ADR-0006 must record that the §7 floor holds — the reporter never closes"


def test_adr0001_header_notes_the_adr0006_amendment() -> None:
    text = (REPO_ROOT / "docs" / "adr" / "0001-orchestrate-control-model.md").read_text(
        encoding="utf-8"
    )
    assert "Amended by [ADR-0006]" in text, (
        "ADR-0001's header must cross-reference the ADR-0006 amendment"
    )


def test_adr0005_header_notes_the_adr0006_amendment() -> None:
    text = (
        REPO_ROOT
        / "docs"
        / "adr"
        / "0005-durable-landed-markers-and-close-at-integrate.md"
    ).read_text(encoding="utf-8")
    assert "ADR-0006" in text, (
        "ADR-0005 must cross-reference ADR-0006, which widens its §3 to a second writer"
    )


def test_skill_documents_status_one_liner_with_state_all() -> None:
    """The out-of-band progress-watching section documents the `status` one-liner
    and its `watch` variant. Both MUST pass `--state all` — merge mode closes each
    landed issue, so the default `--state open` would silently drop every `done`
    row — and select `number,comments` (issue #50)."""

    text = _skill_text()
    lowered = text.lower()

    # The `orchestrate.py status` invocation, tolerating the repo's quoted
    # plugin-root form (`orchestrate.py" status`) between script and subcommand.
    status_invocation = re.compile(r"orchestrate\.py\"?\s+status")

    # The `status` subcommand is documented.
    assert status_invocation.search(text), (
        "SKILL.md must document the `status` subcommand"
    )

    # The documented `gh issue list` feeding `status` must carry `--state all` and
    # request the comments the board reads back — a one-liner without `--state all`
    # can never render a `done` row in merge mode.
    status_pipes = [
        line
        for line in text.splitlines()
        if status_invocation.search(line) and "gh issue list" in line
    ]
    assert status_pipes, (
        "SKILL.md must document a `gh issue list ... | ... orchestrate.py status` one-liner"
    )
    for line in status_pipes:
        assert "--state all" in line, (
            "the status one-liner/watch variant must pass --state all"
        )
        assert "number,comments" in line, (
            "the status one-liner must request --json number,comments"
        )

    # The live `watch` variant is documented — anchored to an actual `watch`
    # wrapper around a `status` invocation on one line, not merely the word
    # "watch" appearing somewhere in prose (the heartbeat section already says
    # "watch the run from your phone"), so deleting the `watch -n 60 '… status'`
    # one-liner fails here rather than passing on unrelated prose.
    watch_invocation = re.compile(r"watch\b[^\n]*orchestrate\.py\"?\s+status")
    assert watch_invocation.search(text), (
        "SKILL.md must document the `watch` live-view variant of `status`"
    )

    # The first-page comment-page cap is noted, with the per-issue fallback.
    assert "gh issue view" in text and ("100" in text or "first page" in lowered), (
        "SKILL.md must note the ~100-comment first-page cap and the "
        "`gh issue view <n> --comments` fallback"
    )
