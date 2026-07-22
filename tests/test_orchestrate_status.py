"""Tests for the `status` subcommand in scripts/orchestrate.py (issue #50).

`status` is a pure stdin -> stdout renderer: it reads a
`gh issue list --json number,comments` payload and prints one row per issue with
its current state in the scoped orchestrate run — `queued`, `working` (with the
phase), `done` (with the SHA), or `parked` (with the reason). It reads the run
lifecycle solely from the durable milestone/landed markers (#48/#49) through
`parse_landed_marker`; it performs no network I/O.

These tests cover the four states, run scoping and `--run`, and the no-marker
`queued` case, against fixture JSON — both through the pure functions and through
the real CLI subprocess.

Run with: `uv run --with pytest pytest -q`
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

# The standalone script under test, loaded by path and exercised through its CLI.
SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "orchestrate.py"

_spec = importlib.util.spec_from_file_location("orchestrate", SCRIPT)
assert _spec is not None and _spec.loader is not None
orchestrate = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = orchestrate
_spec.loader.exec_module(orchestrate)


def comment(body: str, created_at: str) -> dict[str, str]:
    """One issue comment as `gh issue list --json comments` emits it."""

    return {"body": body, "createdAt": created_at}


def issue(number: int, comments: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """One issue row as `gh issue list --json number,comments` emits it."""

    return {"number": number, "comments": comments or []}


def rows_by_number(universe: str, run: str | None = None) -> dict[int, Any]:
    """Build the status board and index its rows by issue number for lookup."""

    parsed = orchestrate.load_status_universe(universe)
    return {row.number: row for row in orchestrate.build_status(parsed, run=run)}


# --- state derivation ---------------------------------------------------------


def test_started_marker_renders_working() -> None:
    marker = orchestrate.format_started_marker(47, "run-1")
    rows = rows_by_number(json.dumps([issue(47, [comment(marker, "2026-07-22T10:00:00Z")])]))
    assert rows[47].state == "working"
    assert "started" in rows[47].detail


def test_implementation_green_renders_working_with_phase() -> None:
    marker = orchestrate.format_implementation_green_marker(47, "run-1")
    rows = rows_by_number(json.dumps([issue(47, [comment(marker, "2026-07-22T10:00:00Z")])]))
    assert rows[47].state == "working"
    assert "implementation green" in rows[47].detail


def test_fix_round_renders_working_with_round_number() -> None:
    marker = orchestrate.format_fix_round_marker(47, 2, "run-1")
    rows = rows_by_number(json.dumps([issue(47, [comment(marker, "2026-07-22T10:00:00Z")])]))
    assert rows[47].state == "working"
    assert "fix round 2" in rows[47].detail


def test_verification_cleared_renders_working_verifying() -> None:
    marker = orchestrate.format_verification_cleared_marker(47, "run-1")
    rows = rows_by_number(json.dumps([issue(47, [comment(marker, "2026-07-22T10:00:00Z")])]))
    assert rows[47].state == "working"
    assert "verif" in rows[47].detail.lower()


def test_landed_marker_renders_done_with_sha() -> None:
    marker = orchestrate.format_landed_marker("a1b2c3d", "main", "run-1")
    rows = rows_by_number(json.dumps([issue(47, [comment(marker, "2026-07-22T10:00:00Z")])]))
    assert rows[47].state == "done"
    assert "a1b2c3d" in rows[47].detail


def test_parked_marker_renders_parked_with_reason() -> None:
    marker = orchestrate.format_parked_marker(47, "fix rounds exhausted", "run-1")
    rows = rows_by_number(json.dumps([issue(47, [comment(marker, "2026-07-22T10:00:00Z")])]))
    assert rows[47].state == "parked"
    assert "fix rounds exhausted" in rows[47].detail


def test_issue_with_no_marker_renders_queued() -> None:
    rows = rows_by_number(json.dumps([issue(51, [comment("just a normal comment", "2026-07-22T10:00:00Z")])]))
    assert rows[51].state == "queued"


def test_issue_with_no_comments_renders_queued() -> None:
    rows = rows_by_number(json.dumps([issue(51)]))
    assert rows[51].state == "queued"


# --- latest-milestone-within-run ---------------------------------------------


def test_latest_marker_in_run_wins() -> None:
    started = orchestrate.format_started_marker(47, "run-1")
    green = orchestrate.format_implementation_green_marker(47, "run-1")
    landed = orchestrate.format_landed_marker("deadbee", "main", "run-1")
    rows = rows_by_number(
        json.dumps(
            [
                issue(
                    47,
                    [
                        comment(started, "2026-07-22T10:00:00Z"),
                        comment(green, "2026-07-22T11:00:00Z"),
                        comment(landed, "2026-07-22T12:00:00Z"),
                    ],
                )
            ]
        )
    )
    assert rows[47].state == "done"
    assert "deadbee" in rows[47].detail


# --- run scoping --------------------------------------------------------------


def test_default_run_is_the_latest_by_marker_timestamp() -> None:
    old = orchestrate.format_landed_marker("old1234", "main", "run-1")
    new = orchestrate.format_started_marker(47, "run-2")
    rows = rows_by_number(
        json.dumps(
            [
                issue(
                    47,
                    [
                        comment(old, "2026-07-20T10:00:00Z"),
                        comment(new, "2026-07-22T10:00:00Z"),
                    ],
                )
            ]
        )
    )
    # run-2 is the newest run, so its `started` milestone governs — not run-1's landed.
    assert rows[47].state == "working"


def test_explicit_run_pins_an_older_run() -> None:
    old = orchestrate.format_landed_marker("old1234", "main", "run-1")
    new = orchestrate.format_started_marker(47, "run-2")
    rows = rows_by_number(
        json.dumps(
            [
                issue(
                    47,
                    [
                        comment(old, "2026-07-20T10:00:00Z"),
                        comment(new, "2026-07-22T10:00:00Z"),
                    ],
                )
            ]
        ),
        run="run-1",
    )
    # Pinned to run-1, so its landed marker governs even though run-2 is newer.
    assert rows[47].state == "done"
    assert "old1234" in rows[47].detail


def test_issue_with_marker_only_in_another_run_is_queued() -> None:
    # Issue 48 carries only a run-1 marker; scoped to run-2 it has no marker.
    other = orchestrate.format_started_marker(48, "run-1")
    current = orchestrate.format_started_marker(47, "run-2")
    universe = json.dumps(
        [
            issue(47, [comment(current, "2026-07-22T11:00:00Z")]),
            issue(48, [comment(other, "2026-07-20T10:00:00Z")]),
        ]
    )
    rows = rows_by_number(universe)
    assert rows[47].state == "working"
    assert rows[48].state == "queued"


# --- full board, four states together ----------------------------------------


def test_board_renders_all_four_states_one_row_per_issue() -> None:
    universe = json.dumps(
        [
            issue(47, [comment(orchestrate.format_landed_marker("a1b2c3d", "main", "run-9"), "2026-07-22T10:00:00Z")]),
            issue(48, [comment(orchestrate.format_verification_cleared_marker(48, "run-9"), "2026-07-22T10:05:00Z")]),
            issue(51, []),
            issue(52, [comment(orchestrate.format_parked_marker(52, "fix rounds exhausted", "run-9"), "2026-07-22T10:10:00Z")]),
        ]
    )
    parsed = orchestrate.load_status_universe(universe)
    board = orchestrate.build_status(parsed)
    assert [row.number for row in board] == [47, 48, 51, 52]
    rendered = orchestrate.render_status(board)
    lines = [line for line in rendered.splitlines() if line.strip()]
    assert len(lines) == 4
    assert "#47" in rendered and "done" in rendered and "a1b2c3d" in rendered
    assert "#48" in rendered and "working" in rendered
    assert "#51" in rendered and "queued" in rendered
    assert "#52" in rendered and "parked" in rendered and "fix rounds exhausted" in rendered


# --- CLI subprocess -----------------------------------------------------------


def run_cli(payload: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Invoke `orchestrate.py status` with the payload on stdin."""

    return subprocess.run(
        [sys.executable, str(SCRIPT), "status", *args],
        input=payload,
        capture_output=True,
        text=True,
    )


def test_cli_status_prints_board_from_stdin() -> None:
    universe = json.dumps(
        [
            issue(47, [comment(orchestrate.format_landed_marker("a1b2c3d", "main", "run-9"), "2026-07-22T10:00:00Z")]),
            issue(51, []),
        ]
    )
    result = run_cli(universe)
    assert result.returncode == 0, result.stderr
    assert "#47" in result.stdout
    assert "done" in result.stdout
    assert "a1b2c3d" in result.stdout
    assert "#51" in result.stdout
    assert "queued" in result.stdout


def test_cli_status_run_flag_pins_a_specific_run() -> None:
    old = orchestrate.format_landed_marker("old1234", "main", "run-1")
    new = orchestrate.format_started_marker(47, "run-2")
    universe = json.dumps(
        [issue(47, [comment(old, "2026-07-20T10:00:00Z"), comment(new, "2026-07-22T10:00:00Z")])]
    )
    result = run_cli(universe, "--run", "run-1")
    assert result.returncode == 0, result.stderr
    assert "done" in result.stdout
    assert "old1234" in result.stdout


def test_cli_status_rejects_malformed_json() -> None:
    result = run_cli("{not json")
    assert result.returncode == 1
    assert "error" in result.stderr.lower()
