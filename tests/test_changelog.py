"""Structural tests for the CHANGELOG's Unreleased section (issue #24 landing).

Issue #23 added its Keep-a-Changelog entry to ``CHANGELOG.md`` at landing time.
Issue #24 — a user-facing change to the shipped ``/orchestrate`` skill that adds
a documented end-of-run "Pruning the run's scaffolding branches" finalize step to
``skills/orchestrate/SKILL.md`` — landed without one. If the release/push
reconciliation trusts entries already being present rather than re-deriving them
from git history, #24's prune step would be silently absent from the next release
notes. These tests guard the symmetry: the Unreleased section must document #24's
scaffolding-branch prune, mirroring the style of #23's already-present entry.

Run with: `uv run --with pytest pytest -q`
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = REPO_ROOT / "CHANGELOG.md"


def _unreleased_section() -> str:
    """The ``## [Unreleased]`` section, up to the next ``## [`` version heading.

    A repo-markdown changelog entry is a single physical line (the paragraphing
    rule), so slicing to whole lines keeps each entry intact for inspection."""

    lines = CHANGELOG.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("## [Unreleased]"))
    rest = lines[start + 1 :]
    end = next(
        (i for i, ln in enumerate(rest) if ln.startswith("## [")),
        len(rest),
    )
    return "\n".join(lines[start : start + 1 + end])


def _scaffolding_prune_entry() -> str | None:
    """The Unreleased bullet documenting #24's scaffolding-branch prune, if any.

    Keyed on ``scaffolding`` — the term that uniquely names #24's change and does
    not appear in any other Unreleased entry — combined with ``prune``."""

    for ln in _unreleased_section().splitlines():
        lowered = ln.lower()
        if (
            ln.lstrip().startswith("-")
            and "scaffolding" in lowered
            and "prune" in lowered
        ):
            return ln
    return None


def test_unreleased_documents_issue_24_scaffolding_prune() -> None:
    # #24's end-of-run scaffolding-branch prune must have its own Unreleased entry.
    entry = _scaffolding_prune_entry()
    assert entry is not None, (
        "the Unreleased section must document #24's end-of-run scaffolding-branch "
        "prune (a bullet mentioning 'scaffolding' and 'prune'), mirroring #23"
    )


def test_issue_24_entry_is_run_scoped_and_names_the_skill() -> None:
    entry = _scaffolding_prune_entry()
    assert entry is not None, "no #24 scaffolding-prune entry found"
    lowered = entry.lower()
    # The entry ties the prune to its run-scoped nature, as the SKILL.md step does.
    assert "runid" in lowered, (
        "the #24 entry must tie the prune to the run-scoped `worktree-<runId>-*` "
        "prefix, not a loose match"
    )
    # It names the shipped file it documents, mirroring #23's file-naming style.
    assert "skill.md" in lowered, (
        "the #24 entry must name `skills/orchestrate/SKILL.md`, the shipped file it "
        "changed, as the other Unreleased entries do"
    )


def test_issue_24_entry_sits_under_fixed_or_changed() -> None:
    # Keep a Changelog places the entry under a change-type heading; #24 fixes a
    # state-neutrality gap, so it belongs under Fixed (or Changed), like #23.
    section = _unreleased_section()
    heading: str | None = None
    found_under: str | None = None
    for ln in section.splitlines():
        if ln.startswith("### "):
            heading = ln.strip()
        elif (
            ln.lstrip().startswith("-")
            and "scaffolding" in ln.lower()
            and "prune" in ln.lower()
        ):
            found_under = heading
            break
    assert found_under in {"### Fixed", "### Changed"}, (
        f"the #24 scaffolding-prune entry must sit under '### Fixed' or "
        f"'### Changed', found under {found_under!r}"
    )
