"""Tests for the deterministic file work in scripts/scaffold.py.

The engine is a single-file `uv run` script under scripts/, not an installed
package, so it is loaded by path. The tests cover the three modes (create,
investigate, update) chosen by directory presence, the content-diff drift
report, the reconcile update (overwrite / add / remove + prune), prerequisite
closure, backticked References, and the sanity/error paths — the logic the
script exists to make reliable. The plugin owns the scaffolded files, so there
is no manifest and no local-edit protection to test.

Run with: `uv run --with pytest pytest -q`
"""

from __future__ import annotations

import importlib.util
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


def out_file(project_dir: Path, module: str) -> Path:
    return project_dir / scaffold.OUTPUT_SUBDIR / f"{module}.md"


# --- order_modules / prerequisite closure -------------------------------------


def test_order_modules_always_includes_general():
    assert scaffold.order_modules(["php"]) == ["general", "php"]


def test_order_modules_closes_wordpress_over_php():
    assert scaffold.order_modules(["wordpress"]) == ["general", "php", "wordpress"]


def test_order_modules_closes_block_transitively():
    # wordpress-block pulls in wordpress + typescript, and wordpress pulls in php.
    assert scaffold.order_modules(["wordpress-block"]) == [
        "general",
        "php",
        "wordpress",
        "typescript",
        "wordpress-block",
    ]


def test_order_modules_is_canonical_regardless_of_request_order():
    assert scaffold.order_modules(["bash", "php"]) == ["general", "php", "bash"]


def test_order_modules_rejects_unknown():
    with pytest.raises(ValueError):
        scaffold.order_modules(["bogus"])


# --- create -------------------------------------------------------------------


def test_create_writes_modules_and_wiring_without_manifest(monkeypatch, project_dir, modules_dir):
    assert run(monkeypatch, project_dir, modules_dir, "php,wordpress") == 0

    # general is always included; the closure adds php under wordpress.
    for module in ("general", "php", "wordpress"):
        assert out_file(project_dir, module).exists()
    # typescript was not requested or pulled in.
    assert not out_file(project_dir, "typescript").exists()

    # No private bookkeeping is written — the plugin owns the files verbatim.
    assert not (project_dir / scaffold.OUTPUT_SUBDIR / "manifest.json").exists()

    # AGENTS.md points at each module with a backticked path; CLAUDE.md bridges.
    agents = (project_dir / "AGENTS.md").read_text()
    assert "`agents.d/coding-standard/php.md`" in agents
    assert (project_dir / "CLAUDE.md").read_text().startswith("@AGENTS.md")


def test_create_emits_override_header_for_wordpress(monkeypatch, project_dir, modules_dir):
    run(monkeypatch, project_dir, modules_dir, "wordpress")
    body = out_file(project_dir, "wordpress").read_text()
    assert "agents.d/coding-standard/php.md` first" in body
    assert scaffold.PRECEDENCE_LINE in body


def test_create_references_are_backticked_and_in_canonical_order(monkeypatch, project_dir, modules_dir):
    run(monkeypatch, project_dir, modules_dir, "wordpress,php")
    agents = (project_dir / "AGENTS.md").read_text()
    for module in ("general", "php", "wordpress"):
        assert f"`agents.d/coding-standard/{module}.md`" in agents
    order = [agents.index(f"agents.d/coding-standard/{m}.md") for m in ("general", "php", "wordpress")]
    assert order == sorted(order)


def test_create_content_matches_build_module_file(monkeypatch, project_dir, modules_dir):
    run(monkeypatch, project_dir, modules_dir, "php")
    expected = scaffold.build_module_file("php", (modules_dir / "php.md").read_text())
    assert out_file(project_dir, "php").read_text() == expected


# --- mode detection -----------------------------------------------------------


def test_presence_of_a_module_file_selects_investigate(monkeypatch, project_dir, modules_dir, capsys):
    # First run creates; a module file now exists, so a bare re-run investigates.
    run(monkeypatch, project_dir, modules_dir, "php")
    capsys.readouterr()
    assert run(monkeypatch, project_dir, modules_dir, "php") == 0
    out = capsys.readouterr().out
    assert "investigate" in out.lower() or "up to date" in out.lower()
    # Investigate must not be a create — no "created" banner.
    assert "created coding standard" not in out


# --- investigate --------------------------------------------------------------


def test_investigate_reports_up_to_date_and_writes_nothing(
    monkeypatch, project_dir, modules_dir, capsys
):
    run(monkeypatch, project_dir, modules_dir, "php")
    capsys.readouterr()
    before = out_file(project_dir, "php").read_text()

    assert run(monkeypatch, project_dir, modules_dir, "php") == 0
    out = capsys.readouterr().out
    assert "up to date" in out
    assert "Nothing to do" in out
    assert out_file(project_dir, "php").read_text() == before


