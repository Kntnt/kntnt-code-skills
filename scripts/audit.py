# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Audit script for kntnt-code-skills.

Runs every scriptable check from the README "Audit checklist". Cognitive
checks (whether a module's prose is genuinely self-contained, whether an
override relationship is stated clearly) stay manual.

Exit code 0 when no findings are produced; exit code 1 otherwise. A
tabulated report is written to stdout in both cases.

The script resolves the repository root from its own location
(scripts/audit.py), so `uv run scripts/audit.py` works from anywhere in
the worktree. Standard library only — no third-party dependencies, so the
PEP 723 block above pins only the Python version.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# Repository root resolved from this file's location: scripts/audit.py.
REPO_ROOT: Path = Path(__file__).resolve().parent.parent

# Directory and file shortcuts.
MODULES_DIR: Path = REPO_ROOT / "lib" / "coding-standard"
GITIGNORE_DIR: Path = REPO_ROOT / "lib" / "gitignore"
TEMPLATES_DIR: Path = REPO_ROOT / "lib" / "templates"
SKILLS_DIR: Path = REPO_ROOT / "skills"
SCAFFOLD: Path = REPO_ROOT / "scripts" / "scaffold.py"
PLUGIN_JSON: Path = REPO_ROOT / ".claude-plugin" / "plugin.json"
CHANGELOG: Path = REPO_ROOT / "CHANGELOG.md"

# The generic project templates that lib/templates/ must carry.
REQUIRED_TEMPLATES: tuple[str, ...] = ("README.md", "CHANGELOG.md", "CONTRIBUTING.md", "NOTICE")


@dataclass
class Finding:
    """One audit finding — path plus optional line plus message."""

    check: str
    path: str
    line: int | None
    message: str


@dataclass
class CheckResult:
    """The result of running one named check."""

    name: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings


def read_text(path: Path) -> str:
    """Read a UTF-8 text file. Returns empty string when the file is missing."""

    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def relpath(path: Path) -> str:
    """Repository-relative path for reporting."""

    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def module_files() -> set[str]:
    """The set of topic-module stems in lib/coding-standard/ — every `*.md`
    except files whose name starts with `_` (e.g. `_index.md`), which carry
    shared profiling knowledge rather than a materialisable module."""

    if not MODULES_DIR.exists():
        return set()
    return {
        p.stem
        for p in MODULES_DIR.iterdir()
        if p.is_file() and p.suffix == ".md" and not p.name.startswith("_")
    }


def frontmatter_name(skill_md: Path) -> str | None:
    """Extract the `name:` field from a SKILL.md's YAML frontmatter, or None."""

    lines = read_text(skill_md).splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = re.match(r"\s*name:\s*(.+?)\s*$", line)
        if match:
            return match.group(1).strip().strip("\"'")
    return None


def canonical_order() -> list[str] | None:
    """Extract the `CANONICAL_ORDER` array from scripts/scaffold.py. Returns None when
    the array cannot be located so the caller can report the structural
    problem rather than silently comparing against an empty list."""

    text = read_text(SCAFFOLD)
    # Tolerate an optional type annotation between the name and `=`
    # (e.g. `CANONICAL_ORDER: list[str] = [...]`) so the Python scaffold's
    # annotated declaration is matched as well as a bare assignment.
    match = re.search(
        r"CANONICAL_ORDER\s*(?::[^=]+)?=\s*\[(.*?)\]", text, flags=re.DOTALL
    )
    if match is None:
        return None
    return re.findall(r"['\"]([A-Za-z0-9_-]+)['\"]", match.group(1))


def latest_changelog_version() -> str | None:
    """The first non-`[Unreleased]` `## [version]` heading in the changelog,
    or None when no released heading exists."""

    pattern = re.compile(r"^## \[([^\]]+)\]", flags=re.MULTILINE)
    for match in pattern.finditer(read_text(CHANGELOG)):
        name = match.group(1)
        if name.lower() == "unreleased":
            continue
        return name
    return None


def check_plugin_json_and_version() -> CheckResult:
    """(a) — plugin.json is well-formed, carries the required fields, and its
    `version` matches the latest non-`[Unreleased]` heading in CHANGELOG.md."""

    result = CheckResult(name="(a) plugin.json shape and CHANGELOG version match")
    try:
        data = json.loads(read_text(PLUGIN_JSON))
    except json.JSONDecodeError as exc:
        result.findings.append(
            Finding(result.name, relpath(PLUGIN_JSON), None, f"invalid JSON: {exc}")
        )
        return result
    if not isinstance(data, dict):
        result.findings.append(
            Finding(result.name, relpath(PLUGIN_JSON), None, "root is not an object")
        )
        return result
    for required in ("name", "version", "description"):
        if required not in data:
            result.findings.append(
                Finding(
                    result.name,
                    relpath(PLUGIN_JSON),
                    None,
                    f"missing required field '{required}'",
                )
            )
    plugin_version = str(data.get("version", "")).strip()
    latest = latest_changelog_version()
    if latest is None:
        result.findings.append(
            Finding(
                result.name, relpath(CHANGELOG), None, "no non-Unreleased heading found"
            )
        )
    elif plugin_version != latest:
        result.findings.append(
            Finding(
                result.name,
                relpath(PLUGIN_JSON),
                None,
                f"plugin.json version '{plugin_version}' does not match latest CHANGELOG version '{latest}'",
            )
        )
    return result


