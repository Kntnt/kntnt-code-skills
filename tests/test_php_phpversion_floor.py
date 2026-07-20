"""Guards for #43 — pin the declared PHP floor with PHPStan's `phpVersion`;
do not reach for PHPCompatibility.

The PHP module requires declaring a PHP floor (`Requires PHP` header /
`composer.json`) and using modern language features fully, but named nothing
that checks the code against that declared floor — drift in either
direction went unnoticed. The reflex tool for this job, PHPCompatibility,
fails silently on modern PHP: its last stable release predates PHP 8.0, so
it passes 8.x-only syntax with zero findings, which is worse than no gate at
all because the check looks green.

Settled at triage (the issue's Agent Brief):

1. `php.md`'s *PHP tooling* section, beside the existing PHPStan bullet,
   now instructs pinning PHPStan's `phpVersion` to the project's declared
   floor and keeping the two in step, as the mechanism that actually
   enforces the floor — with `phpVersion` set, PHPStan reports any syntax
   newer than the floor as an ordinary, non-ignorable error, so a baseline
   file cannot bury it.
2. The same passage explicitly warns against PHPCompatibility's
   `testVersion` for this purpose, stating the reason: its last stable
   release predates PHP 8.0 and it passes modern syntax in silence.
3. Optionally, `wordpress.md` gains the companion note on
   `version_compare()` bootstrap guards: once `phpVersion` is pinned,
   PHPStan constant-folds such a guard, and `treatPhpDocTypesAsCertain:
   false` is the honest configuration when the guard defends against a host
   loading the plugin outside the activation path.

Out of scope (per the issue): mandating a `phpVersion` *range*, any CI
wiring in downstream projects, and detecting an over-declared floor.

These tests read `lib/coding-standard/php.md` and `lib/coding-standard/
wordpress.md` as text and assert the above structurally. Whether the prose
reads well as English, rather than merely containing the right substrings,
is a human editorial call.

Run with: `uv run --with pytest pytest -q`
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULES_DIR = REPO_ROOT / "lib" / "coding-standard"
PHP_MD = MODULES_DIR / "php.md"
WORDPRESS_MD = MODULES_DIR / "wordpress.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tooling_section(text: str) -> str:
    """The "### PHP tooling" section, up to the next heading or EOF."""

    start = text.index("### PHP tooling")
    rest = text[start + len("### PHP tooling") :]
    end_markers = [m for m in ("\n## ", "\n### ") if m in rest]
    if not end_markers:
        return text[start:]
    end = min(rest.index(m) for m in end_markers)
    return text[start : start + len("### PHP tooling") + end]


def _phpstan_bullet(section: str) -> str:
    """The single list-item paragraph carrying the PHPStan rule.

    A bullet may wrap onto continuation lines that are not themselves
    `- **Tool**` bullets, so this collects every line from the `- **PHPStan**`
    line up to (but excluding) the next top-level `- **` bullet.
    """

    lines = section.splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.strip().startswith("- **PHPStan**")
    )
    end = start + 1
    while end < len(lines) and not lines[end].strip().startswith("- **"):
        end += 1
    return "\n".join(lines[start:end])


# --- php.md: phpVersion pins the declared floor ------------------------------


def test_phpstan_bullet_instructs_pinning_php_version() -> None:
    bullet = _phpstan_bullet(_tooling_section(_text(PHP_MD)))
    assert "phpVersion" in bullet, (
        "the PHPStan bullet must instruct setting PHPStan's `phpVersion` "
        "config option"
    )


def test_phpstan_bullet_names_the_declared_floor_sources() -> None:
    bullet = _phpstan_bullet(_tooling_section(_text(PHP_MD)))
    assert "Requires PHP" in bullet, (
        "the bullet must name the `Requires PHP` header as one place the "
        "floor is declared"
    )
    assert "composer.json" in bullet, (
        "the bullet must name `composer.json` as the other place the floor "
        "is declared"
    )


def test_phpstan_bullet_instructs_keeping_the_two_in_step() -> None:
    bullet = _phpstan_bullet(_tooling_section(_text(PHP_MD))).lower()
    assert "in step" in bullet or "in sync" in bullet, (
        "the bullet must instruct keeping the declared floor and "
        "`phpVersion` in step with each other"
    )


def test_phpstan_bullet_states_non_ignorable_enforcement_mechanism() -> None:
    bullet = _phpstan_bullet(_tooling_section(_text(PHP_MD))).lower()
    assert "non-ignorable" in bullet or "cannot" in bullet, (
        "the bullet must state that a pinned `phpVersion` makes newer-than-"
        "floor syntax a non-ignorable finding — the actual enforcement "
        "mechanism, not just a config knob"
    )
    assert "baseline" in bullet, (
        "the bullet must explicitly name the PHPStan baseline file as the "
        "thing that cannot bury this finding"
    )


# --- php.md: the anti-PHPCompatibility warning --------------------------------


def test_phpstan_bullet_warns_against_phpcompatibility_testversion() -> None:
    bullet = _phpstan_bullet(_tooling_section(_text(PHP_MD)))
    assert "PHPCompatibility" in bullet, (
        "the passage must explicitly name PHPCompatibility as the tool to "
        "avoid for floor-checking"
    )
    assert "testVersion" in bullet, (
        "the passage must name PHPCompatibility's `testVersion` option "
        "specifically — that is the mechanism being warned against"
    )


def test_phpcompatibility_warning_states_the_reason() -> None:
    bullet = _phpstan_bullet(_tooling_section(_text(PHP_MD))).lower()
    assert "8.0" in bullet, (
        "the warning must state the reason: PHPCompatibility's last stable "
        "release predates PHP 8.0"
    )
    assert "silen" in bullet, (
        "the warning must state that PHPCompatibility passes modern syntax "
        "silently (covers 'silence' / 'silently')"
    )


def test_phpstan_bullet_still_carries_its_prior_rationale() -> None:
    # The pre-existing "only automated check" rationale must survive —
    # this issue extends the bullet, it does not replace it.
    bullet = _phpstan_bullet(_tooling_section(_text(PHP_MD))).lower()
    assert "only automated check" in bullet
    assert "--level max" in bullet or "level max" in bullet


# --- wordpress.md: the optional bootstrap-guard note --------------------------


def test_wordpress_md_documents_version_compare_bootstrap_guard_interaction() -> None:
    text = _text(WORDPRESS_MD)
    lowered = text.lower()
    assert "version_compare" in text, (
        "wordpress.md must name `version_compare()` as the bootstrap-guard "
        "construct affected by pinning `phpVersion`"
    )
    assert "phpVersion" in text, (
        "wordpress.md must connect the guard back to the `phpVersion` "
        "setting from the PHP module"
    )
    assert "constant" in lowered, (
        "wordpress.md must state that PHPStan constant-folds the guard "
        "once `phpVersion` is pinned"
    )


def test_wordpress_md_names_treat_php_doc_types_as_certain_false() -> None:
    text = _text(WORDPRESS_MD)
    assert "treatPhpDocTypesAsCertain" in text, (
        "wordpress.md must name the `treatPhpDocTypesAsCertain` PHPStan "
        "option as the honest fix for a guard meant to stay a live check"
    )
    assert "false" in text.lower()
