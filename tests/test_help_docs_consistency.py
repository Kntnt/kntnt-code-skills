"""Help/docs consistency test — bind the plugin's manual pages to reality (#45).

The manual pages under ``docs/man/`` are the single source of usage truth for
each skill. This repository has no separate flags registry (unlike the
reference model, ``kntnt-wp-skills``), so the only independent ground truth
for "is this flag real?" is each skill's own ``SKILL.md`` — specifically its
``## Arguments`` section where one exists. These tests fail the moment a
manual page and its skill's own source drift apart in either direction: a
manual page documenting a flag invented out of thin air, or omitting one the
skill's own ``## Arguments`` defines. They also bind the ``help`` overview to
each manual page's ``NAME`` line, the per-skill help-gate to ``scripts/help.py``,
and the README's manual-page links to real files.

Run with: `uv run --with pytest pytest -q`
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
MAN_DIR: Path = REPO_ROOT / "docs" / "man"
SKILLS_DIR: Path = REPO_ROOT / "skills"
README: Path = REPO_ROOT / "README.md"
COMMANDS_HELP: Path = REPO_ROOT / "commands" / "help.md"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, REPO_ROOT / "scripts" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


help_module = _load("help")

# The shape a manual page's NAME line must take: the skill's own name in
# backticks, a spaced em dash, then a non-empty summary — e.g.
# ``\`commit\` — reconcile the changelog``.
NAME_LINE_SHAPE: re.Pattern[str] = re.compile(r"^`([^`]+)` — \S")

# The help-gate's own three trigger tokens; always present, never counted as
# a skill-specific flag when checking for invented options.
HELP_GATE_TOKENS: frozenset[str] = frozenset({"help", "--help", "-h"})


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _skill_names() -> list[str]:
    """List the plugin's skills: every subdirectory of ``skills/`` that
    carries a ``SKILL.md``. This is the authoritative roster the manual pages
    must cover."""

    return sorted(d.name for d in SKILLS_DIR.iterdir() if (d / "SKILL.md").is_file())


def _base(token: str) -> str:
    """Reduce a flag token to its comparable base, stripping any ``=value`` or
    ``|choice`` suffix so ``--level=XS|S|M|L|XL`` and a bare ``--level``
    compare equal."""

    return re.split(r"[=|]", token, maxsplit=1)[0]


def _options_tokens(manpage_text: str) -> list[str]:
    """Extract every backtick-quoted token from a manual page's OPTIONS
    table's Option column (first column of each data row)."""

    lines = manpage_text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "## OPTIONS")
    rest = lines[start + 1 :]
    end = next((i for i, line in enumerate(rest) if line.startswith("## ")), len(rest))
    section = rest[:end]

    tokens: list[str] = []
    for line in section:
        if not line.lstrip().startswith("|"):
            continue
        first_cell = line.strip().strip("|").split("|")[0].strip()
        if first_cell.lower() == "option" or set(first_cell) <= {"-", ":", " "}:
            continue
        tokens += re.findall(r"`([^`]+)`", first_cell)
    return tokens


def _leading_argument_tokens(skill_md_text: str) -> list[str]:
    """Extract each ``## Arguments`` bullet's *leading* backtick token(s) —
    the flag(s) the bullet defines — never a backtick mentioned later in its
    prose (a bullet often cross-references a sibling flag by name).

    Returns an empty list for a skill whose ``SKILL.md`` carries no
    ``## Arguments`` section at all (a genuinely flag-less skill, e.g. `init`).
    """

    if "## Arguments" not in skill_md_text:
        return []

    section = skill_md_text.split("## Arguments", 1)[1].split("\n## ", 1)[0]
    leading = re.compile(r"^-\s*((?:`[^`]+`(?:\s*/\s*)?)+)", re.MULTILINE)

    tokens: list[str] = []
    for match in leading.finditer(section):
        tokens += re.findall(r"`([^`]+)`", match.group(1))
    return tokens


def _name_line(manpage: Path) -> str:
    """Read a manual page's NAME line straight from disk, independently of
    the ``help`` module under test — see the docstring in the reference
    model's own consistency test for why this must not call
    ``help.name_line`` itself (that would make the overview check
    tautological)."""

    lines = manpage.read_text(encoding="utf-8").splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.strip().lower() == "## name"), None
    )
    if start is None:
        return ""
    for line in lines[start + 1 :]:
        if line.strip():
            return line.strip()
    return ""


def _readme_manpage_links() -> list[str]:
    targets = re.findall(r"\]\(([^)]+)\)", _text(README))
    return [target for target in targets if "docs/man/" in target]


SKILLS: list[str] = _skill_names()
README_MANPAGE_LINKS: list[str] = _readme_manpage_links()


# --- every skill has a manual page --------------------------------------------


