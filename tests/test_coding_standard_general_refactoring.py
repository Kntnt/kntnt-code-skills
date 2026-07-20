"""Structural tests for the refactoring-completeness rule (issue #35).

`lib/coding-standard/general.md` — the canonical, language-agnostic module
every other coding-standard module presupposes — previously carried no rule
about refactoring completeness: an implementer could change a shared symbol's
contract, signature, or effective behaviour, update only the callers already
in view, and produce a diff that reads as consistent within the files it
touches while leaving the codebase globally inconsistent. Per-issue/PR review
that only reads the diff structurally misses the gap.

These tests read `lib/coding-standard/general.md` as text and assert the new
rule carries the three concrete requirements from the issue's acceptance
criteria:

1. Enumerate every caller (grep / find-references) before finishing.
2. Update every call site in the same change — never leave some callers on
   the old contract.
3. When the change would genuinely ripple beyond the task at hand, say so
   explicitly in the summary/handoff rather than half-applying it.

They also guard the two structural non-goals: the rule is language-agnostic
(no language/framework name baked into its prose), and adding it introduces
no new module — `lib/coding-standard/_index.md` and `scripts/scaffold.py`'s
canonical order are untouched. `CHANGELOG.md`'s `[Unreleased]` section must
document the rule and the fact that already-scaffolded projects only pick it
up on their next `/coding-standard --update`.

Whether the rule's *tone and length* genuinely read as one of the surrounding
"Universal rules" siblings, rather than merely containing the right keywords,
is the kind of cognitive judgement `scripts/audit.py` itself deliberately
keeps manual (see its module docstring) — a loose sanity bound on word count
is asserted here as a weak signal, but the residual is a human editorial call.

Run with: `uv run --with pytest pytest -q`
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERAL_MD = REPO_ROOT / "lib" / "coding-standard" / "general.md"
INDEX_MD = REPO_ROOT / "lib" / "coding-standard" / "_index.md"
SCAFFOLD_PY = REPO_ROOT / "scripts" / "scaffold.py"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

# The module stems `lib/coding-standard/` carries today (excluding the
# leading-underscore `_index.md`, which is shared profiling knowledge rather
# than a materialisable module). This issue must not add or remove one.
KNOWN_MODULE_STEMS = frozenset(
    {
        "general",
        "php",
        "wordpress",
        "wordpress-block",
        "typescript",
        "javascript-vanilla",
        "python",
        "bash",
    }
)

# Language/framework names that would make the rule non-language-agnostic if
# they showed up inside its own prose — the whole point of it living in the
# universal module rather than a per-language one.
LANGUAGE_NAMES = (
    "PHP",
    "JavaScript",
    "TypeScript",
    "Python",
    "WordPress",
    "Bash",
    "PSR-12",
)


def _general_text() -> str:
    assert GENERAL_MD.is_file(), "lib/coding-standard/general.md is missing"
    return GENERAL_MD.read_text(encoding="utf-8")


def _section(text: str, start_pattern: str, end_pattern: str) -> str:
    """Slice from the heading matching ``start_pattern`` up to (excluding) the
    next heading matching ``end_pattern`` — the text's tail if none follows.

    Searches for ``end_pattern`` only after the start heading's own line, so
    an end pattern that (unlike the start pattern) also matches the start
    heading's hash level cannot re-match at position zero."""

    start = re.search(start_pattern, text, re.MULTILINE)
    assert start is not None, f"section start not found: {start_pattern!r}"
    rest = text[start.start() :]
    after_heading = rest.find("\n") + 1 or len(rest)
    end = re.search(end_pattern, rest[after_heading:], re.MULTILINE)
    return rest if end is None else rest[: after_heading + end.start()]


def _universal_rules_section() -> str:
    """The '## Universal rules' section, up to the next '## ' heading."""

    return _section(_general_text(), r"^##\s+Universal rules", r"^##\s+\S")


def _refactoring_completeness_section() -> str:
    """The '### Refactoring completeness' rule, up to the next heading."""

    return _section(
        _universal_rules_section(),
        r"^###\s+Refactoring completeness",
        r"^#{2,3}\s+\S",
    )


def _defensive_coding_section() -> str:
    """Sibling rule used only as a length reference point."""

    return _section(
        _universal_rules_section(), r"^###\s+Defensive coding", r"^###\s+\S"
    )


# --- the rule exists, in the right place ------------------------------------


def test_universal_rules_has_a_refactoring_completeness_heading() -> None:
    section = _universal_rules_section()
    assert re.search(r"^###\s+Refactoring completeness", section, re.MULTILINE), (
        "## Universal rules must gain a '### Refactoring completeness' rule (#35)"
    )


