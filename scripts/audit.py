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
SKILL_DIR: Path = REPO_ROOT / "skills" / "coder"
SKILL_MD: Path = SKILL_DIR / "SKILL.md"
SCAFFOLD: Path = SKILL_DIR / "bin" / "scaffold"
PLUGIN_JSON: Path = REPO_ROOT / ".claude-plugin" / "plugin.json"
CHANGELOG: Path = REPO_ROOT / "CHANGELOG.md"


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
    """The set of topic-module stems in skills/coder/ — every `*.md` except
    SKILL.md, which is the router rather than a module."""

    if not SKILL_DIR.exists():
        return set()
    return {
        p.stem
        for p in SKILL_DIR.iterdir()
        if p.is_file() and p.suffix == ".md" and p.name != "SKILL.md"
    }


def canonical_order() -> list[str] | None:
    """Extract the `CANONICAL_ORDER` array from bin/scaffold. Returns None when
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


def frontmatter_version(text: str) -> str | None:
    """The `version:` value from a markdown file's YAML frontmatter, read with
    a flat regex so the audit needs no YAML dependency."""

    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    block = text[4:end]
    match = re.search(r"^version:\s*(.+?)\s*$", block, flags=re.MULTILINE)
    return match.group(1).strip().strip("'\"") if match else None


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
    """(b) — the topic-module files in skills/coder/ and bin/scaffold's
    `CANONICAL_ORDER` list the same modules. A module file with no entry would
    be invisible to the scaffolder; an entry with no file would make the
    scaffolder concatenate a missing file. Both directions are flagged."""

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
                relpath(SKILL_DIR / f"{stem}.md"),
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
                f"CANONICAL_ORDER entry '{stem}' has no module file in skills/coder/",
            )
        )
    return result


def check_skill_version_sync() -> CheckResult:
    """(c) — the `coder` skill's frontmatter `version` matches plugin.json.
    The skill and the plugin are released together; a drift here means a
    release updated one but not the other."""

    result = CheckResult(name="(c) SKILL.md version matches plugin.json")
    try:
        plugin_version = str(
            json.loads(read_text(PLUGIN_JSON)).get("version", "")
        ).strip()
    except json.JSONDecodeError:
        # The malformed-JSON case is already reported by check (a).
        return result
    skill_version = frontmatter_version(read_text(SKILL_MD))
    if skill_version is None:
        result.findings.append(
            Finding(
                result.name, relpath(SKILL_MD), None, "no version field in frontmatter"
            )
        )
    elif skill_version != plugin_version:
        result.findings.append(
            Finding(
                result.name,
                relpath(SKILL_MD),
                None,
                f"SKILL.md version '{skill_version}' does not match plugin.json version '{plugin_version}'",
            )
        )
    return result


CHECKS: tuple[Callable[[], CheckResult], ...] = (
    check_plugin_json_and_version,
    check_module_canonical_order_sync,
    check_skill_version_sync,
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