def test_investigate_flags_content_diff(monkeypatch, project_dir, modules_dir, capsys):
    run(monkeypatch, project_dir, modules_dir, "php")
    capsys.readouterr()
    # Editing the source so a fresh regeneration differs from the on-disk file.
    (modules_dir / "php.md").write_text("# php\n\nNew rules.\n", encoding="utf-8")

    run(monkeypatch, project_dir, modules_dir, "php")
    out = capsys.readouterr().out
    assert "differs (would be updated)" in out


def test_investigate_flags_on_disk_edit_as_differs(monkeypatch, project_dir, modules_dir, capsys):
    run(monkeypatch, project_dir, modules_dir, "php")
    capsys.readouterr()
    # Editing the scaffolded file also shows as a difference from the canonical.
    out_file(project_dir, "php").write_text("hand-edited\n", encoding="utf-8")

    run(monkeypatch, project_dir, modules_dir, "php")
    out = capsys.readouterr().out
    assert "differs (would be updated)" in out


def test_investigate_reports_project_drift(monkeypatch, project_dir, modules_dir, capsys):
    run(monkeypatch, project_dir, modules_dir, "php,python")
    capsys.readouterr()

    # Drop python, add bash, in the fresh profile.
    run(monkeypatch, project_dir, modules_dir, "php,bash")
    out = capsys.readouterr().out
    assert "+ bash" in out
    assert "− python" in out


def test_investigate_writes_nothing(monkeypatch, project_dir, modules_dir, capsys):
    run(monkeypatch, project_dir, modules_dir, "php")
    (modules_dir / "php.md").write_text("# php\n\nNew rules.\n", encoding="utf-8")
    capsys.readouterr()
    before = out_file(project_dir, "php").read_text()

    run(monkeypatch, project_dir, modules_dir, "php")
    assert out_file(project_dir, "php").read_text() == before


# --- update -------------------------------------------------------------------


def test_update_adds_new_module(monkeypatch, project_dir, modules_dir):
    run(monkeypatch, project_dir, modules_dir, "php")
    assert run(monkeypatch, project_dir, modules_dir, "php,python", "--update") == 0

    assert out_file(project_dir, "python").exists()
    assert "`agents.d/coding-standard/python.md`" in (project_dir / "AGENTS.md").read_text()


def test_update_removes_dropped_module_and_prunes_reference(monkeypatch, project_dir, modules_dir):
    run(monkeypatch, project_dir, modules_dir, "php,python")
    assert run(monkeypatch, project_dir, modules_dir, "php", "--update") == 0

    assert not out_file(project_dir, "python").exists()
    assert "agents.d/coding-standard/python.md" not in (project_dir / "AGENTS.md").read_text()


def test_update_rewrites_changed_module(monkeypatch, project_dir, modules_dir):
    run(monkeypatch, project_dir, modules_dir, "php")
    (modules_dir / "php.md").write_text("# php\n\nNew rules.\n", encoding="utf-8")

    run(monkeypatch, project_dir, modules_dir, "php", "--update")
    assert "New rules." in out_file(project_dir, "php").read_text()


def test_update_overwrites_on_disk_edit_no_protection(monkeypatch, project_dir, modules_dir):
    run(monkeypatch, project_dir, modules_dir, "php")
    out_file(project_dir, "php").write_text("my edits\n", encoding="utf-8")

    # The plugin owns the file: an edit is simply reconciled, no --force needed.
    run(monkeypatch, project_dir, modules_dir, "php", "--update")
    expected = scaffold.build_module_file("php", (modules_dir / "php.md").read_text())
    assert out_file(project_dir, "php").read_text() == expected


def test_update_preserves_user_prose_in_agents_md(monkeypatch, project_dir, modules_dir):
    run(monkeypatch, project_dir, modules_dir, "php")
    agents_md = project_dir / "AGENTS.md"
    agents_md.write_text(agents_md.read_text() + "\n## Notes\n\nHand-written prose.\n")

    run(monkeypatch, project_dir, modules_dir, "php,python", "--update")
    text = agents_md.read_text()
    assert "Hand-written prose." in text
    assert "`agents.d/coding-standard/python.md`" in text


def test_update_with_no_changes_is_a_noop(monkeypatch, project_dir, modules_dir, capsys):
    run(monkeypatch, project_dir, modules_dir, "php")
    before = out_file(project_dir, "php").read_text()
    capsys.readouterr()

    assert run(monkeypatch, project_dir, modules_dir, "php", "--update") == 0
    assert "nothing to do" in capsys.readouterr().out.lower()
    assert out_file(project_dir, "php").read_text() == before


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
