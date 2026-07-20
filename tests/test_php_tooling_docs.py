"""Tests for #40 — the PHP tooling list contradicting general.md's own
YAGNI-first philosophy.

`lib/coding-standard/php.md`'s "PHP tooling" section mandated Pest, PHPStan,
and pcov as unconditional peer bullets. Two problems, settled at triage
(the issue's Agent Brief):

1. Pest was stated as though every PHP project owes it a test suite, with no
   reference to the general module's own TDD rule — "automate every test
   that can meaningfully constrain behaviour at the lowest layer that does"
   — which is the deciding question for whether tests are owed at all.
   PHPStan stays unconditional (its value is highest precisely where no
   test suite exists, because it is then the only automated check);
   Pest does not.

2. pcov is a PHP runtime extension (PECL / the PHP build / container
   config), not a Composer package — no project can declare it as a
   Composer dependency the way it declares Pest or PHPStan. Listing it as
   a peer bullet beside Composer-installable tools is a category error, and
   it is really the answer to a third, dependent question ("which coverage
   driver") riding under "measure coverage with Pest", not a peer of Pest
   or PHPStan.

These tests assert the reconciled section states its own proportionality
rule (defaults-when-applicable, TDD rule as decider), drops pcov as a peer
bullet in favour of a coverage clause folded into the Pest guidance that
names it a runtime extension, and keeps PHPStan unconditional with its
"only automated check" rationale.

Run with: `uv run --with pytest pytest -q`
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PHP_MD = REPO_ROOT / "lib" / "coding-standard" / "php.md"

# The exact TDD-decider phrase from general.md — the tooling section must
# name this as the deciding question, not restate its own criterion.
_TDD_DECIDER_PHRASE = "meaningfully constrain"


def _text() -> str:
    return PHP_MD.read_text(encoding="utf-8")


def _tooling_section(text: str) -> str:
    start = text.index("### PHP tooling")
    # The section runs to the next "## " or "### " heading, or EOF.
    rest = text[start + len("### PHP tooling") :]
    end_markers = [m for m in ("\n## ", "\n### ") if m in rest]
    if not end_markers:
        return text[start:]
    end = min(rest.index(m) for m in end_markers)
    return text[start : start + len("### PHP tooling") + end]


def _tooling_bullets(section: str) -> list[str]:
    return [
        line.strip()
        for line in section.splitlines()
        if line.strip().startswith("- **")
    ]


def test_tooling_section_names_tdd_rule_as_decider_for_pest() -> None:
    section = _tooling_section(_text())
    assert _TDD_DECIDER_PHRASE in section, (
        "the PHP tooling section must name the general module's TDD rule "
        f"({_TDD_DECIDER_PHRASE!r}) as the deciding question for whether a "
        "test suite is owed at all"
    )


def test_tooling_section_frames_itself_as_defaults_when_applicable() -> None:
    section = _tooling_section(_text()).lower()
    assert "default" in section, (
        "the PHP tooling section must frame its list as defaults-when-"
        "applicable, not an unconditional mandate — matching the DDEV "
        "bullet's existing conditionality pattern"
    )


def test_pest_bullet_is_conditional_not_a_blanket_mandate() -> None:
    section = _tooling_section(_text())
    bullets = _tooling_bullets(section)
    pest_bullets = [b for b in bullets if b.startswith("- **Pest**")]
    assert len(pest_bullets) == 1, "expected exactly one Pest bullet"
    pest_line = pest_bullets[0]
    # The old, unconditional phrasing must not survive verbatim.
    assert pest_line != "- **Pest** for unit and feature tests.", (
        "the Pest bullet must no longer read as an unconditional mandate"
    )
    assert _TDD_DECIDER_PHRASE in pest_line or "TDD" in pest_line, (
        "the Pest bullet itself must point at the TDD rule as the decider"
    )


def test_pcov_no_longer_appears_as_a_peer_tooling_bullet() -> None:
    section = _tooling_section(_text())
    bullets = _tooling_bullets(section)
    pcov_peer_bullets = [b for b in bullets if b.startswith("- **pcov**")]
    assert not pcov_peer_bullets, (
        "pcov must not appear as its own peer bullet in the tooling list — "
        "it is a PHP runtime extension, not a Composer-installable tool "
        "like Pest, PHPStan, or Composer itself"
    )


def test_pcov_over_xdebug_preference_survives_as_a_coverage_clause() -> None:
    section = _tooling_section(_text())
    assert "pcov" in section, (
        "the pcov-over-Xdebug preference must survive somewhere in the "
        "tooling section, folded into the testing guidance as a clause"
    )
    assert "Xdebug" in section, (
        "the coverage clause must still name Xdebug as the alternative "
        "pcov is preferred over"
    )
    lowered = section.lower()
    assert "runtime extension" in lowered or "php extension" in lowered, (
        "the coverage clause must identify pcov as a runtime extension, "
        "not a Composer package — the category error the issue raised"
    )


def test_phpstan_bullet_remains_unconditional_with_last_safety_net_rationale() -> (
    None
):
    section = _tooling_section(_text())
    bullets = _tooling_bullets(section)
    phpstan_bullets = [b for b in bullets if b.startswith("- **PHPStan**")]
    assert len(phpstan_bullets) == 1, "expected exactly one PHPStan bullet"
    phpstan_line = phpstan_bullets[0]
    # Unconditional: no gate on "if you have tests" or similar hedge.
    assert "when" not in phpstan_line.lower().split("phpstan")[0], (
        "PHPStan must remain an unconditional bullet, unlike Pest"
    )
    section_lower = section.lower()
    assert "no test suite" in section_lower or "without a test suite" in (
        section_lower
    ), (
        "PHPStan's rationale must state its value is highest precisely "
        "where no test suite exists"
    )
    assert "only automated" in section_lower, (
        "PHPStan's rationale must state it is then the only automated "
        "check — the 'last safety net' rationale from the Agent Brief"
    )


def test_composer_and_ddev_bullets_are_unchanged_peers() -> None:
    section = _tooling_section(_text())
    bullets = _tooling_bullets(section)
    assert any(b.startswith("- **Composer**") for b in bullets)
    assert any(b.startswith("- **DDEV**") for b in bullets)
