#!/usr/bin/env python3
"""
Scaffold Thomas Barregren's coding standard into a project.

Concatenates the requested module files from this skill into
``docs/coding-standards.md`` and wires the import into ``CLAUDE.md``
(and optionally ``AGENTS.md``).

The skill's ``SKILL.md`` is the source of truth for which modules
exist and which apply to a given project. This script just executes
the file work — concatenation, file creation, surgical edits to
existing files — so the calling agent doesn't have to recreate the
logic every time.

Typical use:

    python3 scaffold.py \\
        --project-dir /path/to/new-project \\
        --skill-dir   /path/to/thomas-coder \\
        --include     php,wordpress,typescript,wordpress-block

Order on the command line does not matter; the canonical order is
imposed internally so override relationships stay correct.

Exit codes:

    0   Scaffolding completed successfully.
    1   Bad arguments, missing module file, or sanity-check failed.
    2   ``docs/coding-standards.md`` already exists in the project
        and was not overwritten. Stderr contains its first 20 lines
        so the caller can decide what to do.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Canonical order in which modules appear in the assembled
# coding-standards.md. Later entries override earlier ones on
# points where they differ — see SKILL.md, step 4 of the flow.
CANONICAL_ORDER: list[str] = [
    "general",
    "php",
    "wordpress",
    "typescript",
    "wordpress-block",
    "javascript-vanilla",
]

# Markers we accept as evidence that a directory is a real project,
# before we start writing files into it. The list is intentionally
# generous — if any one of these exists, the script proceeds.
PROJECT_MARKERS: list[str] = [
    ".git",
    "composer.json",
    "package.json",
]


def main() -> int:

    # Parse arguments.
    parser = argparse.ArgumentParser(
        description="Scaffold Thomas's coding standard into a project.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        required=True,
        help="Path to the project root.",
    )
    parser.add_argument(
        "--skill-dir",
        type=Path,
        required=True,
        help="Path to this skill's folder (where the module files live).",
    )
    parser.add_argument(
        "--include",
        required=True,
        help="Comma-separated module names to include "
             "(e.g. 'php,wordpress,typescript'). 'general' is always "
             "included whether or not it appears in this list.",
    )
    parser.add_argument(
        "--touch-agents-md",
        action="store_true",
        help="Also create or update AGENTS.md alongside CLAUDE.md.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without writing any files.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip the project-directory sanity check.",
    )
    args = parser.parse_args()

    project_dir: Path = args.project_dir.resolve()
    skill_dir: Path = args.skill_dir.resolve()
    requested = [s.strip() for s in args.include.split(",") if s.strip()]

    # Sanity-check the project directory unless --force is set.
    # Refusing to write into a random directory protects Thomas
    # from typos.
    if not args.force:
        has_marker = any((project_dir / m).exists() for m in PROJECT_MARKERS)
        if not has_marker:
            print(
                f"error: {project_dir} doesn't look like a project root "
                f"(no {', '.join(PROJECT_MARKERS)}). Pass --force to "
                "override.",
                file=sys.stderr,
            )
            return 1

    # Validate the requested modules and put them in canonical order.
    unknown = [m for m in requested if m not in CANONICAL_ORDER]
    if unknown:
        print(
            f"error: unknown module(s): {', '.join(unknown)}. "
            f"Known modules: {', '.join(CANONICAL_ORDER)}.",
            file=sys.stderr,
        )
        return 1
    if "general" not in requested:
        requested.append("general")
    ordered = [m for m in CANONICAL_ORDER if m in requested]

    # Read each module from the skill folder. A missing file means
    # the skill itself is broken — fail loudly rather than silently
    # producing a half-baked standard.
    parts: list[str] = []
    for name in ordered:
        path = skill_dir / f"{name}.md"
        if not path.exists():
            print(f"error: module file missing: {path}", file=sys.stderr)
            return 1
        parts.append(path.read_text())

    coding_standards_text = "\n".join(parts).rstrip() + "\n"

    # Write or refuse-to-overwrite docs/coding-standards.md.
    target = project_dir / "docs" / "coding-standards.md"
    if target.exists():
        head = "\n".join(target.read_text().splitlines()[:20])
        print(
            f"existing docs/coding-standards.md found at {target}.\n"
            f"first 20 lines:\n---\n{head}\n---\n"
            "refusing to overwrite. Move it aside or pick a different "
            "directory.",
            file=sys.stderr,
        )
        return 2

    actions: list[str] = []
    if args.dry_run:
        actions.append(
            f"[dry-run] would write docs/coding-standards.md "
            f"({len(coding_standards_text)} bytes, modules: "
            f"{', '.join(ordered)})"
        )
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(coding_standards_text)
        actions.append(
            f"wrote docs/coding-standards.md "
            f"({len(ordered)} modules: {', '.join(ordered)})"
        )

    # Touch CLAUDE.md and (optionally) AGENTS.md.
    template_path = skill_dir / "templates" / "claude-md-template.md"
    if not template_path.exists():
        print(
            f"error: CLAUDE.md template missing: {template_path}",
            file=sys.stderr,
        )
        return 1
    template_text = template_path.read_text()

    agent_files: list[tuple[str, str]] = [("CLAUDE.md", "# CLAUDE.md")]
    if args.touch_agents_md:
        agent_files.append(("AGENTS.md", "# AGENTS.md"))

    for filename, h1 in agent_files:
        agent_file = project_dir / filename

        # Case A: the file doesn't exist yet — copy the template and
        # rewrite the H1 if needed.
        if not agent_file.exists():
            content = template_text
            if filename != "CLAUDE.md":
                content = content.replace("# CLAUDE.md", h1, 1)
            if args.dry_run:
                actions.append(f"[dry-run] would create {filename}")
            else:
                agent_file.write_text(content)
                actions.append(f"created {filename}")
            continue

        # Case B: the file exists and already imports the standard —
        # leave it alone.
        existing = agent_file.read_text()
        if "@docs/coding-standards.md" in existing:
            actions.append(
                f"{filename} already imports coding-standards.md (skipped)"
            )
            continue

        # Case C: the file exists but doesn't import the standard —
        # insert the import surgically.
        updated = insert_import(existing)
        if args.dry_run:
            actions.append(f"[dry-run] would update {filename}")
        else:
            agent_file.write_text(updated)
            actions.append(f"updated {filename}")

    # Report. One line per action so the calling agent can quote the
    # output back to Thomas verbatim.
    print("scaffold complete:")
    for action in actions:
        print(f"  - {action}")
    return 0


def insert_import(content: str) -> str:
    """Insert ``@docs/coding-standards.md`` into a CLAUDE.md / AGENTS.md.

    Strategy, in order:

    1. If a ``## Coding standards`` heading already exists, append
       the import on the line after it.
    2. Otherwise, insert both the heading and the import after the
       first H1 (and any introductory paragraph that follows it).
    3. If there is no H1 at all, append the heading and the import
       at the end.

    Existing content is preserved otherwise.
    """

    lines = content.splitlines()

    # Strategy 1: existing "## Coding standards" heading.
    for i, line in enumerate(lines):
        if line.strip().lower() == "## coding standards":
            insert_at = i + 1
            if insert_at < len(lines) and lines[insert_at].strip() == "":
                insert_at += 1
            # Add a trailing blank only if the next existing line
            # isn't already blank — avoids double-blank lines that
            # look ugly in editors.
            to_insert = ["@docs/coding-standards.md"]
            next_line = lines[insert_at] if insert_at < len(lines) else None
            if next_line is None or next_line.strip() != "":
                to_insert.append("")
            for j, value in enumerate(to_insert):
                lines.insert(insert_at + j, value)
            return "\n".join(lines).rstrip() + "\n"

    # Strategy 2: no heading; find a place after the first H1 and
    # any introductory paragraph to insert one.
    h1_idx = next(
        (i for i, line in enumerate(lines) if line.startswith("# ")),
        -1,
    )
    if h1_idx == -1:
        # Strategy 3: no H1 either; append at the end.
        return (
            content.rstrip()
            + "\n\n## Coding standards\n\n@docs/coding-standards.md\n"
        )

    # Skip blank lines after the H1, then skip the intro paragraph
    # if there is one (a contiguous block of non-blank, non-heading
    # lines).
    insert_at = h1_idx + 1
    while insert_at < len(lines) and lines[insert_at].strip() == "":
        insert_at += 1
    while (
        insert_at < len(lines)
        and lines[insert_at].strip() != ""
        and not lines[insert_at].startswith("#")
    ):
        insert_at += 1

    # The insertion point is either at end-of-file or just before a
    # blank line / heading. Drop the trailing blank from new_section
    # when the next line is already blank, so we don't end up with
    # two blank lines in a row.
    new_section = ["", "## Coding standards", "", "@docs/coding-standards.md", ""]
    next_existing = lines[insert_at] if insert_at < len(lines) else None
    if next_existing is not None and next_existing.strip() == "":
        new_section = new_section[:-1]
    lines[insert_at:insert_at] = new_section
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    sys.exit(main())