@pytest.mark.parametrize("skill", SKILLS)
def test_every_skill_has_a_manpage(skill: str) -> None:
    assert (MAN_DIR / f"{skill}.md").is_file(), f"skill {skill!r} has no manual page"


# --- no invented flags, no omitted ones ---------------------------------------


@pytest.mark.parametrize("skill", SKILLS)
def test_manpage_options_are_grounded_in_the_skills_own_source(skill: str) -> None:
    """Every flag a manual page documents (besides the universal help-gate
    tokens) must appear, base-for-base, as a real backtick-quoted token
    somewhere in that skill's own ``SKILL.md`` — never invented."""

    manpage_text = _text(MAN_DIR / f"{skill}.md")
    skill_md_text = _text(SKILLS_DIR / skill / "SKILL.md")

    documented = {_base(t) for t in _options_tokens(manpage_text)} - HELP_GATE_TOKENS
    invented = {base for base in documented if f"`{base}" not in skill_md_text}
    assert not invented, (
        f"{skill}.md documents flags absent from skills/{skill}/SKILL.md: "
        f"{sorted(invented)}"
    )


@pytest.mark.parametrize("skill", SKILLS)
def test_manpage_options_omit_no_argument_the_skill_defines(skill: str) -> None:
    """Every flag a skill's own ``## Arguments`` section defines must be
    documented in its manual page's OPTIONS table — never silently omitted."""

    manpage_text = _text(MAN_DIR / f"{skill}.md")
    skill_md_text = _text(SKILLS_DIR / skill / "SKILL.md")

    documented_bases = {_base(t) for t in _options_tokens(manpage_text)}
    for token in _leading_argument_tokens(skill_md_text):
        assert _base(token) in documented_bases, (
            f"skills/{skill}/SKILL.md's ## Arguments defines {token!r}, which "
            f"docs/man/{skill}.md's OPTIONS table omits"
        )


# --- the help gate ---------------------------------------------------------------


@pytest.mark.parametrize("skill", SKILLS)
def test_every_skill_has_a_help_gate(skill: str) -> None:
    """Every ``SKILL.md`` carries a help gate that dispatches to
    ``scripts/help.py`` with its own skill name, so `/<skill> --help` and
    `/kntnt-code-skills:help <skill>` reach the same manual page."""

    text = _text(SKILLS_DIR / skill / "SKILL.md")
    assert "## 0. Help gate" in text, f"skills/{skill}/SKILL.md has no help gate"
    assert f'scripts/help.py" {skill}' in text, (
        f"skills/{skill}/SKILL.md's help gate does not dispatch to "
        f"scripts/help.py {skill}"
    )
    for token in HELP_GATE_TOKENS:
        assert f"`{token}`" in text, (
            f"skills/{skill}/SKILL.md's help gate does not name `{token}`"
        )


# --- the overview carries every NAME line -------------------------------------


@pytest.mark.parametrize("skill", SKILLS)
def test_help_overview_carries_each_manpage_name_line(skill: str) -> None:
    name_line = _name_line(MAN_DIR / f"{skill}.md")

    assert name_line and not name_line.startswith("## "), (
        f"{skill}.md has no NAME-line body"
    )

    shape = NAME_LINE_SHAPE.match(name_line)
    assert shape and shape.group(1) == skill, (
        f"{skill}.md NAME line is malformed: {name_line!r}"
    )

    overview = help_module.render_overview(
        REPO_ROOT, help_module.skill_names(REPO_ROOT)
    )
    assert name_line in overview, f"overview omits the NAME line of {skill!r}"


# --- the /help command itself --------------------------------------------------


def test_help_command_runs_on_haiku() -> None:
    text = _text(COMMANDS_HELP)
    assert re.search(r"^model:\s*haiku\s*$", text, re.MULTILINE), (
        "commands/help.md must set 'model: haiku' — the turn is a pure "
        "verbatim echo (#45)"
    )


def test_help_command_does_not_wrap_output_in_an_outer_fence() -> None:
    text = _text(COMMANDS_HELP).lower()
    assert "do not wrap it in an outer code fence" in text or "do not wrap" in text, (
        "commands/help.md must instruct emitting the rendered help verbatim, "
        "not wrapped in an outer fenced code block (#45)"
    )
    assert "single triple-backtick fenced code block" not in text, (
        "commands/help.md still wraps the manpage output in an outer fence, "
        "which breaks its rendered Markdown (tables, headings, SYNOPSIS)"
    )


# --- README links resolve -------------------------------------------------------


def test_readme_links_to_the_manual_pages() -> None:
    assert README_MANPAGE_LINKS, "README references no manual pages under docs/man/"


def test_every_readme_manpage_link_resolves() -> None:
    unresolved = [
        link
        for link in README_MANPAGE_LINKS
        if not (REPO_ROOT / link.split("#", 1)[0]).is_file()
    ]
    assert not unresolved, f"README manpage links do not resolve: {unresolved}"
