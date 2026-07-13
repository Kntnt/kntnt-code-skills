"""Tests for the deterministic file work in scripts/init.py.

The script is a single-file `uv run` tool under scripts/, loaded by path. The
tests cover the parts the skill hands off to it: the deduplicated `.gitignore`
compose, the template token substitution, the SPDX id mapping and URL builder,
and the per-licence placeholder rules — exercised on a fixture licence text so
no test touches the network.

Run with: `uv run --with pytest pytest -q`
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "init", REPO_ROOT / "scripts" / "init.py"
)
assert _spec is not None and _spec.loader is not None
init = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = init
_spec.loader.exec_module(init)


# --- gitignore compose --------------------------------------------------------


def test_compose_gitignore_dedupes_entries():
    base = "# base\n.DS_Store\n.env\n"
    typescript = "# Node\nnode_modules/\ndist/\n"
    block = "# Block\nnode_modules/\nbuild/\n"
    out = init.compose_gitignore(base, [typescript, block])

    # node_modules/ appears once even though two fragments declare it.
    assert out.count("node_modules/") == 1
    assert out.count("dist/") == 1
    assert "build/" in out
    # The base is preserved verbatim at the top.
    assert out.startswith("# base\n.DS_Store\n.env")


def test_compose_gitignore_drops_fully_redundant_fragment():
    base = "node_modules/\n"
    redundant = "# Node\nnode_modules/\n"
    out = init.compose_gitignore(base, [redundant])
    # Nothing new to add, so the fragment (header and all) is dropped.
    assert "# Node" not in out
    assert out.count("node_modules/") == 1


def test_read_gitignore_composes_real_fragments_deduped():
    gitignore_dir = REPO_ROOT / "lib" / "gitignore"
    out = init.read_gitignore(
        gitignore_dir, ["general", "php", "typescript", "wordpress-block", "python"]
    )
    # Shared entries across fragments are deduplicated.
    assert out.count("node_modules/") == 1
    assert out.count("build/") == 1
    assert out.count("dist/") == 1
    # php's /vendor/ and the base's .DS_Store both made it in.
    assert "/vendor/" in out
    assert ".DS_Store" in out


# --- token substitution -------------------------------------------------------


def test_substitute_replaces_known_tokens():
    template = "# {{PROJECT_NAME}} by {{OWNER}}\n{{DESCRIPTION}}\n"
    out = init.substitute(
        template, {"PROJECT_NAME": "foo", "OWNER": "Kntnt", "DESCRIPTION": "A tool."}
    )
    assert out == "# foo by Kntnt\nA tool.\n"


def test_substitute_leaves_unknown_tokens_untouched():
    out = init.substitute("{{KNOWN}} {{MYSTERY}}", {"KNOWN": "ok"})
    assert out == "ok {{MYSTERY}}"


# --- SPDX mapping and URL -----------------------------------------------------


@pytest.mark.parametrize(
    "picked,expected",
    [
        ("GPL-2.0", "GPL-2.0-only"),
        ("GPL-3.0", "GPL-3.0-only"),
        ("Apache-2.0", "Apache-2.0"),
        ("MIT-0", "MIT-0"),
        ("BSD-1-Clause", "BSD-1-Clause"),
    ],
)
def test_map_spdx(picked, expected):
    assert init.map_spdx(picked) == expected


def test_license_url_uses_mapped_id():
    assert init.license_url("GPL-3.0") == (
        "https://raw.githubusercontent.com/spdx/license-list-data/main/text/GPL-3.0-only.txt"
    )
    assert init.license_url("Apache-2.0").endswith("/Apache-2.0.txt")


# --- per-licence placeholder rules --------------------------------------------

FIXTURE_LICENSE = "Copyright <year> <copyright holders>\n\nPermission is granted...\n"


def test_postprocess_fills_placeholders_for_mit0():
    out = init.postprocess_license("MIT-0", FIXTURE_LICENSE, year="2026", owner="Kntnt")
    assert "<year>" not in out
    assert "<copyright holders>" not in out
    assert "Copyright 2026 Kntnt" in out


def test_postprocess_fills_placeholders_for_bsd1():
    out = init.postprocess_license(
        "BSD-1-Clause", FIXTURE_LICENSE, year="2026", owner="Kntnt"
    )
    assert "Copyright 2026 Kntnt" in out


def test_postprocess_leaves_apache_verbatim():
    out = init.postprocess_license(
        "Apache-2.0", FIXTURE_LICENSE, year="2026", owner="Kntnt"
    )
    assert out == FIXTURE_LICENSE


def test_postprocess_leaves_gpl_verbatim():
    out = init.postprocess_license(
        "GPL-3.0", FIXTURE_LICENSE, year="2026", owner="Kntnt"
    )
    assert out == FIXTURE_LICENSE


# --- inbound licensing wording ------------------------------------------------


def test_inbound_licensing_apache_cites_section_5():
    assert "§5" in init.inbound_licensing("Apache-2.0")


def test_inbound_licensing_non_apache_is_generic():
    text = init.inbound_licensing("MIT-0")
    assert "§5" not in text
    assert "project's licence" in text


# --- templates command (no network) -------------------------------------------


def test_templates_command_renders_and_writes(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    argv = [
        "templates",
        "--templates-dir",
        str(REPO_ROOT / "lib" / "templates"),
        "--project-dir",
        str(project),
        "--project-name",
        "demo",
        "--owner",
        "Kntnt",
        "--description",
        "A demo project.",
        "--author-name",
        "Thomas Barregren",
        "--author-url",
        "https://kntnt.com",
        "--year",
        "2026",
        "--date",
        "2026-06-26",
        "--spdx",
        "Apache-2.0",
    ]
    assert init.main(argv) == 0

    readme = (project / "README.md").read_text()
    assert "# demo" in readme
    assert "Kntnt/demo" in readme
    assert "the Apache License 2.0" in readme
    assert "{{" not in readme  # every token substituted

    contributing = (project / "CONTRIBUTING.md").read_text()
    assert "§5" in contributing  # Apache inbound-licensing wording

    # NOTICE is written for Apache.
    assert (project / "NOTICE").exists()
    assert "Copyright 2026 Thomas Barregren" in (project / "NOTICE").read_text()


def test_templates_command_skips_notice_for_non_apache(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    argv = [
        "templates",
        "--templates-dir",
        str(REPO_ROOT / "lib" / "templates"),
        "--project-dir",
        str(project),
        "--project-name",
        "demo",
        "--owner",
        "Kntnt",
        "--description",
        "A demo project.",
        "--author-name",
        "Thomas Barregren",
        "--author-url",
        "https://kntnt.com",
        "--year",
        "2026",
        "--date",
        "2026-06-26",
        "--spdx",
        "MIT-0",
    ]
    assert init.main(argv) == 0
    assert not (project / "NOTICE").exists()
    contributing = (project / "CONTRIBUTING.md").read_text()
    assert "§5" not in contributing


# --- gitignore command (no network) -------------------------------------------


def test_gitignore_command_writes_file(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    argv = [
        "gitignore",
        "--gitignore-dir",
        str(REPO_ROOT / "lib" / "gitignore"),
        "--include",
        "general,php,typescript",
        "--project-dir",
        str(project),
    ]
    assert init.main(argv) == 0
    content = (project / ".gitignore").read_text()
    assert "/vendor/" in content
    assert "node_modules/" in content
