#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Deterministic checks for the `doctor` skill — init's idempotent reconciler.

`doctor` re-checks a project against the same baseline `init` lays down and
proposes the fixes that bring it back into line. This script owns the cheap,
deterministic checks; the heavy, judgement-laden ones (does the README still
describe the real code? is each `agents.d/` file accurate?) run in the skill's
Workflow. The script writes nothing — it only reports — and emits its findings
as JSON so the skill can group them, prompt, and apply the fixes itself.

The checks:

  * **git** — is this a git repository, and is everything committed? Report-only;
    the remedy is `/push`, never an auto-commit.
  * **gitignore** — does `.gitignore` exist and cover the universal baseline plus
    the per-module fragment for each scaffolded coding-standard module?
  * **coding-standard** — is the standard in its correct home
    (`agents.d/coding-standard/`) rather than a stale `docs/coding-standard/` or
    monolithic `docs/coding-standards.md`, and is the scaffold in sync (delegated
    to `scaffold.py investigate`)?
  * **license** — is a `LICENSE` present, and under Apache, a `NOTICE` beside it?

Each finding is `{category, severity, message, remedy, auto_fixable}`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

OUTPUT_SUBDIR: str = "agents.d/coding-standard"

# Stale locations the coding standard must not live in — the correct home is
# agents.d/coding-standard/. Both forms are migration targets, not valid homes.
STALE_STANDARD_PATHS: tuple[str, ...] = (
    "docs/coding-standard",
    "docs/coding-standards.md",
)


def finding(
    category: str, severity: str, message: str, remedy: str, auto_fixable: bool
) -> dict:
    """Build one finding record."""

    return {
        "category": category,
        "severity": severity,
        "message": message,
        "remedy": remedy,
        "auto_fixable": auto_fixable,
    }


