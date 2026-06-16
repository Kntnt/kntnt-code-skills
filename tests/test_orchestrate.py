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
