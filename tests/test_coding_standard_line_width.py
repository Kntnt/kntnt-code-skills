"""Guards for #37 — the standard's line-width rules.

Before this change, `general.md` stated a single vague sentence ("Comments
wrap at column 80. Code may go wider where it improves readability — see
formatter settings per language.") that disagreed with `php.md`'s own
duplicate ("Comments wrap at column 80.") plus a hard 120-column code cap.
Neither mentioned trailing (end-of-line) comments, and no tooling anywhere
enforced the 80-column comment rule.

`general.md` becomes the single authoritative source, stating three rules —
a standalone comment hard-wraps at 80, a trailing comment never wraps, code
has no upper limit (a removal of *pressure* to break, not licence to sprawl,
with the existing *Motivated line breaks* guidance as the actual trigger for
breaking) — and records that rule 1 is enforced by review, since no sniff can
express a comment-specific width. `php.md` drops its 120-column cap and its
duplicated comment rule, pointing to the general module instead. The other
language modules are checked for the same duplicated/conflicting rule (not
for an unrelated formatter tool setting, e.g. TypeScript's Biome `Line width`
config, which is a distinct per-tool default, not a restatement of the
standard's own comment/code width rule).

Run with: `uv run --with pytest pytest -q`
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULES_DIR = REPO_ROOT / "lib" / "coding-standard"
GENERAL_MD = MODULES_DIR / "general.md"
PHP_MD = MODULES_DIR / "php.md"

# Modules other than general/php that must stay free of a duplicated or
# conflicting comment/code width rule.
OTHER_MODULES = ("typescript.md", "javascript-vanilla.md", "python.md", "bash.md")

# The old sentence general.md must no longer carry verbatim — it is the
# ambiguous "may go wider" statement rule 3 replaces.
_OLD_GENERAL_LINE_WRAPPING = (
    "Code may go wider where it improves readability — see formatter "
    "settings per language."
)

# The old php.md bullet that duplicated the comment rule and hard-capped code
# at 120 columns — must not survive anywhere in the file.
_OLD_PHP_LINE_WRAPPING = (
    "Code may go up to the project's max line width (default 120 cols). "
    "Comments wrap at column 80."
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _line_wrapping_paragraph(text: str) -> str:
    """The `**Line wrapping.**` paragraph in general.md, up to the next
    `###` heading (`### Whitespace`)."""

    start = text.index("**Line wrapping.**")
    end = text.index("### Whitespace", start)
    return text[start:end]


def test_general_md_no_longer_carries_the_old_ambiguous_sentence() -> None:
    text = _text(GENERAL_MD)
    assert _OLD_GENERAL_LINE_WRAPPING not in text, (
        "the old ambiguous 'Code may go wider ... see formatter settings per "
        "language' sentence must be replaced by the three explicit rules"
    )


def test_general_md_states_standalone_comments_hard_wrap_at_80() -> None:
    paragraph = _line_wrapping_paragraph(_text(GENERAL_MD)).lower()
    assert "column 80" in paragraph, (
        "general.md must state that a standalone comment never passes column 80"
    )
    assert "never" in paragraph


def test_general_md_states_trailing_comments_never_wrap() -> None:
    paragraph = _line_wrapping_paragraph(_text(GENERAL_MD)).lower()
    assert "trailing" in paragraph or "end of a code line" in paragraph, (
        "general.md must explicitly call out trailing (end-of-line) comments"
    )
    assert "never" in paragraph and "wrap" in paragraph


def test_general_md_states_code_lines_have_no_upper_limit_with_sprawl_caveat() -> None:
    paragraph = _line_wrapping_paragraph(_text(GENERAL_MD)).lower()
    assert "no upper limit" in paragraph, (
        "general.md must state code lines have no upper limit"
    )
    assert "sprawl" in paragraph or "invitation" in paragraph, (
        "general.md must caveat that removing the limit is not an invitation "
        "to let code sprawl"
    )


def test_general_md_positions_motivated_line_breaks_as_the_trigger() -> None:
    paragraph = _line_wrapping_paragraph(_text(GENERAL_MD))
    assert "Motivated line breaks" in paragraph, (
        "the Line wrapping rule must point at *Motivated line breaks* as the "
        "replacement trigger for breaking a code line"
    )


def test_general_md_records_prose_only_enforcement() -> None:
    paragraph = _line_wrapping_paragraph(_text(GENERAL_MD)).lower()
    assert "sniff" in paragraph, (
        "general.md must record that no sniff can express a comment-specific "
        "width, so enforcement is by review"
    )
    assert "review" in paragraph


def test_general_md_motivated_line_breaks_bullet_survives_intact() -> None:
    text = _text(GENERAL_MD)
    assert (
        "**Motivated line breaks are fine.** Break an array literal across "
        "lines when its elements naturally form a list or matrix — lookup "
        "tables, observer thresholds, route definitions, fixture rows. "
        "Content-driven, not character-count-driven. Do not split a short "
        "call like `create_user( $name, $email, $role )`."
    ) in text, "the existing Motivated line breaks guidance must survive verbatim"


def test_php_md_has_no_120_column_cap() -> None:
    text = _text(PHP_MD)
    assert "120" not in text, "php.md must drop its 120-column code cap entirely"
    assert _OLD_PHP_LINE_WRAPPING not in text


def test_php_md_does_not_restate_the_comment_width_rule() -> None:
    text = _text(PHP_MD)
    assert "column 80" not in text, (
        "php.md must not restate the comment-width rule — general.md is now "
        "the single authoritative statement"
    )


def test_php_md_points_to_the_general_module_for_line_width() -> None:
    text = _text(PHP_MD).lower()
    assert "line wrapping" in text and "general module" in text, (
        "php.md must point to the general module's Line wrapping rules "
        "instead of duplicating them"
    )


def test_other_language_modules_carry_no_duplicated_width_rule() -> None:
    for name in OTHER_MODULES:
        text = _text(MODULES_DIR / name)
        assert "column 80" not in text, (
            f"{name} must not carry a duplicate of the comment-width rule"
        )
        assert "120" not in text, f"{name} must not carry a conflicting 120-cap"
