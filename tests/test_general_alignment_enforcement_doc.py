"""Guards for the "no vertical alignment of `=` / `=>`" rule's enforcement note
(issue #38).

`lib/coding-standard/general.md` forbids vertical alignment, but nothing in
the phpcs ecosystem can enforce that prohibition — the sniffs that touch
`DoubleArrow`/`Equal` alignment (`Generic.Formatting.MultipleStatementAlignment`,
`WordPress.Arrays.MultipleStatementAlignment`) are one-directional: they can
only ever demand alignment, never forbid it. Every project therefore
*excludes* those sniffs, and aligned code passes phpcs silently. The triage
decision on #38 was prose-only, no sniff: the rule's own text must say so, so
"no tooling enforces this; review does" is a documented property rather than
a surprise a contributor discovers by reading phpcs.xml.dist.

These tests read the rule's own bullet in `general.md` and assert the
enforcement note is present, and that this repository's own dogfooded copy
under `agents.d/coding-standard/general.md` — materialised from the same
source by `scripts/scaffold.py` — never drifts from it.

Run with: `uv run --with pytest pytest -q`
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LIB_GENERAL = REPO_ROOT / "lib" / "coding-standard" / "general.md"
AGENTS_GENERAL = REPO_ROOT / "agents.d" / "coding-standard" / "general.md"

# Load scripts/scaffold.py by path, since it is a standalone script rather than
# an importable package.
_spec = importlib.util.spec_from_file_location(
    "scaffold", REPO_ROOT / "scripts" / "scaffold.py"
)
assert _spec is not None and _spec.loader is not None
scaffold = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = scaffold
_spec.loader.exec_module(scaffold)

# The bullet's fixed lead-in, and the marker that ends its block (the next
# bullet in the Whitespace list). Matching on these two anchors isolates the
# rule's own prose from the rest of the module, so the assertions below cannot
# be satisfied by unrelated text elsewhere in the file.
_BULLET_START = "No vertical alignment of `=` or `=>`"
_BULLET_END = "No padding inside short collections"


def _alignment_bullet(text: str) -> str:
    """The "No vertical alignment" bullet's full text, start bullet up to (not
    including) the next bullet. Fails loudly if either anchor is missing, so a
    rewording that drops the rule shows up as a clear assertion error rather
    than a silently empty match."""

    start = text.find(_BULLET_START)
    assert start != -1, f"'{_BULLET_START}' bullet not found in general.md"
    end = text.find(_BULLET_END, start)
    assert end != -1, f"'{_BULLET_END}' bullet not found after the alignment rule"
    return text[start:end]


def test_alignment_bullet_states_no_tooling_enforces_it() -> None:
    bullet = _alignment_bullet(LIB_GENERAL.read_text(encoding="utf-8"))
    assert re.search(r"no sniff\b.*enforces", bullet, flags=re.IGNORECASE), (
        f"the no-alignment rule must state that no sniff enforces it — got: {bullet!r}"
    )


def test_alignment_bullet_states_review_catches_it() -> None:
    bullet = _alignment_bullet(LIB_GENERAL.read_text(encoding="utf-8"))
    assert re.search(r"review catches", bullet, flags=re.IGNORECASE), (
        "the no-alignment rule must state that review (not tooling) catches "
        f"violations — got: {bullet!r}"
    )


def test_alignment_bullet_states_excluding_the_sniffs_is_expected() -> None:
    bullet = _alignment_bullet(LIB_GENERAL.read_text(encoding="utf-8"))
    assert re.search(r"exclud\w*", bullet, flags=re.IGNORECASE), (
        "the no-alignment rule must name excluding the alignment-demanding "
        f"sniffs as the expected posture — got: {bullet!r}"
    )
    assert re.search(r"expected|correct", bullet, flags=re.IGNORECASE), (
        "the no-alignment rule must characterise excluding those sniffs as "
        f"expected/correct, not a gap — got: {bullet!r}"
    )


def test_agents_d_general_md_matches_fresh_regeneration() -> None:
    """This repository dogfoods its own coding standard: `agents.d/coding-
    standard/general.md` is `scripts/scaffold.py`'s materialisation of `lib/
    coding-standard/general.md`. Editing the source without regenerating the
    scaffolded copy would leave a contributor reading `agents.d/` blind to the
    enforcement note — assert the two never drift."""

    lib_text = LIB_GENERAL.read_text(encoding="utf-8")
    fresh = scaffold.build_module_file("general", lib_text)
    on_disk = AGENTS_GENERAL.read_text(encoding="utf-8")
    assert on_disk == fresh, (
        "agents.d/coding-standard/general.md has drifted from a fresh "
        "regeneration of lib/coding-standard/general.md — run "
        "scripts/scaffold.py --update to reconcile"
    )
