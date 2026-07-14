"""Tests for the cross-issue integration hotfix ("#32 <-> #33 interaction").

On the normal (non-empty) verifier-panel path, the per-issue reviewer's brief
explicitly checks "is the red demonstrated?" (``DEFAULT_LENSES`` in
``orchestrate.workflow.js``; SKILL.md's step 2). #32's empty-panel skip
(``buildAndVerify`` returning early when ``panel.length === 0``) removes that
reviewer entirely on the ``--max-lenses=0`` path — by design, the whole point
of the flag. #33 then documented, in both SKILL.md and ADR-0003, that "even
then red-before-green ... still hold[s]", justified by the claim that it is
"checked deterministically by ``orchestrate.py redgreen``, not by a lens, so
it holds even at 0".

That claim is false: the engine (``orchestrate.workflow.js``) never invokes
``orchestrate.py redgreen`` anywhere in the per-issue lifecycle, at any panel
size. ``redCommit``/``greenCommit`` are ``IMPLEMENT_SCHEMA`` fields the
implementer self-reports; nothing validates their presence or ordering. So at
``--max-lenses=0`` red-before-green is self-attested only, never independently
verified — the opposite of what the docs and the ADR present.

These tests assert the docs, the ADR, and the engine's own comment stop
overclaiming a deterministic/independent check that does not exist, and
instead say plainly what is true: the implementer still works test-first,
demonstrating red before green on its own; independent re-checking of that
demonstration — by a lens (at ``N >= 1``) or by ``orchestrate.py redgreen`` —
is exactly what ``--max-lenses=0`` drops, same as the rest of the panel.

Run with: `uv run --with pytest pytest -q`
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_MD = REPO_ROOT / "skills" / "orchestrate" / "SKILL.md"
ADR_0003 = REPO_ROOT / "docs" / "adr" / "0003-decoupling-rigor-from-the-level-dial.md"
WORKFLOW = REPO_ROOT / "skills" / "orchestrate" / "orchestrate.workflow.js"

# Phrases that assert a guarantee no code path actually provides. Neither may
# appear anywhere in the reconciled docs, ADR, or engine comment: the engine
# never calls `orchestrate.py redgreen` in the per-issue lifecycle, so
# red-before-green at `--max-lenses=0` is self-attested, never independently
# or deterministically re-checked.
_OVERCLAIM_PHRASES = (
    "checked deterministically",
    "red-before-green always holds",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _arguments_section(text: str) -> str:
    return text[text.index("## Arguments") : text.index("## The operating contract")]


def _max_lenses_argument_line(text: str) -> str:
    section = _arguments_section(text)
    for line in section.splitlines():
        if line.lstrip().startswith("- `--max-lenses=N`"):
            return line
    raise AssertionError("no --max-lenses=N argument bullet found in SKILL.md")


def _rigor_floor_line(text: str) -> str:
    section = text[text.index("## Model and effort") : text.index("## Running it unattended")]
    for line in section.splitlines():
        if "inviolable floor holds under everything" in line:
            return line
    raise AssertionError("no inviolable-floor bullet found in SKILL.md")


# The exact old phrasing that presented red-before-green as itself still
# independently upheld at N=0 — must not survive the reconciliation verbatim.
_SKILL_OLD_MAX_LENSES_CLAIM = (
    "test-first**, **red-before-green**, and the **mandatory integration "
    "review** all still hold"
)
_SKILL_OLD_FLOOR_CLAIM = (
    "even then red-before-green and the mandatory integration review still hold"
)


def test_skill_does_not_overclaim_redgreen_anywhere() -> None:
    text = _text(SKILL_MD).lower()
    for phrase in _OVERCLAIM_PHRASES:
        assert phrase not in text, (
            f"SKILL.md must not claim {phrase!r} — orchestrate.py redgreen is "
            "never invoked anywhere in the per-issue lifecycle, so the claim is false"
        )


def test_skill_max_lenses_argument_states_independent_rechecking_is_dropped() -> None:
    text = _text(SKILL_MD)
    line = _max_lenses_argument_line(text)
    lowered = line.lower()
    # Still names the practice the implementer keeps doing on its own.
    assert "test-first" in lowered
    assert "red-before-green" in lowered
    assert "integration review" in lowered and "mandatory" in lowered, (
        "the --max-lenses=0 case must still state the mandatory integration "
        "review holds"
    )
    # Must NOT claim red-before-green is itself still independently upheld —
    # only the mandatory integration review is a genuine per-run guarantee there.
    assert _SKILL_OLD_MAX_LENSES_CLAIM not in line, (
        "must not claim red-before-green is independently upheld at N=0 — say "
        "plainly that independent re-checking is what N=0 drops instead"
    )
    assert "self-attest" in lowered or "independent re-check" in lowered, (
        "the --max-lenses=0 case must say plainly that independent re-checking "
        "(or: red-before-green becomes self-attested) is what N=0 drops"
    )


def test_skill_floor_prose_states_independent_rechecking_is_dropped() -> None:
    text = _text(SKILL_MD)
    line = _rigor_floor_line(text)
    lowered = line.lower()
    assert "breachable only by an explicit `--max-lenses=0`" in lowered
    assert _SKILL_OLD_FLOOR_CLAIM not in lowered, (
        "must not claim red-before-green independently holds even at N=0 — "
        "nothing re-checks it there"
    )
    assert "self-attest" in lowered or "independent re-check" in lowered, (
        "the floor prose must say plainly that independent re-checking is what "
        "the N=0 breach drops, not that red-before-green still holds independently"
    )
    assert "mandatory integration review" in lowered


def test_skill_spine_paragraph_does_not_claim_redgreen_is_wired_in() -> None:
    text = _text(SKILL_MD)
    idx = text.index("The spine itself stays")
    paragraph = text[idx : idx + 1400]
    assert "is there a red-before-green commit (`orchestrate.py redgreen`)" not in paragraph, (
        "the spine paragraph must not present orchestrate.py redgreen as "
        "something the deterministic spine already runs per issue"
    )
    # The helper's existence and capability stay true — only the false "it is
    # already wired in" implication must go.
    assert "orchestrate.py redgreen" in text, (
        "the redgreen helper should still be named as available, just not "
        "claimed to run automatically per issue"
    )


def test_adr0003_does_not_overclaim_redgreen_wiring() -> None:
    text = _text(ADR_0003).lower()
    for phrase in _OVERCLAIM_PHRASES:
        assert phrase not in text, (
            f"ADR-0003 must not claim {phrase!r} — orchestrate.py redgreen is "
            "never invoked anywhere in the per-issue lifecycle"
        )


def test_adr0003_section2_states_self_attested_not_independently_checked() -> None:
    text = _text(ADR_0003)
    start = text.index("### 2. `--max-lenses=N`")
    end = text.index("### 3.")
    section = text[start:end].lower()
    assert "self-attest" in section, (
        "ADR-0003 §2 must state red-before-green is self-attested by the "
        "implementer at N=0, not independently re-checked"
    )
    assert "test-first" in section
    assert "mandatory integration review" in section


def test_workflow_comment_does_not_overclaim_redgreen_wiring() -> None:
    text = _text(WORKFLOW).lower()
    for phrase in _OVERCLAIM_PHRASES:
        assert phrase not in text, (
            f"orchestrate.workflow.js must not claim {phrase!r} in its "
            "buildAndVerify comment — nothing in the engine calls "
            "orchestrate.py redgreen"
        )
