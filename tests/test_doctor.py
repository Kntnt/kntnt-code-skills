"""Tests for the deterministic checks in scripts/doctor.py.

The script is a single-file `uv run` tool under scripts/, loaded by path. The
tests cover the cheap checks the skill relies on: missing `.gitignore` entries,
a missing licence, the Apache/NOTICE pairing, the inverted-location check, and
the delegation to `scaffold.py investigate` for in-sync detection. They run on
temp fixture projects and the real `lib/` sources — no network, no GitHub.

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
MODULES_DIR = REPO_ROOT / "lib" / "coding-standard"
GITIGNORE_DIR = REPO_ROOT / "lib" / "gitignore"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, REPO_ROOT / "scripts" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


doctor = _load("doctor")
scaffold = _load("scaffold")


@pytest.fixture
def git_project(tmp_path: Path) -> Path:
    """A committed git project so the git check is quiet during other tests."""

    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "t@example.com"], check=True
    )
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    (root / "placeholder.txt").write_text("x\n")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "init"], check=True)
    return root


# --- git environment isolation (regression guard) -----------------------------


def test_git_env_leak_never_touches_the_target_repo(tmp_path: Path) -> None:
    """A pytest run under a leaked git environment must leave the pointed-at
    repository byte-for-byte unchanged.

    This reproduces the pre-commit hook leak that corrupted this repo twice: git
    hooks export GIT_DIR / GIT_INDEX_FILE / GIT_WORK_TREE into the environment
    of everything they run, and those outrank a fixture's `-C <tmpdir>`
    targeting, so an unscrubbed fixture runs its git init/add/commit against
    whatever they point at. A decoy repository stands in for the developer's
    real checkout; a child pytest runs both a fixture-backed test and a
    doctor.main invocation (which spawns its own git) with the leak exported,
    and only tests/conftest.py's autouse scrub stands between the leak and the
    decoy. Red before that scrub existed, green after.
    """

    # Seed a decoy repository standing in for the developer's real checkout.
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    subprocess.run(["git", "-C", str(decoy), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(decoy), "config", "user.email", "d@example.com"], check=True
    )
    subprocess.run(
        ["git", "-C", str(decoy), "config", "user.name", "Decoy"], check=True
    )
    (decoy / "keep.txt").write_text("keep\n")
    subprocess.run(["git", "-C", str(decoy), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(decoy), "commit", "-q", "-m", "seed"], check=True)

    # Snapshot the bytes the leak would corrupt: the index a stray `git add`
    # rewrites and the config a stray `git init` flips to core.bare=true.
    git_dir = decoy / ".git"
    config_before = (git_dir / "config").read_bytes()
    index_before = (git_dir / "index").read_bytes()

    # Export the location vars exactly as the pre-commit hook does, so a child
    # pytest inherits the leak and its conftest scrub is the only thing that can
    # spare the decoy.
    leaked = os.environ.copy()
    leaked["GIT_DIR"] = str(git_dir)
    leaked["GIT_INDEX_FILE"] = str(git_dir / "index")
    leaked["GIT_WORK_TREE"] = str(tmp_path)

    # Two nodes cover both leak surfaces — the fixture's own write-git, and
    # doctor.main's git subprocesses driven against a separate tmp project.
    test_file = REPO_ROOT / "tests" / "test_doctor.py"
    nodes = [
        f"{test_file}::test_check_gitignore_clean_when_covered",
        f"{test_file}::test_main_emits_valid_json",
    ]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *nodes],
        cwd=str(tmp_path),
        env=leaked,
        capture_output=True,
        text=True,
    )

    # The decoy's index and config must be byte-for-byte intact — the property
    # under test — and the child run must itself have stayed green.
    assert (git_dir / "index").read_bytes() == index_before, (
        "leak wrote the decoy index"
    )
    assert (git_dir / "config").read_bytes() == config_before, (
        "leak rewrote the decoy config"
    )
    assert result.returncode == 0, (
        f"child pytest failed:\n{result.stdout}\n{result.stderr}"
    )


def scaffold_standard(project_dir: Path, modules: list[str]) -> None:
    """Write canonical module files so an investigate run reports 'up to date'."""

    ordered = scaffold.order_modules(modules)
    out_dir = project_dir / scaffold.OUTPUT_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)
    for module in ordered:
        body = (MODULES_DIR / f"{module}.md").read_text(encoding="utf-8")
        (out_dir / f"{module}.md").write_text(
            scaffold.build_module_file(module, body), encoding="utf-8"
        )


# --- missing_gitignore_entries (pure) -----------------------------------------


def test_missing_entries_reports_absent_lines():
    missing = doctor.missing_gitignore_entries(
        ".DS_Store\n", "# base\n.DS_Store\n.env\n", ["# php\n/vendor/\n"]
    )
    assert ".env" in missing
    assert "/vendor/" in missing
    assert ".DS_Store" not in missing


def test_missing_entries_allows_extra_user_lines():
    missing = doctor.missing_gitignore_entries(
        ".DS_Store\n.env\nmy-secret/\n", "# base\n.DS_Store\n.env\n", []
    )
    assert missing == []


# --- check_gitignore ----------------------------------------------------------


def test_check_gitignore_flags_missing_file(git_project):
    findings = doctor.check_gitignore(git_project, GITIGNORE_DIR, [])
    assert any(
        f["category"] == "gitignore" and "no .gitignore" in f["message"]
        for f in findings
    )


def test_check_gitignore_flags_missing_fragment_entries(git_project):
    # Only the baseline; a php project also wants /vendor/.
    base = (GITIGNORE_DIR / "base.txt").read_text()
    (git_project / ".gitignore").write_text(base)
    findings = doctor.check_gitignore(git_project, GITIGNORE_DIR, ["php"])
    assert any("/vendor/" in f["message"] for f in findings)


def test_check_gitignore_clean_when_covered(git_project):
    base = (GITIGNORE_DIR / "base.txt").read_text()
    php = (GITIGNORE_DIR / "php.txt").read_text()
    (git_project / ".gitignore").write_text(base + "\n" + php)
    assert doctor.check_gitignore(git_project, GITIGNORE_DIR, ["php"]) == []


# --- check_license ------------------------------------------------------------


def test_check_license_flags_missing(git_project):
    findings = doctor.check_license(git_project)
    assert any("no LICENSE" in f["message"] for f in findings)


def test_check_license_flags_apache_without_notice(git_project):
    (git_project / "LICENSE").write_text("Apache License\nVersion 2.0, January 2004\n")
    findings = doctor.check_license(git_project)
    assert any("NOTICE" in f["message"] for f in findings)


def test_check_license_clean_with_apache_and_notice(git_project):
    (git_project / "LICENSE").write_text("Apache License\nVersion 2.0, January 2004\n")
    (git_project / "NOTICE").write_text("proj\nCopyright 2026\n")
    assert doctor.check_license(git_project) == []


def test_check_license_clean_with_non_apache(git_project):
    (git_project / "LICENSE").write_text("MIT No Attribution\n")
    assert doctor.check_license(git_project) == []


# --- check_coding_standard ----------------------------------------------------


def test_inverted_location_check_flags_docs_standard(git_project):
    (git_project / "docs").mkdir()
    (git_project / "docs" / "coding-standards.md").write_text(
        "old monolithic standard\n"
    )
    findings = doctor.check_coding_standard(git_project, MODULES_DIR, [])
    assert any("correct home" in f["message"] for f in findings)


def test_coding_standard_in_sync_has_no_drift_finding(git_project):
    scaffold_standard(git_project, ["php"])
    modules = doctor.scaffolded_module_stems(git_project)
    findings = doctor.check_coding_standard(git_project, MODULES_DIR, modules)
    assert not any("differs" in f["message"] for f in findings)


def test_coding_standard_drift_is_flagged(git_project):
    scaffold_standard(git_project, ["php"])
    # Hand-edit the scaffolded file so a fresh regeneration differs.
    (git_project / scaffold.OUTPUT_SUBDIR / "php.md").write_text("tampered\n")
    modules = doctor.scaffolded_module_stems(git_project)
    findings = doctor.check_coding_standard(git_project, MODULES_DIR, modules)
    assert any("differs" in f["message"] for f in findings)


# --- JSON output --------------------------------------------------------------


def test_main_emits_valid_json(git_project, capsys):
    code = doctor.main(
        [
            "--project-dir",
            str(git_project),
            "--modules-dir",
            str(MODULES_DIR),
            "--gitignore-dir",
            str(GITIGNORE_DIR),
        ]
    )
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert "findings" in parsed
    assert isinstance(parsed["findings"], list)
    # A bare git project with no LICENSE/.gitignore yields findings → exit 1.
    assert code == 1
