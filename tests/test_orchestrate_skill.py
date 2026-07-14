"""Structural tests for the orchestrate SKILL.md guidance (issues #19, #24, #25, #28).

These read ``skills/orchestrate/SKILL.md`` as text and assert several things the
skill's prose must carry — among them (issues #19/#24):

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
    """The '## The operating contract' section, up to '## Flow'."""

    return _section(_skill_text(), r"^##\s+The operating contract", r"^##\s+Flow")


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