def check_module_canonical_order_sync() -> CheckResult:
    """(b) — the topic-module files in lib/coding-standard/ and scripts/
    scaffold.py's `CANONICAL_ORDER` list the same modules. A module file with no
    entry would be invisible to the scaffolder; an entry with no file would make
    the scaffolder read a missing file. Both directions are flagged."""

    result = CheckResult(name="(b) modules <-> CANONICAL_ORDER symmetry")
    order = canonical_order()
    if order is None:
        result.findings.append(
            Finding(
                result.name,
                relpath(SCAFFOLD),
                None,
                "could not locate CANONICAL_ORDER array",
            )
        )
        return result
    order_set = set(order)
    files = module_files()
    for stem in sorted(files - order_set):
        result.findings.append(
            Finding(
                result.name,
                relpath(MODULES_DIR / f"{stem}.md"),
                None,
                f"module '{stem}' has no entry in CANONICAL_ORDER",
            )
        )
    for stem in sorted(order_set - files):
        result.findings.append(
            Finding(
                result.name,
                relpath(SCAFFOLD),
                None,
                f"CANONICAL_ORDER entry '{stem}' has no module file in lib/coding-standard/",
            )
        )
    return result


def check_skill_frontmatter() -> CheckResult:
    """(c) — every directory under skills/ carries a SKILL.md whose frontmatter
    `name` matches the directory name, so /help and invocation stay coherent.
    This is what brings new skills (init, doctor) under the audit."""

    result = CheckResult(name="(c) skills/ directories and SKILL.md names")
    if not SKILLS_DIR.exists():
        result.findings.append(
            Finding(result.name, relpath(SKILLS_DIR), None, "skills/ directory missing")
        )
        return result
    for skill_dir in sorted(d for d in SKILLS_DIR.iterdir() if d.is_dir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            result.findings.append(
                Finding(result.name, relpath(skill_md), None, "missing SKILL.md")
            )
            continue
        name = frontmatter_name(skill_md)
        if name is None:
            result.findings.append(
                Finding(result.name, relpath(skill_md), None, "no `name:` in frontmatter")
            )
        elif name != skill_dir.name:
            result.findings.append(
                Finding(
                    result.name,
                    relpath(skill_md),
                    None,
                    f"frontmatter name '{name}' does not match directory '{skill_dir.name}'",
                )
            )
    return result


def check_gitignore_fragments() -> CheckResult:
    """(d) — lib/gitignore/ carries base.txt and every other `<module>.txt`
    fragment names a module in CANONICAL_ORDER. A fragment for an unknown module
    would never be composed; a missing base.txt would break every compose."""

    result = CheckResult(name="(d) lib/gitignore/ fragments are sane")
    if not (GITIGNORE_DIR / "base.txt").is_file():
        result.findings.append(
            Finding(result.name, relpath(GITIGNORE_DIR / "base.txt"), None, "missing base.txt")
        )
    order = canonical_order()
    known = set(order) if order is not None else set()
    for fragment in sorted(GITIGNORE_DIR.glob("*.txt")) if GITIGNORE_DIR.exists() else []:
        if fragment.stem == "base":
            continue
        if known and fragment.stem not in known:
            result.findings.append(
                Finding(
                    result.name,
                    relpath(fragment),
                    None,
                    f"gitignore fragment '{fragment.stem}' is not a module in CANONICAL_ORDER",
                )
            )
    return result


def check_templates_present() -> CheckResult:
    """(e) — lib/templates/ carries the generic project templates init renders."""

    result = CheckResult(name="(e) lib/templates/ generic templates present")
    for name in REQUIRED_TEMPLATES:
        if not (TEMPLATES_DIR / name).is_file():
            result.findings.append(
                Finding(result.name, relpath(TEMPLATES_DIR / name), None, "missing template")
            )
    return result


CHECKS: tuple[Callable[[], CheckResult], ...] = (
    check_plugin_json_and_version,
    check_module_canonical_order_sync,
    check_skill_frontmatter,
    check_gitignore_fragments,
    check_templates_present,
)


def format_report(results: list[CheckResult]) -> str:
    """Render a tabulated summary followed by a per-failing-check detail block."""

    name_width = max(len(r.name) for r in results)
    status_width = len("STATUS")
    header = f"{'CHECK'.ljust(name_width)}  {'STATUS'.ljust(status_width)}  COUNT"
    separator = "-" * len(header)
    lines = [header, separator]
    for r in results:
        status = "OK" if r.ok else "FAIL"
        lines.append(
            f"{r.name.ljust(name_width)}  {status.ljust(status_width)}  {len(r.findings)}"
        )
    lines.append(separator)
    total = sum(len(r.findings) for r in results)
    lines.append(
        f"{'TOTAL FINDINGS'.ljust(name_width)}  {''.ljust(status_width)}  {total}"
    )
    failing = [r for r in results if not r.ok]
    if failing:
        lines.append("")
        lines.append("Findings:")
        for r in failing:
            lines.append("")
            lines.append(f"## {r.name}")
            for f in r.findings:
                location = f.path if f.line is None else f"{f.path}:{f.line}"
                lines.append(f"  - {location} — {f.message}")
    return "\n".join(lines)


def main() -> int:
    """Run every check, print the report, return 0 on a clean run else 1."""

    results = [check() for check in CHECKS]
    print(format_report(results))
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
