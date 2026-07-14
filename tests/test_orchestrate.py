"""Tests for the deterministic mechanics in scripts/orchestrate.py.

The helper is a single-file `uv run` script under scripts/, not an installed
package, so it is loaded by path. The tests cover the error-prone parts the
script exists to make reliable: parsing the issue contract, the dependency
graph and its waves, the red-before-green structural check, and the report
rendering — exactly the logic that would otherwise be done by hand each run.

Run with: `uv run --with pytest pytest -q`
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

# The path to the standalone script under test, used both to load it by path and
# to exercise its real CLI through a subprocess (the `plan` argument parsing).
SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "orchestrate.py"

# Load scripts/orchestrate.py by path, since it is a standalone script rather
# than an importable package. Register it in sys.modules before executing so
# its @dataclass decorators can resolve their own module during class creation.
_spec = importlib.util.spec_from_file_location("orchestrate", SCRIPT)
assert _spec is not None and _spec.loader is not None
orchestrate = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = orchestrate
_spec.loader.exec_module(orchestrate)

Issue = orchestrate.Issue
Commit = orchestrate.Commit
Verdict = orchestrate.Verdict


def issue(number: int, blocked_by: set[int] | None = None, labels=None) -> object:
    """Build an Issue with sensible defaults for graph tests."""

    return Issue(
        number=number,
        title=f"Issue {number}",
        labels=labels or [],
        blocked_by=blocked_by or set(),
    )


# --- parse_blocked_by ---------------------------------------------------------


def test_parse_blocked_by_reads_a_single_reference() -> None:
    assert orchestrate.parse_blocked_by("## Blocked by\n\n- #42") == {42}


def test_parse_blocked_by_reads_multiple_references_including_prose() -> None:
    body = "## Blocked by\n\n- #42\n- depends on #43"
    assert orchestrate.parse_blocked_by(body) == {42, 43}


def test_parse_blocked_by_treats_none_as_no_dependencies() -> None:
    assert (
        orchestrate.parse_blocked_by("## Blocked by\n\nNone - can start immediately")
        == set()
    )


def test_parse_blocked_by_returns_empty_when_section_absent() -> None:
    assert orchestrate.parse_blocked_by("## What to build\n\nA thing.") == set()


def test_parse_blocked_by_stops_at_the_next_heading() -> None:
    body = "## Blocked by\n\n- #1\n\n## Notes\n\nSee #999 for context."
    assert orchestrate.parse_blocked_by(body) == {1}


def test_parse_blocked_by_reads_an_inline_label_without_a_heading() -> None:
    # An inline `**Depends on:** #44` with no `## Blocked by` heading anywhere
    # must still produce the edge (the core regression this issue fixes).
    assert orchestrate.parse_blocked_by("Some prose.\n\n**Depends on:** #44") == {44}


def test_parse_blocked_by_keeps_see_under_notes_a_non_edge() -> None:
    # "See #999" under a Notes heading is a soft reference, never a hard edge.
    body = "## Notes\n\nSee #999 for context. It relates to #888."
    assert orchestrate.parse_blocked_by(body) == set()


# --- parse_dependencies (hard edges with provenance + soft notes) -------------


def test_parse_dependencies_inline_label_yields_edge_with_origin() -> None:
    signals = orchestrate.parse_dependencies("**Depends on:** #44")
    assert signals.edges == {44: "Depends on"}
    assert signals.soft_notes == []


def test_parse_dependencies_blocked_by_single_line_yields_both_edges() -> None:
    signals = orchestrate.parse_dependencies("Blocked by: #44, #45")
    assert signals.edges == {44: "Blocked by", 45: "Blocked by"}


def test_parse_dependencies_label_then_bullet_list_yields_one_edge_each() -> None:
    body = "**Depends on:**\n\n- #44\n- #45\n- #46"
    signals = orchestrate.parse_dependencies(body)
    assert signals.edges == {44: "Depends on", 45: "Depends on", 46: "Depends on"}


def test_parse_dependencies_recognises_every_hard_keyword() -> None:
    body = "Depends upon #1.\nRequires #2.\nNeeds #3.\nBlocked by #4.\nDepends on #5.\n"
    signals = orchestrate.parse_dependencies(body)
    assert signals.edges == {
        1: "Depends upon",
        2: "Requires",
        3: "Needs",
        4: "Blocked by",
        5: "Depends on",
    }


def test_parse_dependencies_heading_section_still_works() -> None:
    body = "## Blocked by\n\n- #42\n\n## Notes\n\nSee #999."
    signals = orchestrate.parse_dependencies(body)
    assert signals.edges == {42: "Blocked by"}


def test_parse_dependencies_keeps_relates_to_a_soft_note_not_an_edge() -> None:
    signals = orchestrate.parse_dependencies("Relates to #44.")
    assert signals.edges == {}
    assert any("#44" in note for note in signals.soft_notes)


def test_parse_dependencies_keeps_same_files_a_soft_note_not_an_edge() -> None:
    signals = orchestrate.parse_dependencies("This touches the same files as #56.")
    assert signals.edges == {}
    assert any("#56" in note for note in signals.soft_notes)


def test_parse_dependencies_ignores_a_self_reference() -> None:
    # A self-reference cannot be a blocker; the caller passes its own number.
    signals = orchestrate.parse_dependencies("Depends on #7.", self_number=7)
    assert signals.edges == {}


def test_parse_dependencies_see_only_is_neither_edge_nor_note() -> None:
    # Bare "See #999" (not "See also") is the pre-existing Notes-section case; it
    # must remain a non-edge and must not pollute the soft-note list either.
    signals = orchestrate.parse_dependencies("## Notes\n\nSee #999 for context.")
    assert signals.edges == {}
    assert signals.soft_notes == []


# --- parse_dependencies: a keyword governs only its own clause -----------------
#
# These pin the AC's "NO edge for a soft phrase" criterion against the form
# triage actually emits: a directional keyword and a soft phrase in separate
# sentences on the SAME line. The keyword must claim only the refs in its own
# clause; the soft phrase's ref must be a soft note and never a hard edge.


def test_parse_dependencies_soft_phrase_after_a_keyword_on_one_line_is_not_an_edge() -> (
    None
):
    signals = orchestrate.parse_dependencies("Depends on #45. Relates to #44.")
    assert signals.edges == {45: "Depends on"}
    assert any("#44" in note for note in signals.soft_notes)


def test_parse_dependencies_bold_label_then_soft_phrase_on_one_line() -> None:
    body = "**Depends on:** #44 (schema). Relates to #46 for context."
    signals = orchestrate.parse_dependencies(body)
    assert signals.edges == {44: "Depends on"}
    assert any("#46" in note for note in signals.soft_notes)


def test_parse_dependencies_see_also_after_blocked_by_on_one_line_is_not_an_edge() -> (
    None
):
    signals = orchestrate.parse_dependencies(
        "Blocked by #44 and #45. See also the discussion in #12."
    )
    assert signals.edges == {44: "Blocked by", 45: "Blocked by"}
    assert 12 not in signals.edges


def test_parse_dependencies_same_files_after_requires_on_one_line_is_not_an_edge() -> (
    None
):
    # The literal Agent Brief example: "touches the same files as #N" is NEVER an
    # edge, even when a hard keyword shares the line.
    signals = orchestrate.parse_dependencies(
        "Requires #1. Touches the same files as #2."
    )
    assert signals.edges == {1: "Requires"}
    assert 2 not in signals.edges
    assert any("#2" in note for note in signals.soft_notes)


def test_parse_dependencies_two_hard_keywords_on_one_line_keep_their_own_origin() -> (
    None
):
    # Each keyword governs its own clause, so #2's provenance is its real origin.
    signals = orchestrate.parse_dependencies("Depends on #1, requires #2 too.")
    assert signals.edges == {1: "Depends on", 2: "Requires"}


# --- parse_dependencies: a bare keyword reaches onto the next prose line --------
#
# When a directional keyword ends its own line with no ref (the label sits alone
# and the `#N` is on the next line as plain prose, not a bullet), the keyword's
# authority still reaches the immediately following non-blank line. This is the
# conservative direction issue #10 asks for: a missed edge is the bug. The reach
# is bounded by the same clause boundary as the same-line scan, so a soft phrase
# or a sentence break on the next line does not get absorbed.


def test_parse_dependencies_keyword_then_prose_ref_on_next_line_yields_edge() -> None:
    signals = orchestrate.parse_dependencies("Depends on\nthe #44 schema.")
    assert signals.edges == {44: "Depends on"}


def test_parse_dependencies_bare_keyword_next_line_stops_at_clause_boundary() -> None:
    # The keyword's reach onto the next line is its own clause only: #44 is the
    # edge, but the soft phrase after the sentence break stays a soft note.
    signals = orchestrate.parse_dependencies("Depends on\n#44. Relates to #46.")
    assert signals.edges == {44: "Depends on"}
    assert any("#46" in note for note in signals.soft_notes)


def test_parse_dependencies_keyword_with_same_line_ref_ignores_next_prose_line() -> (
    None
):
    # When the keyword's own line already carries a ref, the next prose line is
    # unrelated content and must not be absorbed (the "stop at the first
    # non-bullet line" guarantee for the satisfied case).
    signals = orchestrate.parse_dependencies("Depends on #44.\nUnrelated #99 mention.")
    assert signals.edges == {44: "Depends on"}


# --- parse_dependencies: keyword needs a word boundary ------------------------
#
# A hard keyword embedded in a longer word (prerequires, misrequires) must not
# mint a spurious edge — only a standalone keyword counts.


def test_parse_dependencies_keyword_inside_a_larger_word_is_not_an_edge() -> None:
    assert orchestrate.parse_dependencies("Misrequires #6.").edges == {}
    assert orchestrate.parse_dependencies("prerequires #3.").edges == {}


# --- parse_dependencies: heading section is the only source for some refs ------


def test_parse_dependencies_heading_inline_keyword_keeps_its_specific_origin() -> None:
    # `## Blocked by\n\n- depends on #43`: the more-specific inline keyword wins,
    # so the recorded provenance is "Depends on", not the heading's "Blocked by"
    # (the behaviour parse_dependencies' own comment promises).
    signals = orchestrate.parse_dependencies("## Blocked by\n\n- depends on #43")
    assert signals.edges == {43: "Depends on"}


def test_parse_dependencies_heading_section_recovers_a_prose_only_ref() -> None:
    # A ref that sits in a prose paragraph under `## Blocked by` — no bullet, no
    # directional keyword — is reachable ONLY by BLOCKED_BY_SECTION_RE; the inline
    # scanner stops at the first non-bullet line. This binds the regression AC to
    # the heading-specific code so deleting it is caught.
    signals = orchestrate.parse_dependencies(
        "## Blocked by\n\nThe migration in #77 must merge first."
    )
    assert signals.edges == {77: "Blocked by"}


# --- load_issues --------------------------------------------------------------


def test_load_issues_reads_nested_label_objects() -> None:
    raw = '[{"number":1,"title":"A","labels":[{"name":"ready-for-agent"}],"body":""}]'
    issues = orchestrate.load_issues(raw)
    assert issues[0].labels == ["ready-for-agent"]


def test_load_issues_rejects_a_missing_number() -> None:
    with pytest.raises(ValueError, match="number"):
        orchestrate.load_issues('[{"title":"A"}]')


def test_load_issues_rejects_malformed_json() -> None:
    with pytest.raises(ValueError, match="valid JSON"):
        orchestrate.load_issues("not json")


def test_load_issues_rejects_a_non_array() -> None:
    with pytest.raises(ValueError, match="array"):
        orchestrate.load_issues('{"number":1}')


def test_load_issues_derives_an_inline_edge_with_provenance() -> None:
    raw = (
        '[{"number":45,"title":"B","labels":[],'
        '"body":"**Depends on:** #44 (schema first)."}]'
    )
    issues = orchestrate.load_issues(raw)
    assert issues[0].blocked_by == {44}
    assert issues[0].blocked_by_origin == {44: "Depends on"}


def test_load_issues_ignores_a_self_referencing_dependency() -> None:
    raw = '[{"number":7,"title":"C","labels":[],"body":"Depends on #7."}]'
    issues = orchestrate.load_issues(raw)
    assert issues[0].blocked_by == set()


def test_load_issues_collects_soft_notes() -> None:
    raw = (
        '[{"number":8,"title":"D","labels":[],'
        '"body":"Relates to #44. Touches the same files as #56."}]'
    )
    issues = orchestrate.load_issues(raw)
    assert issues[0].blocked_by == set()
    assert any("#44" in note for note in issues[0].soft_notes)
    assert any("#56" in note for note in issues[0].soft_notes)


# --- parse_dependencies: prose-title resolution ------------------------------
#
# A prerequisite named by its exact prose title (no `#N`) must resolve to an
# edge, but only inside a dependency region. Resolution needs the caller to pass
# a normalised title -> number map, because one body cannot know the other
# issues' titles on its own.


def test_parse_dependencies_resolves_a_prose_title_within_blocked_by() -> None:
    index = {"user schema migration": 44}
    signals = orchestrate.parse_dependencies(
        "## Blocked by\n\n- User schema migration", title_index=index
    )
    assert signals.edges == {44: "Blocked by"}
    assert signals.warnings == []


def test_parse_dependencies_resolves_a_prose_title_prose_line_within_blocked_by() -> (
    None
):
    # A title in a plain prose paragraph (no bullet) under the heading resolves.
    index = {"user schema migration": 44}
    signals = orchestrate.parse_dependencies(
        "## Blocked by\n\nUser schema migration.", title_index=index
    )
    assert signals.edges == {44: "Blocked by"}


def test_parse_dependencies_resolves_a_prose_title_after_an_inline_label() -> None:
    # A bold inline label followed by a prose title resolves, attributed to the
    # inline keyword rather than the heading form.
    index = {"user schema migration": 44}
    signals = orchestrate.parse_dependencies(
        "**Depends on:** User schema migration", title_index=index
    )
    assert signals.edges == {44: "Depends on"}


def test_parse_dependencies_mixes_titles_and_numbers_without_duplicates() -> None:
    # A section naming one prerequisite by title and another by `#N` resolves
    # both; naming the SAME prerequisite twice yields exactly one edge.
    index = {"user schema migration": 44}
    signals = orchestrate.parse_dependencies(
        "## Blocked by\n\n- User schema migration\n- #44\n- #46", title_index=index
    )
    assert signals.edges == {44: "Blocked by", 46: "Blocked by"}


def test_parse_dependencies_does_not_match_a_title_outside_dependency_regions() -> None:
    # The same title mentioned under an unrelated heading is NOT a dependency.
    index = {"user schema migration": 44}
    signals = orchestrate.parse_dependencies(
        "## Notes\n\nThe User schema migration is elegant.", title_index=index
    )
    assert signals.edges == {}


def test_parse_dependencies_does_not_match_a_bare_prose_keyword_title() -> None:
    # A hard keyword used as an ordinary verb ("needs review") is not a label,
    # so a stray title-shaped clause after it must not mint an edge.
    index = {"review": 44}
    signals = orchestrate.parse_dependencies(
        "This work needs review before shipping.", title_index=index
    )
    assert signals.edges == {}


# --- parse_dependencies: unresolved-region warning ----------------------------


def test_parse_dependencies_warns_when_blocked_by_resolves_to_zero() -> None:
    signals = orchestrate.parse_dependencies(
        "## Blocked by\n\n- Some prerequisite that does not exist", title_index={}
    )
    assert signals.edges == {}
    assert signals.warnings != []


def test_parse_dependencies_does_not_warn_for_none_can_start_immediately() -> None:
    signals = orchestrate.parse_dependencies(
        "## Blocked by\n\nNone - can start immediately.", title_index={}
    )
    assert signals.warnings == []


def test_parse_dependencies_does_not_warn_when_a_number_reference_resolves() -> None:
    signals = orchestrate.parse_dependencies("## Blocked by\n\n- #42", title_index={})
    assert signals.warnings == []


# --- parse_dependencies: title resolves a number no #N supplies (AC #2) --------
#
# These distinguish "title resolved" from "title ignored": the title maps to a
# number that is NOT otherwise present as `#N` in the same region, so the edge
# exists ONLY because title resolution ran. They fail if that resolution is cut.


def test_parse_dependencies_title_supplies_a_number_absent_as_a_reference() -> None:
    index = {"user schema migration": 44}
    signals = orchestrate.parse_dependencies(
        "## Blocked by\n\n- User schema migration\n- #46", title_index=index
    )
    assert signals.edges == {44: "Blocked by", 46: "Blocked by"}


def test_load_issues_title_only_and_number_ref_yield_both_distinct_edges() -> None:
    raw = (
        '[{"number":44,"title":"User schema migration","labels":[],"body":""},'
        '{"number":46,"title":"Widget API","labels":[],"body":""},'
        '{"number":45,"title":"Eval","labels":[],'
        '"body":"## Blocked by\\n\\n- User schema migration\\n- #46"}]'
    )
    issues = orchestrate.load_issues(raw)
    by_number = {i.number: i for i in issues}
    assert by_number[45].blocked_by == {44, 46}


# --- parse_dependencies: only a genuine label resolves a prose title -----------
#
# A prose title resolves after a genuine label (bold-wrapped or colon-bearing)
# but NOT after a bare keyword used as an ordinary verb, even at body start.
# Bare `#N` extraction is unchanged regardless of the label shape.


def test_parse_dependencies_colon_label_resolves_a_prose_title() -> None:
    index = {"user schema migration": 44}
    signals = orchestrate.parse_dependencies(
        "Depends on: User schema migration", title_index=index
    )
    assert signals.edges == {44: "Depends on"}


def test_parse_dependencies_bold_label_resolves_a_prose_title() -> None:
    index = {"user schema migration": 44}
    signals = orchestrate.parse_dependencies(
        "**Depends on** User schema migration", title_index=index
    )
    assert signals.edges == {44: "Depends on"}


def test_parse_dependencies_body_start_bare_keyword_title_is_not_an_edge() -> None:
    # A hard keyword at absolute body start, with no bold and no colon, is not a
    # label; a following clause equal to a title must not mint an edge.
    assert (
        orchestrate.parse_dependencies(
            "Requires review", title_index={"review": 44}
        ).edges
        == {}
    )
    assert (
        orchestrate.parse_dependencies(
            "Needs\nUser schema migration", title_index={"user schema migration": 44}
        ).edges
        == {}
    )


def test_parse_dependencies_bare_line_initial_number_still_resolves() -> None:
    # Bare `#N` extraction is untouched by the label rule.
    signals = orchestrate.parse_dependencies("Depends on #44", title_index={})
    assert signals.edges == {44: "Depends on"}


# --- parse_dependencies: an unresolved inline label warns too -----------------
#
# The unresolved-region warning is not limited to the `## Blocked by` heading:
# a genuine inline label (bold/colon) that resolves to nothing warns as well. A
# resolved label is quiet, and a plain prose keyword (no label) never warns.


def test_parse_dependencies_warns_on_an_unresolvable_inline_label() -> None:
    signals = orchestrate.parse_dependencies(
        "**Depends on:** unknown prerequisite name", title_index={}
    )
    assert signals.edges == {}
    assert signals.warnings != []


def test_parse_dependencies_does_not_warn_when_an_inline_label_resolves() -> None:
    signals = orchestrate.parse_dependencies("**Depends on:** #44", title_index={})
    assert signals.edges == {44: "Depends on"}
    assert signals.warnings == []


def test_parse_dependencies_does_not_warn_for_a_plain_prose_keyword() -> None:
    signals = orchestrate.parse_dependencies(
        "This work needs careful review.", title_index={}
    )
    assert signals.edges == {}
    assert signals.warnings == []


def test_build_plan_warns_on_an_unresolved_inline_label() -> None:
    raw = (
        '[{"number":45,"title":"Eval","labels":[],'
        '"body":"**Depends on:** some prerequisite not tracked here"}]'
    )
    issues = orchestrate.load_issues(raw)
    plan = orchestrate.build_plan(issues, [], "ready-for-agent")
    assert any("45" in warning for warning in plan["warnings"])


# --- load_issues: prose-title resolution across the in-scope set ---------------


def test_load_issues_resolves_a_prose_title_blocked_by_to_an_edge() -> None:
    raw = (
        '[{"number":44,"title":"User schema migration","labels":[],"body":""},'
        '{"number":45,"title":"Eval","labels":[],'
        '"body":"## Blocked by\\n\\nUser schema migration."}]'
    )
    issues = orchestrate.load_issues(raw)
    by_number = {i.number: i for i in issues}
    assert by_number[45].blocked_by == {44}
    assert by_number[45].blocked_by_origin == {44: "Blocked by"}


def test_load_issues_resolves_mixed_title_and_number_without_duplicate_edges() -> None:
    raw = (
        '[{"number":44,"title":"User schema migration","labels":[],"body":""},'
        '{"number":45,"title":"Eval","labels":[],'
        '"body":"## Blocked by\\n\\n- User schema migration\\n- #44"}]'
    )
    issues = orchestrate.load_issues(raw)
    by_number = {i.number: i for i in issues}
    assert by_number[45].blocked_by == {44}


def test_load_issues_ignores_a_title_mentioned_outside_dependency_regions() -> None:
    raw = (
        '[{"number":44,"title":"User schema migration","labels":[],"body":""},'
        '{"number":45,"title":"Eval","labels":[],'
        '"body":"## What to build\\n\\nBuild on the User schema migration approach.'
        '\\n\\n## Blocked by\\n\\nNone - can start immediately."}]'
    )
    issues = orchestrate.load_issues(raw)
    by_number = {i.number: i for i in issues}
    assert by_number[45].blocked_by == set()


# --- build_plan: prose-title edges and warnings -------------------------------


def test_build_plan_resolves_a_prose_blocked_by_title_to_an_edge() -> None:
    raw = (
        '[{"number":44,"title":"User schema migration","labels":[],"body":"Base."},'
        '{"number":45,"title":"Eval harness","labels":[],'
        '"body":"## Blocked by\\n\\n- User schema migration"}]'
    )
    issues = orchestrate.load_issues(raw)
    plan = orchestrate.build_plan(issues, [], "ready-for-agent")
    assert {"from": 45, "to": 44, "origin": "Blocked by"} in plan["dependency_edges"]
    assert plan["waves"] == [[44], [45]]
    assert plan["merge_required"] is True


def test_build_plan_dedupes_a_prerequisite_named_by_title_and_number() -> None:
    raw = (
        '[{"number":44,"title":"User schema migration","labels":[],"body":"Base."},'
        '{"number":45,"title":"Eval","labels":[],'
        '"body":"## Blocked by\\n\\n- User schema migration\\n- #44"}]'
    )
    issues = orchestrate.load_issues(raw)
    plan = orchestrate.build_plan(issues, [], "ready-for-agent")
    edges = [e for e in plan["dependency_edges"] if e["from"] == 45 and e["to"] == 44]
    assert len(edges) == 1


def test_build_plan_warns_when_a_blocked_by_section_resolves_to_zero() -> None:
    raw = (
        '[{"number":45,"title":"Eval","labels":[],'
        '"body":"## Blocked by\\n\\n- Some prerequisite that is not an issue"}]'
    )
    issues = orchestrate.load_issues(raw)
    plan = orchestrate.build_plan(issues, [], "ready-for-agent")
    assert "warnings" in plan
    assert any("45" in warning for warning in plan["warnings"])


def test_build_plan_has_no_warnings_when_every_dependency_resolves() -> None:
    raw = (
        '[{"number":44,"title":"User schema migration","labels":[],"body":"Base."},'
        '{"number":45,"title":"Eval","labels":[],'
        '"body":"## Blocked by\\n\\n- User schema migration"}]'
    )
    issues = orchestrate.load_issues(raw)
    plan = orchestrate.build_plan(issues, [], "ready-for-agent")
    assert plan["warnings"] == []


# --- build_plan ---------------------------------------------------------------


def test_build_plan_multi_waves_a_coupled_set_from_inline_deps() -> None:
    raw = (
        '[{"number":44,"title":"Schema","labels":[],"body":"Foundational."},'
        '{"number":45,"title":"Eval","labels":[],'
        '"body":"**Depends on:** #44 (the schema)."}]'
    )
    issues = orchestrate.load_issues(raw)
    plan = orchestrate.build_plan(issues, [], "ready-for-agent")
    assert plan["waves"] == [[44], [45]]


def test_build_plan_records_edge_provenance() -> None:
    raw = (
        '[{"number":44,"title":"Schema","labels":[],"body":"Foundational."},'
        '{"number":45,"title":"Eval","labels":[],"body":"Depends on #44."}]'
    )
    issues = orchestrate.load_issues(raw)
    plan = orchestrate.build_plan(issues, [], "ready-for-agent")
    assert {"from": 45, "to": 44, "origin": "Depends on"} in plan["dependency_edges"]


def test_build_plan_flags_merge_required_when_any_edge_exists() -> None:
    raw = (
        '[{"number":44,"title":"Schema","labels":[],"body":"Foundational."},'
        '{"number":45,"title":"Eval","labels":[],"body":"Depends on #44."}]'
    )
    issues = orchestrate.load_issues(raw)
    plan = orchestrate.build_plan(issues, [], "ready-for-agent")
    assert plan["merge_required"] is True


def test_build_plan_does_not_flag_merge_for_independent_issues() -> None:
    raw = (
        '[{"number":1,"title":"A","labels":[],"body":"Standalone."},'
        '{"number":2,"title":"B","labels":[],"body":"Standalone."}]'
    )
    issues = orchestrate.load_issues(raw)
    plan = orchestrate.build_plan(issues, [], "ready-for-agent")
    assert plan["merge_required"] is False
    assert plan["dependency_edges"] == []


def test_build_plan_surfaces_soft_notes() -> None:
    raw = (
        '[{"number":1,"title":"A","labels":[],'
        '"body":"Touches the same files as #2."},'
        '{"number":2,"title":"B","labels":[],"body":"Standalone."}]'
    )
    issues = orchestrate.load_issues(raw)
    plan = orchestrate.build_plan(issues, [], "ready-for-agent")
    assert any(
        note["number"] == 1 and "#2" in note["note"] for note in plan["soft_notes"]
    )


def test_build_plan_keeps_existing_top_level_fields() -> None:
    # Backward compatibility: the Workflow engine consumes these keys as args.
    raw = '[{"number":1,"title":"A","labels":[],"body":"Standalone."}]'
    issues = orchestrate.load_issues(raw)
    plan = orchestrate.build_plan(issues, [], "ready-for-agent")
    for key in ("scope_label", "issues", "waves", "external_dependencies", "excluded"):
        assert key in plan


# --- missing Agent Brief fallback flag (issue #18) ----------------------------
#
# The plan must flag each in-scope issue that carries no Agent Brief comment, so
# a run knows which issues are built from their body + acceptance criteria rather
# than a posted brief. An issue HAS a brief iff a comment body carries a Markdown
# "Agent Brief" HEADING (`^#{1,6}\s*Agent Brief`, case-insensitive) — anchoring
# to the heading form the real briefs use, so a prose mention ("no Agent Brief
# was posted") does not falsely suppress the flag. gh returns `comments` as a
# list of {"body": ...} objects; bare strings are tolerated, and an absent
# `comments` field is treated as no detectable brief (the fallback still copes).


def test_load_issues_flags_issue_with_agent_brief_comment() -> None:
    raw = (
        '[{"number":1,"title":"A","labels":[],"body":"Do a thing.",'
        '"comments":[{"body":"## Agent Brief\\n\\nBuild the widget."}]}]'
    )
    issues = orchestrate.load_issues(raw)
    assert issues[0].no_brief is False


def test_load_issues_flags_issue_with_comments_but_no_brief() -> None:
    raw = (
        '[{"number":2,"title":"B","labels":[],"body":"Do a thing.",'
        '"comments":[{"body":"Just a plain discussion comment."}]}]'
    )
    issues = orchestrate.load_issues(raw)
    assert issues[0].no_brief is True


def test_load_issues_treats_absent_comments_as_no_brief() -> None:
    raw = '[{"number":3,"title":"C","labels":[],"body":"Do a thing."}]'
    issues = orchestrate.load_issues(raw)
    assert issues[0].no_brief is True


def test_load_issues_tolerates_bare_string_comments() -> None:
    raw = (
        '[{"number":4,"title":"D","labels":[],"body":"x",'
        '"comments":["## Agent Brief\\n\\nbuild it"]}]'
    )
    issues = orchestrate.load_issues(raw)
    assert issues[0].no_brief is False


def test_load_issues_brief_detection_is_case_insensitive() -> None:
    raw = (
        '[{"number":5,"title":"E","labels":[],"body":"x",'
        '"comments":[{"body":"## agent brief\\n\\nfollows below"}]}]'
    )
    issues = orchestrate.load_issues(raw)
    assert issues[0].no_brief is False


def test_load_issues_prose_mention_of_agent_brief_is_still_flagged() -> None:
    # A comment that merely MENTIONS "agent brief" in prose — with no heading — is
    # NOT a brief; the issue stays flagged no_brief. This is the false-positive the
    # heading anchor closes: substring matching would wrongly clear it.
    raw = (
        '[{"number":9,"title":"F","labels":[],"body":"x",'
        '"comments":[{"body":"Note: no Agent Brief was posted for this issue."}]}]'
    )
    issues = orchestrate.load_issues(raw)
    assert issues[0].no_brief is True


def test_load_issues_agent_brief_heading_comment_is_not_flagged() -> None:
    # A genuine `## Agent Brief` heading comment marks the issue as having a brief.
    raw = (
        '[{"number":10,"title":"G","labels":[],"body":"x",'
        '"comments":[{"body":"## Agent Brief\\n\\nBuild it, test-first."}]}]'
    )
    issues = orchestrate.load_issues(raw)
    assert issues[0].no_brief is False


def test_build_plan_surfaces_no_brief_per_issue_and_top_level() -> None:
    raw = (
        '[{"number":1,"title":"Has brief","labels":[],"body":"x",'
        '"comments":[{"body":"## Agent Brief\\n\\nhere"}]},'
        '{"number":2,"title":"No brief","labels":[],"body":"y",'
        '"comments":[{"body":"just chatter"}]},'
        '{"number":3,"title":"No comments","labels":[],"body":"z"}]'
    )
    issues = orchestrate.load_issues(raw)
    plan = orchestrate.build_plan(issues, [], "ready-for-agent")

    # Per-issue flag: false only for the issue that actually carries a brief.
    by_number = {i["number"]: i for i in plan["issues"]}
    assert by_number[1]["no_brief"] is False
    assert by_number[2]["no_brief"] is True
    assert by_number[3]["no_brief"] is True

    # Convenience top-level list of the numbers lacking a brief, sorted.
    assert plan["issues_without_brief"] == [2, 3]


def test_build_plan_no_brief_list_empty_when_every_issue_has_a_brief() -> None:
    raw = (
        '[{"number":1,"title":"A","labels":[],"body":"x",'
        '"comments":[{"body":"## Agent Brief\\n\\ndo it"}]}]'
    )
    issues = orchestrate.load_issues(raw)
    plan = orchestrate.build_plan(issues, [], "ready-for-agent")
    assert plan["issues_without_brief"] == []
    assert plan["issues"][0]["no_brief"] is False


def test_build_plan_keeps_every_prior_field_with_no_brief_added() -> None:
    # The no_brief additions must not drop any pre-existing plan field the engine
    # or the report consume.
    raw = '[{"number":1,"title":"A","labels":[],"body":"Standalone."}]'
    issues = orchestrate.load_issues(raw)
    plan = orchestrate.build_plan(issues, [], "ready-for-agent")
    for key in (
        "scope_label",
        "issues",
        "waves",
        "dependency_edges",
        "merge_required",
        "merge_note",
        "soft_notes",
        "warnings",
        "external_dependencies",
        "excluded",
        "issues_without_brief",
    ):
        assert key in plan


# --- exclude_by_label ---------------------------------------------------------


def test_exclude_by_label_partitions_case_insensitively() -> None:
    kept, dropped = orchestrate.exclude_by_label(
        [issue(1, labels=["Ready-For-Human"]), issue(2, labels=["ready-for-agent"])],
        ["ready-for-human"],
    )
    assert [i.number for i in kept] == [2]
    assert [i.number for i in dropped] == [1]


# --- build_waves --------------------------------------------------------------


def test_build_waves_orders_a_linear_chain() -> None:
    waves = orchestrate.build_waves([issue(1), issue(2, {1}), issue(3, {2})])
    assert waves == [[1], [2], [3]]


def test_build_waves_groups_independent_issues_into_one_wave() -> None:
    waves = orchestrate.build_waves([issue(1), issue(2), issue(3)])
    assert waves == [[1, 2, 3]]


def test_build_waves_handles_a_diamond() -> None:
    waves = orchestrate.build_waves(
        [issue(1), issue(2, {1}), issue(3, {1}), issue(4, {2, 3})]
    )
    assert waves == [[1], [2, 3], [4]]


def test_build_waves_ignores_a_blocker_outside_the_scope() -> None:
    # #99 is not in scope, so #1 is not held back by it.
    assert orchestrate.build_waves([issue(1, {99})]) == [[1]]


def test_build_waves_raises_on_a_cycle() -> None:
    with pytest.raises(ValueError, match="cycle"):
        orchestrate.build_waves([issue(1, {2}), issue(2, {1})])


# --- external_dependencies ----------------------------------------------------


def test_external_dependencies_reports_out_of_scope_blockers() -> None:
    assert orchestrate.external_dependencies([issue(1, {99}), issue(2, {1})]) == {
        1: [99]
    }


def test_external_dependencies_is_empty_when_all_blockers_are_in_scope() -> None:
    assert orchestrate.external_dependencies([issue(1), issue(2, {1})]) == {}


# --- red/green parsing and assessment -----------------------------------------


def test_parse_git_log_groups_paths_under_their_commit() -> None:
    commits = orchestrate.parse_git_log(
        "commit aaa\n\nsrc/x.py\ntests/test_x.py\n\ncommit bbb\n\nREADME.md"
    )
    assert commits == [
        Commit(sha="aaa", files=["src/x.py", "tests/test_x.py"]),
        Commit(sha="bbb", files=["README.md"]),
    ]


def test_default_is_test_recognises_directory_segments_and_filenames() -> None:
    assert orchestrate.default_is_test("tests/test_foo.py")
    assert orchestrate.default_is_test("app/__tests__/foo.spec.ts")
    assert orchestrate.default_is_test("src/Foo/BarTest.php")
    assert not orchestrate.default_is_test("src/foo.py")
    assert not orchestrate.default_is_test("README.md")


def test_red_before_green_true_when_test_precedes_source() -> None:
    commits = [Commit("a", ["tests/test_x.py"]), Commit("b", ["src/x.py"])]
    verdict = orchestrate.assess_red_before_green(commits, orchestrate.default_is_test)
    assert verdict["demonstrated"] is True
    assert verdict["redCommit"] == "a"
    assert verdict["greenCommit"] == "b"


def test_red_before_green_false_when_test_and_source_share_a_commit() -> None:
    commits = [Commit("a", ["tests/test_x.py", "src/x.py"])]
    verdict = orchestrate.assess_red_before_green(commits, orchestrate.default_is_test)
    assert verdict["demonstrated"] is False


def test_red_before_green_false_when_source_precedes_test() -> None:
    commits = [Commit("a", ["src/x.py"]), Commit("b", ["tests/test_x.py"])]
    assert (
        orchestrate.assess_red_before_green(commits, orchestrate.default_is_test)[
            "demonstrated"
        ]
        is False
    )


def test_red_before_green_false_when_no_test_commit() -> None:
    commits = [Commit("a", ["src/x.py"])]
    verdict = orchestrate.assess_red_before_green(commits, orchestrate.default_is_test)
    assert verdict["demonstrated"] is False
    assert verdict["redCommit"] is None


def test_make_test_classifier_honours_a_glob_override() -> None:
    is_test = orchestrate.make_test_classifier(["*.spec.ts"])
    assert is_test("feature.spec.ts")
    assert not is_test("tests/test_x.py")  # the override replaces the default


# --- dedupe -------------------------------------------------------------------


def test_dedupe_preserves_first_seen_order_and_drops_blanks() -> None:
    assert orchestrate.dedupe(["B", "a", "A", "", "  ", "b"]) == ["B", "a"]


# --- render_report ------------------------------------------------------------


def test_render_report_leads_with_done_and_dedupes_human_followups() -> None:
    verdicts = [
        Verdict(1, "Schema", "done", "green", "clear", ["Eyeball staging"], [], []),
        Verdict(
            2,
            "API",
            "done",
            "green",
            "clear",
            ["Eyeball staging"],
            ["cursor pagination"],
            [],
        ),
        Verdict(3, "UI", "parked", "", "", [], [], ["flaky a11y assertion"]),
    ]
    report = orchestrate.render_report(verdicts)

    # Done issues appear, the shared follow-up is collapsed to one line, and the
    # parked issue's reason is carried into the blockers section.
    assert "- #1 Schema" in report and "- #2 API" in report
    assert report.count("Eyeball staging") == 1
    assert "#2: cursor pagination" in report
    assert "flaky a11y assertion" in report


def test_render_report_surfaces_a_prerequisite_park_reason() -> None:
    # Issue #20: an issue skipped because an in-scope prerequisite did not land is
    # parked with a reason NAMING that prerequisite. The engine emits that reason in
    # the record's `blockers` (the field render_report shows for a parked issue), so
    # the report must surface it rather than "no reason recorded".
    verdicts = [
        Verdict(
            12,
            "Dependent",
            "parked",
            "",
            "",
            [],
            [],
            ["prerequisite did not land: #11"],
        ),
    ]
    report = orchestrate.render_report(verdicts)

    assert "#12 Dependent (parked) — prerequisite did not land: #11" in report, (
        "a prerequisite-parked issue must appear in the report naming the "
        "unlanded prerequisite, not 'no reason recorded'"
    )
    assert "no reason recorded" not in report


def test_render_report_shows_none_for_empty_sections() -> None:
    report = orchestrate.render_report(
        [Verdict(1, "A", "done", "green", "clear", [], [], [])]
    )
    assert "## Remaining for a human\n\n- None." in report
    assert "## Blockers and parked issues\n\n- None." in report


# --- verify rigor from --level + per-issue Risk (issue #26) --------------------
#
# The planner derives the verify-panel rigor (per-issue lens count) and the
# run-level fix-round cap from the `--level` dial and each issue's explicit risk,
# per ADR-0001 §5-§6. The §5 baseline table: XS/S/M -> 1 lens, 1 fix round;
# L -> 2 lenses, 2 rounds; XL -> 3 lenses, 2 rounds. Per-issue risk escalates on
# top (escalate-only, highest signal wins); an inviolable floor of >=1 lens and
# 1 fix round always holds; `0` fix rounds is reachable only via an explicit
# `--max-fix-rounds=0`. These tests assert on the emitted plan JSON.


def _plan(
    body: str,
    *,
    number: int = 1,
    labels: list[str] | None = None,
    level: str = "M",
    max_fix_rounds: int | None = None,
) -> dict[str, Any]:
    """Load a single-issue plan from a body and return the built plan JSON. The
    level and fix-round override thread straight through to build_plan."""

    entry = {
        "number": number,
        "title": f"Issue {number}",
        "labels": labels or [],
        "body": body,
    }
    issues = orchestrate.load_issues(json.dumps([entry]))
    return orchestrate.build_plan(
        issues, [], "ready-for-agent", level=level, max_fix_rounds=max_fix_rounds
    )


def _lenses(plan: dict[str, Any], number: int = 1) -> list[Any]:
    """The lens list emitted for one issue in a plan."""

    return next(i["lenses"] for i in plan["issues"] if i["number"] == number)


# AC-1: level -> baseline lookup for lenses and the run-level fix-round cap.


@pytest.mark.parametrize("level", ["XS", "S", "M"])
def test_build_plan_low_levels_emit_one_lens_and_one_fix_round(level: str) -> None:
    plan = _plan("Standalone.", level=level)
    assert len(_lenses(plan)) == 1
    assert plan["maxFixRounds"] == 1


def test_build_plan_level_l_emits_two_lenses_and_two_fix_rounds() -> None:
    plan = _plan("Standalone.", level="L")
    assert len(_lenses(plan)) == 2
    assert plan["maxFixRounds"] == 2


def test_build_plan_level_xl_emits_three_lenses_and_two_fix_rounds() -> None:
    plan = _plan("Standalone.", level="XL")
    assert len(_lenses(plan)) == 3
    assert plan["maxFixRounds"] == 2


def test_build_plan_defaults_to_the_m_baseline() -> None:
    # No level argument at all resolves to the M baseline (one lens, one round).
    plan = _plan("Standalone.")
    assert len(_lenses(plan)) == 1
    assert plan["maxFixRounds"] == 1


def test_plan_cli_accepts_level_and_emits_rigor() -> None:
    # AC-1: the real CLI accepts `--level` and emits the derived rigor.
    raw = '[{"number":7,"title":"A","labels":[],"body":"Standalone."}]'
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "plan", "--level=L"],
        input=raw,
        capture_output=True,
        text=True,
        check=True,
    )
    plan = json.loads(result.stdout)
    assert plan["level"] == "L"
    assert plan["maxFixRounds"] == 2
    assert len(plan["issues"][0]["lenses"]) == 2


# AC-2: the `Risk:` marker is parsed and escalates that issue's rigor, escalate-only.


def test_build_plan_risk_high_marker_escalates_lenses() -> None:
    plan = _plan("Agent Brief (Risk: high): do the risky thing.", level="M")
    assert len(_lenses(plan)) == 3


def test_build_plan_risk_medium_marker_escalates_lenses() -> None:
    plan = _plan("Risk: medium\n\nBuild it.", level="M")
    assert len(_lenses(plan)) == 2


def test_build_plan_risk_high_marker_is_a_floor_even_at_xs() -> None:
    # An explicit high is a floor the level can never undercut: XS + Risk: high
    # yields the XL-tier rigor (three lenses), not the XS baseline of one.
    plan = _plan("Risk: high — irreversible delete path.", level="XS")
    assert len(_lenses(plan)) == 3


def test_build_plan_risk_high_marker_escalates_run_level_fix_rounds() -> None:
    # Rigor is the whole §5 row: a high-risk issue lifts the run-level cap to 2.
    plan = _plan("Risk: high.", level="XS")
    assert plan["maxFixRounds"] == 2


def test_build_plan_bold_wrapped_risk_marker_is_parsed() -> None:
    plan = _plan("**Risk:** high\n\nSensitive.", level="XS")
    assert len(_lenses(plan)) == 3


def test_build_plan_risk_marker_in_agent_brief_comment_is_parsed() -> None:
    # The marker lives in the Agent Brief comment, not the body.
    raw = (
        '[{"number":1,"title":"A","labels":[],"body":"Context only.",'
        '"comments":[{"body":"## Agent Brief\\n\\nRisk: high\\n\\nBuild it."}]}]'
    )
    issues = orchestrate.load_issues(raw)
    plan = orchestrate.build_plan(issues, [], "ready-for-agent", level="XS")
    assert len(_lenses(plan)) == 3


def test_build_plan_risk_low_marker_does_not_lower_below_level_baseline() -> None:
    # An explicit low never pulls rigor below the level's own baseline floor.
    plan = _plan("Risk: low\n\nRoutine.", level="L")
    assert len(_lenses(plan)) == 2
    assert plan["maxFixRounds"] == 2


def test_build_plan_risk_high_label_escalates_lenses() -> None:
    # The optional `risk:*` label is an explicit hazard channel too, escalate-only.
    plan = _plan("Standalone.", labels=["risk:high"], level="XS")
    assert len(_lenses(plan)) == 3


# AC-3: the inviolable floor -- >=1 lens even at XS, fix-round floor 1, `0` only
# via an explicit override.


def test_build_plan_xs_still_emits_at_least_one_lens() -> None:
    plan = _plan("Trivial.", level="XS")
    assert len(_lenses(plan)) >= 1


@pytest.mark.parametrize("level", ["XS", "S", "M", "L", "XL"])
def test_build_plan_no_level_defaults_to_zero_fix_rounds(level: str) -> None:
    plan = _plan("Standalone.", level=level)
    assert plan["maxFixRounds"] >= 1


def test_build_plan_zero_fix_rounds_only_via_explicit_override() -> None:
    plan = _plan("Standalone.", level="XS", max_fix_rounds=0)
    assert plan["maxFixRounds"] == 0


def test_build_plan_explicit_override_replaces_the_derived_cap() -> None:
    # An explicit cap wins over the level-derived one (here below the XL default).
    plan = _plan("Standalone.", level="XL", max_fix_rounds=1)
    assert plan["maxFixRounds"] == 1


def test_plan_cli_rejects_a_negative_max_fix_rounds() -> None:
    raw = '[{"number":1,"title":"A","labels":[],"body":"x"}]'
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "plan", "--max-fix-rounds=-1"],
        input=raw,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1


# AC-4: an explicit low that disagrees with a planner-seen hazard (a `risk:*`
# label) is surfaced via the warnings channel and never silently applied.


def test_build_plan_warns_when_low_marker_disagrees_with_hazard_label() -> None:
    plan = _plan("Risk: low\n\nLooks routine.", labels=["risk:high"], level="XS")
    assert any("1" in warning and "low" in warning for warning in plan["warnings"])


def test_build_plan_low_marker_vs_hazard_label_escalates_not_downgrades() -> None:
    # The disagreement is not silently applied: the hazard escalates the rigor.
    plan = _plan("Risk: low\n\nLooks routine.", labels=["risk:high"], level="XS")
    assert len(_lenses(plan)) == 3


def test_build_plan_no_disagreement_warning_when_low_marker_stands_alone() -> None:
    plan = _plan("Risk: low\n\nRoutine.", level="M")
    assert plan["warnings"] == []


# AC-5: round up on uncertainty -- absent or ambiguous risk resolves to the level
# baseline, never below it.


def test_build_plan_absent_risk_resolves_to_level_baseline() -> None:
    plan = _plan("No marker here at all.", level="L")
    assert len(_lenses(plan)) == 2


def test_build_plan_ambiguous_risk_marker_resolves_to_baseline() -> None:
    # A `Risk:` word that is not one of high/medium/low is not a signal: the issue
    # rounds up to the level baseline rather than below it.
    plan = _plan("Risk: elevated maybe\n\nUnclear.", level="M")
    assert len(_lenses(plan)) == 1
    assert plan["maxFixRounds"] == 1


def test_build_plan_run_level_cap_is_the_max_across_issues() -> None:
    # The run-level cap accommodates the riskiest issue: a single Risk: high issue
    # at XS lifts the shared cap to 2 even though the other issue stays baseline.
    raw = (
        '[{"number":1,"title":"A","labels":[],"body":"Routine."},'
        '{"number":2,"title":"B","labels":[],"body":"Risk: high — delete path."}]'
    )
    issues = orchestrate.load_issues(raw)
    plan = orchestrate.build_plan(issues, [], "ready-for-agent", level="XS")
    assert plan["maxFixRounds"] == 2
    assert len(_lenses(plan, 1)) == 1
    assert len(_lenses(plan, 2)) == 3
