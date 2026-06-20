"""Tests for the deterministic file work in scripts/scaffold.py.

The engine is a single-file `uv run` script under scripts/, not an installed
package, so it is loaded by path. The tests cover the three modes (create,
investigate, update), the four drift states, the hand-edit guard, the
conservative References reconcile, and the sanity/error paths — the logic the
script exists to make reliable.

Run with: `uv run --with pytest pytest -q`
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# Load scripts/scaffold.py by path, since it is a standalone script rather than
# an importable package.
_spec = importlib.util.spec_from_file_location(
    "scaffold", Path(__file__).resolve().parent.parent / "scripts" / "scaffold.py"
)
assert _spec is not None and _spec.loader is not None
scaffold = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = scaffold
_spec.loader.exec_module(scaffold)


# --- fixtures -----------------------------------------------------------------


@pytest.fixture
def modules_dir(tmp_path: Path) -> Path:
    """A source directory holding a minimal file for every known module."""

    src = tmp_path / "lib" / "coding-standard"
    src.mkdir(parents=True)
    for module in scaffold.CANONICAL_ORDER:
        (src / f"{module}.md").write_text(
            f"# {module} heading\n\nBody for {module}.\n", encoding="utf-8"
        )
    return src


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """A project root carrying a .git marker so the sanity check passes."""

    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    return root


def run(monkeypatch, project_dir: Path, modules_dir: Path, include: str, *flags: str) -> int:
    """Invoke the script's main() with the given arguments, returning its exit
    code."""

    argv = [
        "scaffold.py",
        "--project-dir", str(project_dir),
        "--modules-dir", str(modules_dir),
        "--include", include,
        *flags,
    ]
    monkeypatch.setattr(sys, "argv", argv)
    return scaffold.main()


def read_manifest(project_dir: Path) -> dict:
    return json.loads(scaffold.manifest_path(project_dir).read_text(encoding="utf-8"))


def out_file(project_dir: Path, module: str) -> Path:
    return project_dir / scaffold.OUTPUT_SUBDIR / f"{module}.md"


# --- create -------------------------------------------------------------------


def test_create_writes_modules_manifest_and_wiring(monkeypatch, project_dir, modules_dir):
    assert run(monkeypatch, project_dir, modules_dir, "php,wordpress") == 0

    # general is always included; the requested modules are present.
    for module in ("general", "php", "wordpress"):
        assert out_file(project_dir, module).exists()
    # typescript was not requested.
    assert not out_file(project_dir, "typescript").exists()

    # Manifest records each module's output hash.
    manifest = read_manifest(project_dir)
    assert manifest["manifestVersion"] == scaffold.MANIFEST_VERSION
    assert set(manifest["modules"]) == {"general", "php", "wordpress"}
    expected = scaffold.sha256_text(
        scaffold.build_module_file("php", (modules_dir / "php.md").read_text())
    )
    assert manifest["modules"]["php"] == expected

    # AGENTS.md points at each module; CLAUDE.md bridges.
    agents = (project_dir / "AGENTS.md").read_text()
    assert "agents.d/coding-standard/php.md" in agents
    assert (project_dir / "CLAUDE.md").read_text().startswith("@AGENTS.md")


def test_create_emits_override_header_for_wordpress(monkeypatch, project_dir, modules_dir):
    run(monkeypatch, project_dir, modules_dir, "wordpress")
    body = out_file(project_dir, "wordpress").read_text()
    assert "agents.d/coding-standard/php.md` first" in body
    assert scaffold.PRECEDENCE_LINE in body


def test_create_references_are_in_canonical_order(monkeypatch, project_dir, modules_dir):
    run(monkeypatch, project_dir, modules_dir, "wordpress,php")
    agents = (project_dir / "AGENTS.md").read_text()
    order = [agents.index(f"agents.d/coding-standard/{m}.md") for m in ("general", "php", "wordpress")]
    assert order == sorted(order)


def test_create_refuses_to_clobber_without_force(monkeypatch, project_dir, modules_dir):
    target = out_file(project_dir, "php")
    target.parent.mkdir(parents=True)
    target.write_text("hand-made\n", encoding="utf-8")
    assert run(monkeypatch, project_dir, modules_dir, "php") == 2
    assert target.read_text() == "hand-made\n"
    assert run(monkeypatch, project_dir, modules_dir, "php", "--force") == 0
    assert target.read_text() != "hand-made\n"


# --- investigate --------------------------------------------------------------


def test_investigate_reports_up_to_date_and_writes_nothing(
    monkeypatch, project_dir, modules_dir, capsys
):
    run(monkeypatch, project_dir, modules_dir, "php")
    capsys.readouterr()
    before = scaffold.manifest_path(project_dir).read_text()

    assert run(monkeypatch, project_dir, modules_dir, "php") == 0
    out = capsys.readouterr().out
    assert "Nothing to do" in out
    assert scaffold.manifest_path(project_dir).read_text() == before


def test_investigate_flags_update_available(monkeypatch, project_dir, modules_dir, capsys):
    run(monkeypatch, project_dir, modules_dir, "php")
    capsys.readouterr()
    (modules_dir / "php.md").write_text("# php\n\nNew rules.\n", encoding="utf-8")

    run(monkeypatch, project_dir, modules_dir, "php")
    out = capsys.readouterr().out
    assert "update available" in out


def test_investigate_flags_local_edit(monkeypatch, project_dir, modules_dir, capsys):
    run(monkeypatch, project_dir, modules_dir, "php")
    capsys.readouterr()
    out_file(project_dir, "php").write_text("edited by hand\n", encoding="utf-8")

    run(monkeypatch, project_dir, modules_dir, "php")
    out = capsys.readouterr().out
    assert "locally edited" in out
    assert "--force" in out


def test_investigate_flags_local_edit_and_update(monkeypatch, project_dir, modules_dir, capsys):
    run(monkeypatch, project_dir, modules_dir, "php")
    capsys.readouterr()
    out_file(project_dir, "php").write_text("edited by hand\n", encoding="utf-8")
    (modules_dir / "php.md").write_text("# php\n\nNew rules.\n", encoding="utf-8")

    run(monkeypatch, project_dir, modules_dir, "php")
    out = capsys.readouterr().out
    assert "locally edited + update available" in out


def test_investigate_reports_project_drift(monkeypatch, project_dir, modules_dir, capsys):
    run(monkeypatch, project_dir, modules_dir, "php,python")
    capsys.readouterr()

    # Drop python, add bash, in the fresh profile.
    run(monkeypatch, project_dir, modules_dir, "php,bash")
    out = capsys.readouterr().out
    assert "+ bash" in out
    assert "- python" in out


# --- update -------------------------------------------------------------------


def test_update_adds_new_module(monkeypatch, project_dir, modules_dir):
    run(monkeypatch, project_dir, modules_dir, "php")
    assert run(monkeypatch, project_dir, modules_dir, "php,python", "--update") == 0

    assert out_file(project_dir, "python").exists()
    assert "python" in read_manifest(project_dir)["modules"]
    assert "agents.d/coding-standard/python.md" in (project_dir / "AGENTS.md").read_text()


def test_update_removes_dropped_module_and_prunes_reference(monkeypatch, project_dir, modules_dir):
    run(monkeypatch, project_dir, modules_dir, "php,python")
    assert run(monkeypatch, project_dir, modules_dir, "php", "--update") == 0

    assert not out_file(project_dir, "python").exists()
    assert "python" not in read_manifest(project_dir)["modules"]
    assert "agents.d/coding-standard/python.md" not in (project_dir / "AGENTS.md").read_text()


def test_update_rewrites_changed_module(monkeypatch, project_dir, modules_dir):
    run(monkeypatch, project_dir, modules_dir, "php")
    before = read_manifest(project_dir)["modules"]["php"]
    (modules_dir / "php.md").write_text("# php\n\nNew rules.\n", encoding="utf-8")

    run(monkeypatch, project_dir, modules_dir, "php", "--update")
    assert "New rules." in out_file(project_dir, "php").read_text()
    assert read_manifest(project_dir)["modules"]["php"] != before


def test_update_protects_local_edits_then_force_overwrites(
    monkeypatch, project_dir, modules_dir, capsys
):
    run(monkeypatch, project_dir, modules_dir, "php")
    out_file(project_dir, "php").write_text("my edits\n", encoding="utf-8")
    (modules_dir / "php.md").write_text("# php\n\nNew rules.\n", encoding="utf-8")
    capsys.readouterr()

    # Without --force: the edited file is left untouched and reported.
    run(monkeypatch, project_dir, modules_dir, "php", "--update")
    assert out_file(project_dir, "php").read_text() == "my edits\n"
    assert "left untouched" in capsys.readouterr().out

    # With --force: it is overwritten with the current standard.
    run(monkeypatch, project_dir, modules_dir, "php", "--update", "--force")
    assert "New rules." in out_file(project_dir, "php").read_text()


def test_update_preserves_user_prose_in_agents_md(monkeypatch, project_dir, modules_dir):
    run(monkeypatch, project_dir, modules_dir, "php")
    agents_md = project_dir / "AGENTS.md"
    agents_md.write_text(agents_md.read_text() + "\n## Notes\n\nHand-written prose.\n")

    run(monkeypatch, project_dir, modules_dir, "php,python", "--update")
    text = agents_md.read_text()
    assert "Hand-written prose." in text
    assert "agents.d/coding-standard/python.md" in text


def test_update_with_no_changes_is_a_noop(monkeypatch, project_dir, modules_dir, capsys):
    run(monkeypatch, project_dir, modules_dir, "php")
    before = scaffold.manifest_path(project_dir).read_text()
    capsys.readouterr()

    assert run(monkeypatch, project_dir, modules_dir, "php", "--update") == 0
    assert "nothing to do" in capsys.readouterr().out.lower()
    assert scaffold.manifest_path(project_dir).read_text() == before


# --- sanity and errors --------------------------------------------------------


def test_refuses_non_project_directory_without_force(monkeypatch, tmp_path, modules_dir):
    bare = tmp_path / "bare"
    bare.mkdir()
    assert run(monkeypatch, bare, modules_dir, "php") == 1
    assert run(monkeypatch, bare, modules_dir, "php", "--force") == 0


def test_unknown_module_fails(monkeypatch, project_dir, modules_dir, capsys):
    assert run(monkeypatch, project_dir, modules_dir, "php,bogus") == 1
    assert "bogus" in capsys.readouterr().err


def test_missing_source_file_fails(monkeypatch, project_dir, modules_dir, capsys):
    (modules_dir / "php.md").unlink()
    assert run(monkeypatch, project_dir, modules_dir, "php") == 1
    assert "missing" in capsys.readouterr().err


def test_dry_run_writes_nothing(monkeypatch, project_dir, modules_dir):
    assert run(monkeypatch, project_dir, modules_dir, "php", "--dry-run") == 0
    assert not (project_dir / scaffold.OUTPUT_SUBDIR).exists()
    assert not (project_dir / "AGENTS.md").exists()
