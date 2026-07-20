"""Tests for the echo-manpage renderer in scripts/help.py.

`help.py` is deliberately dumb: it echoes ``docs/man/<skill>.md`` verbatim
rather than rendering anything, because Claude Code already renders
GitHub-flavoured Markdown in the terminal. These tests exercise the three
branches (overview, detail, unknown) against a temporary plugin-root fixture
that mirrors the real layout — ``.claude-plugin/plugin.json``, ``skills/*/SKILL.md``,
and ``docs/man/*.md`` — so they never depend on this repository's own manual
pages.

Run with: `uv run --with pytest pytest -q`
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, REPO_ROOT / "scripts" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


help_script = _load("help")


@pytest.fixture
def plugin_root(tmp_path: Path) -> Path:
    """A minimal plugin root: a manifest plus two skills, each with a
    ``SKILL.md`` and a matching ``docs/man/<skill>.md`` manual page."""

    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "kntnt-code-skills",
                "version": "9.9.9",
                "description": "A test plugin description.",
                "repository": "https://github.com/Kntnt/kntnt-code-skills",
            }
        ),
        encoding="utf-8",
    )

    for skill in ("alpha", "beta"):
        (tmp_path / "skills" / skill).mkdir(parents=True)
        (tmp_path / "skills" / skill / "SKILL.md").write_text(
            f"---\nname: {skill}\n---\n\n# {skill}\n", encoding="utf-8"
        )

    man_dir = tmp_path / "docs" / "man"
    man_dir.mkdir(parents=True)
    (man_dir / "alpha.md").write_text(
        "# alpha\n\n## NAME\n\n`alpha` — the first test skill\n\n## SYNOPSIS\n\n"
        "```\n/kntnt-code-skills:alpha\n```\n",
        encoding="utf-8",
    )
    (man_dir / "beta.md").write_text(
        "# beta\n\n## NAME\n\n`beta` — the second test skill\n\n## SYNOPSIS\n\n"
        "```\n/kntnt-code-skills:beta\n```\n",
        encoding="utf-8",
    )

    return tmp_path


# --- man_names / skill_names --------------------------------------------------


def test_man_names_lists_every_manual_page_alphabetically(plugin_root: Path) -> None:
    assert help_script.man_names(plugin_root) == ["alpha", "beta"]


def test_man_names_empty_when_man_dir_is_missing(tmp_path: Path) -> None:
    assert help_script.man_names(tmp_path) == []


def test_skill_names_excludes_command_pages(plugin_root: Path) -> None:
    (plugin_root / "docs" / "man" / "help.md").write_text(
        "# help\n\n## NAME\n\n`help` — the help command\n", encoding="utf-8"
    )
    assert help_script.skill_names(plugin_root) == ["alpha", "beta"]
    assert "help" in help_script.man_names(plugin_root)


# --- name_line -----------------------------------------------------------------


def test_name_line_reads_the_first_non_empty_line_after_name_heading(
    plugin_root: Path,
) -> None:
    assert (
        help_script.name_line(plugin_root, "alpha") == "`alpha` — the first test skill"
    )


def test_name_line_returns_empty_string_when_no_name_heading(tmp_path: Path) -> None:
    man_dir = tmp_path / "docs" / "man"
    man_dir.mkdir(parents=True)
    (man_dir / "bare.md").write_text(
        "# bare\n\nNo NAME section here.\n", encoding="utf-8"
    )
    assert help_script.name_line(tmp_path, "bare") == ""


# --- render_overview -------------------------------------------------------------


def test_render_overview_carries_header_blurb_and_every_name_line(
    plugin_root: Path,
) -> None:
    overview = help_script.render_overview(
        plugin_root, help_script.skill_names(plugin_root)
    )
    assert "kntnt-code-skills 9.9.9" in overview
    assert "https://github.com/Kntnt/kntnt-code-skills" in overview
    assert "A test plugin description." in overview
    assert "`alpha` — the first test skill" in overview
    assert "`beta` — the second test skill" in overview


def test_render_overview_points_at_the_detail_command(plugin_root: Path) -> None:
    overview = help_script.render_overview(
        plugin_root, help_script.skill_names(plugin_root)
    )
    assert "kntnt-code-skills:help <skill>" in overview


# --- render_detail ---------------------------------------------------------------


def test_render_detail_echoes_the_manual_page_verbatim(plugin_root: Path) -> None:
    expected = (
        (plugin_root / "docs" / "man" / "alpha.md")
        .read_text(encoding="utf-8")
        .rstrip("\n")
    )
    assert help_script.render_detail(plugin_root, "alpha") == expected


# --- render_unknown ----------------------------------------------------------------


def test_render_unknown_names_the_argument_and_lists_known_skills(
    plugin_root: Path,
) -> None:
    rendered = help_script.render_unknown("nope", help_script.skill_names(plugin_root))
    assert "nope" in rendered
    assert "alpha" in rendered
    assert "beta" in rendered


# --- main() dispatch, exercised as a subprocess ------------------------------------


def _run_main(plugin_root: Path, *args: str) -> str:
    env = dict(os.environ)
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "help.py"), *args],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return result.stdout


def test_main_with_no_argument_prints_the_overview(plugin_root: Path) -> None:
    out = _run_main(plugin_root)
    assert "Skills" in out
    assert "`alpha` — the first test skill" in out


def test_main_with_a_known_skill_prints_its_manual_page(plugin_root: Path) -> None:
    out = _run_main(plugin_root, "alpha")
    assert "## SYNOPSIS" in out
    assert "/kntnt-code-skills:alpha" in out


def test_main_with_an_unknown_skill_prints_the_error_line(plugin_root: Path) -> None:
    out = _run_main(plugin_root, "nonexistent")
    assert "nonexistent" in out
    assert "alpha" in out