def gitignore_entries(text: str) -> set[str]:
    """The non-comment, non-blank entries declared in a `.gitignore`-shaped text."""

    return {
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def missing_gitignore_entries(
    gitignore_text: str, base_text: str, fragment_texts: list[str]
) -> list[str]:
    """Entries the baseline and the module fragments expect but `.gitignore` lacks.

    Coverage, not equality: the project may add its own entries; doctor only
    flags baseline/fragment entries that are absent. Order is preserved (base
    first, then fragments) and duplicates are collapsed.
    """

    present = gitignore_entries(gitignore_text)
    expected: list[str] = []
    seen: set[str] = set()
    for text in [base_text, *fragment_texts]:
        for line in text.splitlines():
            entry = line.strip()
            if entry and not entry.startswith("#") and entry not in seen:
                seen.add(entry)
                expected.append(entry)
    return [entry for entry in expected if entry not in present]


def scaffolded_module_stems(project_dir: Path) -> list[str]:
    """The coding-standard module stems already materialised in the project."""

    out_dir = project_dir / OUTPUT_SUBDIR
    if not out_dir.exists():
        return []
    return sorted(
        p.stem for p in out_dir.iterdir() if p.is_file() and p.suffix == ".md"
    )


def check_git(project_dir: Path) -> list[dict]:
    """git repo present and clean? Report-only — the remedy is `/push`."""

    findings: list[dict] = []
    inside = subprocess.run(
        ["git", "-C", str(project_dir), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
    )
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        findings.append(
            finding(
                "git",
                "high",
                "not a git repository",
                "run `git init` (or `/init` for a fresh project)",
                auto_fixable=False,
            )
        )
        return findings

    status = subprocess.run(
        ["git", "-C", str(project_dir), "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    if status.stdout.strip():
        findings.append(
            finding(
                "git",
                "low",
                "uncommitted changes in the working tree",
                "run `/push` to reconcile the changelog, commit, and push",
                auto_fixable=False,
            )
        )
    return findings


def check_gitignore(
    project_dir: Path, gitignore_dir: Path, modules: list[str]
) -> list[dict]:
    """`.gitignore` present and covering the baseline + the module fragments."""

    findings: list[dict] = []
    gitignore = project_dir / ".gitignore"
    if not gitignore.exists():
        findings.append(
            finding(
                "gitignore",
                "medium",
                "no .gitignore",
                "add one from lib/gitignore/base.txt plus the module fragments",
                auto_fixable=True,
            )
        )
        return findings

    base = (gitignore_dir / "base.txt").read_text(encoding="utf-8")
    fragment_texts: list[str] = []
    for module in modules:
        fragment = gitignore_dir / f"{module}.txt"
        if fragment.exists():
            fragment_texts.append(fragment.read_text(encoding="utf-8"))

    missing = missing_gitignore_entries(
        gitignore.read_text(encoding="utf-8"), base, fragment_texts
    )
    if missing:
        findings.append(
            finding(
                "gitignore",
                "low",
                f".gitignore is missing {len(missing)} expected entr"
                f"{'y' if len(missing) == 1 else 'ies'}: {', '.join(missing)}",
                "append the missing baseline/fragment entries",
                auto_fixable=True,
            )
        )
    return findings


def check_coding_standard(
    project_dir: Path, modules_dir: Path, modules: list[str]
) -> list[dict]:
    """Standard in its correct home and in sync.

    The inverted location check is deterministic; the in-sync check delegates to
    `scaffold.py investigate`, whose drift report is the source of truth.
    """

    findings: list[dict] = []

    # Inverted location check: the standard must live in agents.d/coding-standard/,
    # not under docs/.
    for stale in STALE_STANDARD_PATHS:
        if (project_dir / stale).exists():
            findings.append(
                finding(
                    "coding-standard",
                    "medium",
                    f"coding standard found at `{stale}` — the correct home is `{OUTPUT_SUBDIR}/`",
                    f"migrate `{stale}` to `{OUTPUT_SUBDIR}/` and re-point AGENTS.md References",
                    auto_fixable=True,
                )
            )

    # In-sync check: only meaningful once the project is scaffolded.
    if modules:
        scaffold = Path(__file__).resolve().parent / "scaffold.py"
        result = subprocess.run(
            [
                "uv",
                "run",
                str(scaffold),
                "--project-dir",
                str(project_dir),
                "--modules-dir",
                str(modules_dir),
                "--include",
                ",".join(modules),
            ],
            capture_output=True,
            text=True,
        )
        # scaffold.py prints exactly "… up to date. Nothing to do." when clean;
        # any other report (per-module "differs", "would be added/removed") is
        # drift. Keying on the all-clear sentinel avoids a false negative from a
        # single clean module's "up to date" line in a mixed report.
        report = result.stdout
        if result.returncode == 0 and "Nothing to do" not in report:
            findings.append(
                finding(
                    "coding-standard",
                    "low",
                    "scaffolded coding standard differs from the current standard",
                    "run `/coding-standard --update` to reconcile",
                    auto_fixable=True,
                )
            )
    return findings


def looks_apache(license_text: str) -> bool:
    """Whether a LICENSE text is the Apache License 2.0."""

    return "Apache License" in license_text and "Version 2.0" in license_text


def check_license(project_dir: Path) -> list[dict]:
    """`LICENSE` present, and `NOTICE` beside it under Apache."""

    findings: list[dict] = []
    license_file = project_dir / "LICENSE"
    if not license_file.exists():
        findings.append(
            finding(
                "license",
                "medium",
                "no LICENSE file",
                "choose a licence and add LICENSE (see `/init` step 6)",
                auto_fixable=False,
            )
        )
        return findings

    if (
        looks_apache(license_file.read_text(encoding="utf-8"))
        and not (project_dir / "NOTICE").exists()
    ):
        findings.append(
            finding(
                "license",
                "low",
                "Apache-2.0 LICENSE present but no NOTICE",
                "add a NOTICE with the copyright and attribution",
                auto_fixable=True,
            )
        )
    return findings


def run_checks(project_dir: Path, modules_dir: Path, gitignore_dir: Path) -> list[dict]:
    """Run every deterministic check and return the combined findings."""

    modules = scaffolded_module_stems(project_dir)
    findings: list[dict] = []
    findings += check_git(project_dir)
    findings += check_gitignore(project_dir, gitignore_dir, modules)
    findings += check_coding_standard(project_dir, modules_dir, modules)
    findings += check_license(project_dir)
    return findings


def main(argv: list[str] | None = None) -> int:
    """Run the deterministic checks and print findings as JSON. Exit 0 when clean,
    1 when any finding is produced, so a caller can gate on the exit code."""

    plugin_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(
        description="Deterministic checks for the doctor skill."
    )
    parser.add_argument("--project-dir", type=Path, default=Path("."))
    parser.add_argument(
        "--modules-dir",
        type=Path,
        default=plugin_root / "lib" / "coding-standard",
        help="The plugin's coding-standard module sources.",
    )
    parser.add_argument(
        "--gitignore-dir",
        type=Path,
        default=plugin_root / "lib" / "gitignore",
        help="The plugin's .gitignore baseline and fragments.",
    )
    args = parser.parse_args(argv)

    findings = run_checks(
        args.project_dir.resolve(),
        args.modules_dir.resolve(),
        args.gitignore_dir.resolve(),
    )
    print(json.dumps({"findings": findings}, indent=2))
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
