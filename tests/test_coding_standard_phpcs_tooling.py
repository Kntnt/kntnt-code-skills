"""Guards for #39 — naming phpcs + WPCS as recommended tooling.

Before this change, phpcs appeared nowhere in the standard even though every
Kntnt WordPress project ships it, so each project's `phpcs.xml.dist` was
copy-pasted from an older project rather than written from the standard.
That produced measurable drift: a wrong 120-column line cap inherited from a
stale config, warnings that could not fail the build, and exclusions that
had to be rediscovered from scratch instead of read from the standard.

Scope settled at triage: prose-only — no central `kntnt/coding-standard`
ruleset package. `php.md` and `wordpress.md` now name phpcs + WPCS as
**recommended**, not required, tooling for WordPress projects, and
`wordpress.md` carries three things in prose:

1. The sniffs to exclude so a ruleset encodes this standard's four
   deliberate WP-CS deviations (`[ ]` arrays, PSR-4 filenames, namespaces
   over `kntnt_` prefixes, no Yoda) plus the sniffs that actively contradict
   the standard (forced `=>` alignment, the forbidden blank line before a
   function's closing brace).
2. What phpcs cannot enforce — the comment-width rule and the no-alignment
   rule — so a green run is read as "conforms to the subset phpcs can see,"
   never "conforms."
3. That the ruleset lives per project; no central package exists yet.

These tests read `lib/coding-standard/php.md` and `lib/coding-standard/
wordpress.md` as text and assert the above structurally. Whether the prose
reads well as English, rather than merely containing the right substrings,
is a human editorial call.

Run with: `uv run --with pytest pytest -q`
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULES_DIR = REPO_ROOT / "lib" / "coding-standard"
PHP_MD = MODULES_DIR / "php.md"
WORDPRESS_MD = MODULES_DIR / "wordpress.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

# The six sniffs a project's ruleset must exclude: the four deliberate
# WP-CS deviations plus the two sniffs that actively contradict the
# standard (forced array/=> alignment, the forbidden blank line before a
# function's closing brace).
REQUIRED_EXCLUDED_SNIFFS = (
    "Universal.Arrays.DisallowShortArraySyntax",
    "WordPress.Files.FileName",
    "WordPress.NamingConventions.PrefixAllGlobals",
    "WordPress.PHP.YodaConditions",
    "WordPress.Arrays.MultipleStatementAlignment",
    "PSR2.Methods.FunctionClosingBrace",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(text: str, start_pattern: str, end_pattern: str) -> str:
    """Slice from the heading matching ``start_pattern`` up to (excluding) the
    next heading matching ``end_pattern`` — the text's tail if none follows."""

    start = re.search(start_pattern, text, re.MULTILINE)
    assert start is not None, f"section start not found: {start_pattern!r}"
    rest = text[start.start() :]
    after_heading = rest.find("\n") + 1 or len(rest)
    end = re.search(end_pattern, rest[after_heading:], re.MULTILINE)
    return rest if end is None else rest[: after_heading + end.start()]


def _wordpress_tooling_section() -> str:
    """The '### WordPress-specific tooling' section, up to the next heading."""

    return _section(
        _text(WORDPRESS_MD), r"^###\s+WordPress-specific tooling", r"^###\s+\S"
    )


def _phpcs_ruleset_section() -> str:
    """The dedicated phpcs/WPCS ruleset section, up to the next heading."""

    return _section(
        _text(WORDPRESS_MD), r"^###\s+phpcs\b.*WPCS.*ruleset", r"^###\s+\S|\Z"
    )


def _cannot_enforce_paragraph() -> str:
    """The 'What phpcs cannot enforce' sub-block inside the ruleset section."""

    section = _phpcs_ruleset_section()
    return _section(section, r"cannot enforce", r"\Z")


# --- php.md names phpcs + WPCS, pointing onward ------------------------


def test_php_md_php_tooling_names_phpcs_and_wpcs() -> None:
    text = _text(PHP_MD)
    tooling = _section(text, r"^###\s+PHP tooling", r"\Z")
    assert "phpcs" in tooling, "php.md's PHP tooling section must name phpcs"
    assert "WPCS" in tooling, "php.md's PHP tooling section must name WPCS"


def test_php_md_still_points_wordpress_specifics_at_the_wordpress_module() -> None:
    text = _text(PHP_MD)
    tooling = _section(text, r"^###\s+PHP tooling", r"\Z")
    assert "WordPress rules" in tooling, (
        "php.md must still point WordPress-specific tooling detail at the "
        "WordPress module rather than duplicating it"
    )


