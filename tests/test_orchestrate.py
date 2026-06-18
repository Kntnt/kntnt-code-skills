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
import sys
from pathlib import Path

import pytest

# Load scripts/orchestrate.py by path, since it is a standalone script rather
# than an importable package. Register it in sys.modules before executing so
# its @dataclass decorators can resolve their own module during class creation.
_spec = importlib.util.spec_from_file_location(
    "orchestrate", Path(__file__).resolve().parent.parent / "scripts" / "orchestrate.py"
)
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


def test_render_report_shows_none_for_empty_sections() -> None:
    report = orchestrate.render_report(
        [Verdict(1, "A", "done", "green", "clear", [], [], [])]
    )
    assert "## Remaining for a human\n\n- None." in report
    assert "## Blockers and parked issues\n\n- None." in report