# --- the three acceptance-criteria requirements -----------------------------


def test_rule_requires_enumerating_callers_before_finishing() -> None:
    section = _refactoring_completeness_section().lower()
    assert "enumerate" in section, "the rule must require enumerating callers"
    assert "caller" in section or "call site" in section, (
        "the rule must name callers or call sites as what gets enumerated"
    )
    assert (
        "grep" in section
        or "find-references" in section
        or "find references" in section
    ), "the rule must name a concrete enumeration technique (grep / find-references)"


def test_rule_requires_updating_every_call_site_in_the_same_change() -> None:
    section = _refactoring_completeness_section().lower()
    assert "same change" in section, (
        "the rule must require every call site to be updated in the same change"
    )
    assert "every" in section or "all of them" in section, (
        "the rule must be unambiguous that ALL callers are updated, not just some"
    )


def test_rule_warns_a_locally_consistent_diff_can_be_globally_inconsistent() -> None:
    section = _refactoring_completeness_section().lower()
    assert "locally" in section and "consistent" in section, (
        "the rule must name the locally-consistent-diff failure mode"
    )
    assert "globally inconsistent" in section, (
        "the rule must state the diff can still leave the codebase globally inconsistent"
    )


def test_rule_requires_flagging_ripple_beyond_the_task_instead_of_half_applying() -> (
    None
):
    section = _refactoring_completeness_section().lower()
    assert "ripple" in section, "the rule must name the ripple-beyond-the-task case"
    assert "summary" in section or "handoff" in section, (
        "the rule must say where to flag the ripple (summary/handoff)"
    )


# --- language-agnostic, consistent tone/length ------------------------------


def test_rule_is_language_agnostic() -> None:
    section = _refactoring_completeness_section()
    for name in LANGUAGE_NAMES:
        assert not re.search(rf"\b{re.escape(name)}\b", section), (
            f"the rule must be language-agnostic — it must not mention {name!r}"
        )


def test_rule_length_is_a_plausible_sibling_of_defensive_coding() -> None:
    # Weak automated signal only — see module docstring. A rule far shorter
    # than a one-liner, or wildly longer than its longest sibling, is a sign
    # something is off; a genuine tone/length fit is a human editorial call.
    rule_words = len(_refactoring_completeness_section().split())
    sibling_words = len(_defensive_coding_section().split())
    assert 15 <= rule_words <= sibling_words * 2, (
        f"rule is {rule_words} words; Defensive coding sibling is {sibling_words} words"
    )


# --- no structural change to the index or scaffolder ------------------------


def test_no_new_or_removed_module_file() -> None:
    modules_dir = REPO_ROOT / "lib" / "coding-standard"
    stems = {
        p.stem
        for p in modules_dir.iterdir()
        if p.is_file() and p.suffix == ".md" and not p.name.startswith("_")
    }
    assert stems == KNOWN_MODULE_STEMS, (
        "this issue must not add or remove a coding-standard module file"
    )


def test_index_module_table_is_unchanged() -> None:
    index_text = INDEX_MD.read_text(encoding="utf-8")
    for stem in KNOWN_MODULE_STEMS:
        assert f"`{stem}.md`" in index_text, f"_index.md must still list `{stem}.md`"


def test_scaffold_canonical_order_is_unchanged() -> None:
    scaffold_text = SCAFFOLD_PY.read_text(encoding="utf-8")
    for stem in KNOWN_MODULE_STEMS:
        assert f'"{stem}"' in scaffold_text, (
            f"scripts/scaffold.py's CANONICAL_ORDER must still list {stem!r}"
        )


# --- CHANGELOG documents the rule and the re-sync note ----------------------


def test_changelog_unreleased_documents_the_rule_and_resync_note() -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    # This entry is a permanent record: it starts under [Unreleased] and a release
    # moves it verbatim into that version's section, where it stays as newer
    # releases land above it. Find whichever section holds it by its issue marker,
    # so the test survives any number of later releases, not just the first.
    sections = re.split(r"(?m)^(?=## )", text)
    entry = next((section for section in sections if "#35" in section), "")
    assert "#35" in entry, "CHANGELOG must reference issue #35"
    lowered = entry.lower()
    assert "refactoring completeness" in lowered, "CHANGELOG must name the new rule"
    assert "--update" in entry, (
        "CHANGELOG must note that already-scaffolded projects need a "
        "`/coding-standard --update` re-sync to pick up the rule"
    )