# --- wordpress.md names phpcs + WPCS as recommended, not required -------


def test_wordpress_md_tooling_section_names_phpcs_and_wpcs() -> None:
    section = _wordpress_tooling_section()
    assert "phpcs" in section
    assert "WPCS" in section or "wp-coding-standards/wpcs" in section


def test_wordpress_md_states_phpcs_is_recommended_not_required() -> None:
    section = _wordpress_tooling_section().lower()
    assert "recommended" in section, (
        "wordpress.md must state phpcs is recommended tooling"
    )
    assert "not required" in section, (
        "wordpress.md must explicitly state phpcs is NOT required — a "
        "mandate would contradict the proportionality direction (#40)"
    )


# --- the dedicated ruleset section exists --------------------------------


def test_wordpress_md_has_a_dedicated_phpcs_ruleset_section() -> None:
    text = _text(WORDPRESS_MD)
    assert re.search(r"^###\s+phpcs\b.*WPCS.*ruleset", text, re.MULTILINE), (
        "wordpress.md must gain a dedicated '### phpcs / WPCS ruleset' "
        "section documenting exclusions, the cannot-enforce list, and the "
        "per-project posture"
    )


# --- required exclusions enumerated in prose -----------------------------


def test_ruleset_section_enumerates_every_required_exclusion() -> None:
    section = _phpcs_ruleset_section()
    for sniff in REQUIRED_EXCLUDED_SNIFFS:
        assert sniff in section, (
            f"the phpcs/WPCS ruleset section must name {sniff!r} as a "
            "required exclusion"
        )


def test_ruleset_section_ties_exclusions_to_the_deliberate_deviations() -> None:
    section = _phpcs_ruleset_section().lower()
    for term in ("array", "filename", "namespace", "yoda"):
        assert term in section, (
            f"the ruleset section must connect its exclusions back to the "
            f"deliberate deviation concerning {term!r}"
        )


def test_ruleset_section_ties_exclusions_to_the_direct_contradictions() -> None:
    section = _phpcs_ruleset_section().lower()
    assert "align" in section, (
        "the ruleset section must name the forced-alignment contradiction"
    )
    assert "blank line" in section, (
        "the ruleset section must name the forbidden-blank-line contradiction"
    )


# --- explicit cannot-enforce list -----------------------------------------


def test_cannot_enforce_paragraph_names_comment_width_rule() -> None:
    paragraph = _cannot_enforce_paragraph().lower()
    assert "comment" in paragraph and "80" in paragraph, (
        "the cannot-enforce list must name the 80-column comment-width rule"
    )


def test_cannot_enforce_paragraph_names_no_alignment_rule() -> None:
    paragraph = _cannot_enforce_paragraph().lower()
    assert "alignment" in paragraph, (
        "the cannot-enforce list must name the no-vertical-alignment rule"
    )
    assert "never" in paragraph or "cannot" in paragraph or "no sniff" in paragraph, (
        "the cannot-enforce list must state phpcs cannot check the rule, not "
        "merely mention alignment in passing"
    )


def test_cannot_enforce_paragraph_frames_green_as_partial_not_full_conformance() -> (
    None
):
    section = _phpcs_ruleset_section().lower()
    assert "conforms" in section, (
        "the ruleset section must state that a green phpcs run means "
        "conforming to the subset phpcs can see, never full conformance"
    )


# --- per-project posture, no central package ------------------------------


def test_ruleset_section_states_no_central_package_exists() -> None:
    section = _phpcs_ruleset_section().lower()
    assert "per project" in section or "per-project" in section, (
        "the ruleset section must state the ruleset lives per project"
    )
    assert (
        "no central" in section or "not exist" in section or "no package" in section
    ), "the ruleset section must state no central package exists"


# --- CHANGELOG documents the change ---------------------------------------


def test_changelog_unreleased_documents_phpcs_tooling_addition() -> None:
    text = _text(CHANGELOG)
    # This entry is a permanent record: it starts under [Unreleased] and a release
    # moves it verbatim into that version's section, where it stays as newer
    # releases land above it. Find whichever section holds it by its issue marker,
    # so the test survives any number of later releases, not just the first.
    sections = re.split(r"(?m)^(?=## )", text)
    entry = next((section for section in sections if "#39" in section), "")
    assert "#39" in entry, "CHANGELOG must reference issue #39"
    lowered = entry.lower()
    assert "phpcs" in lowered and "wpcs" in lowered, (
        "CHANGELOG must name phpcs and WPCS in the new entry"
    )
