"""Guards for #41 — plugin/theme header metadata is exempt from the
comment-width rule.

`lib/coding-standard/wordpress.md` said nothing about the plugin header
docblock (main plugin file) or the theme `style.css` header. The general
module's comment-width rule (*Line wrapping*, added by #37) hard-wraps a
standalone comment at column 80 — but these headers are not prose comments:
`get_file_data()` parses them one field per line, with no continuation
syntax, so wrapping a long `Description:` does not reformat it, it silently
truncates it at the line break. WordPress's header-parsing regex also treats
`@` as an ordinary header-line prefix (on a par with `*`, `#`, and
whitespace), so a linter annotation such as `@since` or `@phpstan-ignore`
placed inside the header block risks being parsed as, and shadowing, a real
field.

Triage settled #41 as prose-only, scoped to the **whole header block** (not
only its `Field:` lines), and left column alignment of field values to
WordPress convention — the general module's ban on vertical alignment of
`=` / `=>` does not extend to header metadata.

These tests read `lib/coding-standard/wordpress.md` as text and assert:

1. A dedicated section documents the header block.
2. The comment-width rule is exempted for the whole block, not only
   `Field:` lines.
3. A field is never wrapped, with the `get_file_data()` one-field-per-line
   reason.
4. Linter annotations are warned against, with the `@`-prefix-shadowing
   reason.
5. Column alignment of field values is left to WordPress convention, with
   an explicit statement that the general module's alignment ban does not
   extend here.

Whether the prose reads well as English, rather than merely containing the
right substrings, is a human editorial call.

Run with: `uv run --with pytest pytest -q`
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORDPRESS_MD = REPO_ROOT / "lib" / "coding-standard" / "wordpress.md"

# The heading the new section must carry — matched loosely so a minor title
# rewording ("Plugin and theme header metadata") still passes.
_HEADING_PATTERN = r"^###\s+Plugin and theme headers?\b.*$"


def _text() -> str:
    return WORDPRESS_MD.read_text(encoding="utf-8")


def _header_section() -> str:
    """The new header-metadata section, from its own heading up to (not
    including) the next `###` heading, or the file's tail if it is last."""

    text = _text()
    start = re.search(_HEADING_PATTERN, text, re.MULTILINE)
    assert start is not None, (
        "wordpress.md must gain a dedicated '### Plugin and theme headers' "
        "section documenting the comment-width exemption"
    )
    rest = text[start.end() :]
    end = re.search(r"^###\s+\S", rest, re.MULTILINE)
    return rest if end is None else rest[: end.start()]


# --- the section exists ------------------------------------------------


def test_wordpress_md_has_a_dedicated_header_section() -> None:
    # Raises via the assertion inside _header_section() if missing.
    section = _header_section()
    assert section.strip(), "the header section must not be empty"


# --- headers are metadata, parsed one field per line --------------------


def test_header_section_states_headers_are_metadata_not_comments() -> None:
    section = _header_section().lower()
    assert "metadata" in section, (
        "the section must state plugin/theme headers are metadata, not prose"
    )
    assert "get_file_data" in _header_section(), (
        "the section must name get_file_data() as the parser driving the "
        "one-field-per-line format"
    )


def test_header_section_states_one_field_per_line() -> None:
    section = _header_section().lower()
    assert "one field per line" in section or "field per line" in section, (
        "the section must state the header format is parsed one field per "
        "line, with no continuation"
    )


# --- the whole block is exempt from the comment-width rule --------------


def test_header_section_exempts_the_whole_block_from_comment_width_rule() -> None:
    section = _header_section().lower()
    assert "comment-width" in section or "line wrapping" in section, (
        "the section must reference the comment-width / Line wrapping rule "
        "it is exempting the header block from"
    )
    assert "whole" in section or "entire" in section, (
        "the exemption must explicitly cover the whole header block, not "
        "only its Field: lines — the triage-settled scope"
    )


def test_header_section_exemption_is_not_scoped_to_field_lines_only() -> None:
    section = _header_section()
    assert "not only" in section.lower() or "not just" in section.lower(), (
        "the section must explicitly rule out the narrower reading — the "
        "exemption is not limited to lines that carry a `Field:` label"
    )


# --- a field is never wrapped, with the get_file_data() reason ----------


def test_header_section_states_a_field_is_never_wrapped() -> None:
    section = _header_section().lower()
    assert "never" in section and "wrap" in section, (
        "the section must state a header field is never wrapped across multiple lines"
    )


def test_header_section_states_wrapping_silently_truncates() -> None:
    section = _header_section().lower()
    assert "silent" in section, (
        "the section must state that get_file_data() drops a wrapped "
        "continuation silently — no error, no warning"
    )
    assert "truncat" in section or "drop" in section, (
        "the section must state the dropped/truncated consequence of "
        "wrapping a field, not just that wrapping is disallowed"
    )


# --- linter annotations are warned against, with the @-prefix reason ----


def test_header_section_warns_against_linter_annotations() -> None:
    section = _header_section().lower()
    assert "annotation" in section, (
        "the section must warn against placing a linter annotation inside "
        "the header block"
    )
    assert "never" in section or "don't" in section or "do not" in section, (
        "the warning must be stated as a rule, not merely mentioned in passing"
    )


def test_header_section_states_the_at_prefix_reason() -> None:
    section = _header_section()
    assert "@" in section, (
        "the section must name the `@` character as the mechanism behind "
        "the annotation risk"
    )
    lowered = section.lower()
    assert "prefix" in lowered, (
        "the section must state that `@` is parsed as a header-line prefix"
    )
    assert "shadow" in lowered, (
        "the section must state the consequence: an annotation can shadow a real field"
    )


# --- alignment is left to WordPress convention ---------------------------


def test_header_section_leaves_field_alignment_to_wordpress_convention() -> None:
    section = _header_section().lower()
    assert "alignment" in section, (
        "the section must address column alignment of header field values"
    )
    assert "wordpress convention" in section, (
        "the section must explicitly leave field-value alignment to "
        "WordPress convention"
    )


def test_header_section_states_general_alignment_ban_does_not_extend_here() -> None:
    section = _header_section().lower()
    assert "does not extend" in section or "does not apply" in section, (
        "the section must explicitly state that the general module's "
        "no-alignment rule does not extend to header fields — otherwise a "
        "reader could plausibly think the two rules conflict"
    )


# --- the section stays in the WordPress module, not duplicated elsewhere --


def test_php_md_carries_no_header_metadata_rule() -> None:
    php_md = (REPO_ROOT / "lib" / "coding-standard" / "php.md").read_text(
        encoding="utf-8"
    )
    assert "get_file_data" not in php_md, (
        "the header-metadata exemption is a WordPress-specific rule and "
        "must live in wordpress.md only, not duplicated into php.md"
    )
