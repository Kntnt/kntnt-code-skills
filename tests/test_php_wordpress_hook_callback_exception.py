"""Guards for the hook-callback exception to first-class callable syntax (issue #42).

The PHP module's *Required modern features* mandate first-class callable
syntax (`$this->method(...)`) unconditionally. Applied to WordPress hook
registration, that syntax builds a fresh `Closure` at the call site whose
`_wp_filter_build_unique_id()` hook id is tied to that unreachable instance —
no other code can ever `remove_action()` / `remove_filter()` against it. The
array-callable form, `[ $this, 'method' ]`, stays individually removable and
is the correct choice there.

These tests read `lib/coding-standard/php.md` and `lib/coding-standard/
wordpress.md` as text and assert:

1. The PHP module's first-class-callable bullet carries the hook-callback
   exception — naming `add_action()`/`add_filter()`, the removability
   rationale (a `Closure` cannot be removed), and generalising to any
   registry where a callback must remain individually removable — while the
   syntax stays the default for immediate-consumption callables
   (`array_filter`/`array_map`/`usort`-style).
2. The WordPress module states the array-callable form is correct for hook
   registration, with the same removability rationale, so a WordPress-
   focused reader meets the rule in context without having to cross-read the
   PHP module.

Run with: `uv run --with pytest pytest -q`
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PHP_MD = REPO_ROOT / "lib" / "coding-standard" / "php.md"
WORDPRESS_MD = REPO_ROOT / "lib" / "coding-standard" / "wordpress.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _first_class_callable_bullet(text: str) -> str:
    """The single list-item line carrying the first-class-callable rule."""

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("-") and "first-class callable" in stripped.lower():
            return stripped
    raise AssertionError("no first-class-callable bullet found in php.md")


# --- php.md: the rule stays the default for immediate consumption -----------


def test_first_class_callable_still_the_default_for_immediate_consumption() -> None:
    bullet = _first_class_callable_bullet(_text(PHP_MD))
    lowered = bullet.lower()
    assert "first-class callable" in lowered
    # At least one immediate-consumption example survives (array_filter/array_map/usort).
    assert any(name in bullet for name in ("array_filter", "array_map", "usort"))


# --- php.md: the hook-callback exception -------------------------------------


def test_first_class_callable_bullet_names_add_action_and_add_filter() -> None:
    bullet = _first_class_callable_bullet(_text(PHP_MD))
    assert "add_action(" in bullet
    assert "add_filter(" in bullet


def test_first_class_callable_bullet_states_removability_rationale() -> None:
    bullet = _first_class_callable_bullet(_text(PHP_MD))
    lowered = bullet.lower()
    assert "closure" in lowered
    assert "remov" in lowered  # covers "removed", "removable", "removability"


def test_first_class_callable_bullet_generalises_beyond_wordpress_hooks() -> None:
    bullet = _first_class_callable_bullet(_text(PHP_MD))
    lowered = bullet.lower()
    assert "registry" in lowered


def test_first_class_callable_bullet_prescribes_the_array_callable_form() -> None:
    bullet = _first_class_callable_bullet(_text(PHP_MD))
    assert "[ $this, " in bullet or "[$this, " in bullet


# --- wordpress.md: the array-callable form is correct for hook registration -


def test_wordpress_md_states_array_callable_form_for_hook_registration() -> None:
    text = _text(WORDPRESS_MD)
    lowered = text.lower()
    assert "add_action(" in text or "add_filter(" in text
    assert "[ $this, " in text or "[$this, " in text
    assert "remov" in lowered  # the same removability rationale, not a bare rule restated


def test_wordpress_md_cross_references_the_php_module() -> None:
    text = _text(WORDPRESS_MD)
    # The rationale is stated once, authoritatively, in the PHP module; the
    # WordPress module should point back rather than duplicate it wholesale.
    assert "PHP" in text and ("first-class" in text.lower() or "PHP rules" in text or "PHP module" in text)
