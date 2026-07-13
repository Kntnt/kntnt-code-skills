#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Materialise and maintain Kntnt's coding standard in a project.

Writes each requested module as its own on-demand file under
``agents.d/coding-standard/<module>.md``, ensures ``AGENTS.md`` carries a
``## References`` pointer to each one, and ensures ``CLAUDE.md`` bridges to
``AGENTS.md`` with ``@AGENTS.md``.

The standard is reached on demand: an agent follows a References pointer and
reads only the modules a task needs, rather than paying for the whole standard
on every session. Override modules (WordPress over PHP, Gutenberg blocks over
TypeScript) carry a generated prerequisite + precedence header so the override
resolves however the file is reached. That wiring lives in MODULE_META here, so
the source modules stay generic and portable.

The plugin OWNS these scaffolded files: they are canonical and verbatim, never
hand-edited. Project-specific deviations belong in ``AGENTS.md`` prose, not in
edits to a module file. There is therefore no private bookkeeping and no
"locally edited" state — drift is simply the content diff between the file on
disk and a fresh regeneration from the current ``lib/`` sources.

This script owns the deterministic, error-prone file work; the judgement —
which modules a project needs — stays with the calling skill, which always
passes the current profile via ``--include``. It runs in one of three modes,
chosen by whether the project is already scaffolded and the ``--update`` flag:

  * **create** — ``agents.d/coding-standard/`` holds no module file yet: write
    the modules and the wiring.
  * **investigate** — already scaffolded, no ``--update``: print a read-only
    drift report (which modules differ from a fresh regeneration, which would
    be added, which would be removed) and write nothing.
  * **update** — already scaffolded, ``--update`` given: reconcile to the
    current ``--include`` — rewrite every module whose content differs, add new
    ones, remove dropped ones, and prune their References.

A project is "scaffolded" exactly when ``agents.d/coding-standard/`` contains at
least one ``<module>.md`` for a known module; the directory's presence is the
mode marker.

Typical use:

    scripts/scaffold.py \\
        --project-dir  /path/to/project \\
        --modules-dir  /path/to/plugin/lib/coding-standard \\
        --include      php,wordpress,typescript,wordpress-block
        [--update] [--dry-run] [--force]

Order on the command line does not matter; the canonical order is imposed
internally so override relationships stay correct, and prerequisites are added
automatically (``wordpress`` pulls in ``php``; ``wordpress-block`` pulls in
``wordpress`` and ``typescript``; ``general`` is always present).

Exit codes:

    0   Completed successfully (create, investigate, or update).
    1   Bad arguments, missing module source file, or sanity-check failed.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NoReturn, TypedDict

# Canonical order. Later entries override earlier ones on points where they
# differ. The order is also the precedence order written into AGENTS.md's
# References list, so the "last listed wins" tie-break in the generated headers
# stays correct. Kept in step with lib/coding-standard/_index.md by hand.
CANONICAL_ORDER: list[str] = [
    "general",
    "php",
    "wordpress",
    "typescript",
    "wordpress-block",
    "javascript-vanilla",
    "python",
    "bash",
]


# Per-module wiring for the generated files. Keyed by module:
#   label      — human title in the generated H1.
#   read_when  — completes "Read before writing or changing <read_when>." in
#                both the file header and the AGENTS.md References line.
#   requires   — modules that must be read first because this one overrides or
#                builds on them; drives the prerequisite header and the
#                prerequisite closure. Empty for standalone modules.
class ModuleMeta(TypedDict):
    """The wiring for one module: its H1 label, its read-when phrase, and the
    modules it requires (read first because this one overrides or builds on
    them)."""

    label: str
    read_when: str
    requires: list[str]


MODULE_META: dict[str, ModuleMeta] = {
    "general": {"label": "General", "read_when": "any code", "requires": []},
    "php": {"label": "PHP", "read_when": "PHP", "requires": []},
    "wordpress": {
        "label": "WordPress",
        "read_when": "a WordPress plugin or theme",
        "requires": ["php"],
    },
    "typescript": {"label": "TypeScript", "read_when": "TypeScript", "requires": []},
    "wordpress-block": {
        "label": "WordPress Blocks",
        "read_when": "Gutenberg blocks",
        "requires": ["wordpress", "typescript"],
    },
    "javascript-vanilla": {
        "label": "Vanilla JavaScript",
        "read_when": "build-less browser JavaScript",
        "requires": [],
    },
    "python": {"label": "Python", "read_when": "Python", "requires": []},
    "bash": {"label": "Bash", "read_when": "Bash", "requires": []},
}

# Direct prerequisites per module, derived from MODULE_META so the two never
# drift. order_modules() closes over this transitively, so requesting
# `wordpress-block` materialises `wordpress`, `typescript`, and `php` too.
PREREQUISITES: dict[str, list[str]] = {
    name: list(meta["requires"]) for name, meta in MODULE_META.items()
}

# Override modules get a verbatim prerequisite sentence in their header — the
# wording reads naturally per module, so it is stored rather than generated
# from `requires`. Every module with a non-empty `requires` has an entry. The
# referenced siblings are named by their full project-relative path so the
# reader can open them directly.
OVERRIDE_HEADER: dict[str, str] = {
    "wordpress": (
        "Read `agents.d/coding-standard/php.md` first; the rules below override "
        "parts of it."
    ),
    "wordpress-block": (
        "Read `agents.d/coding-standard/wordpress.md` and "
        "`agents.d/coding-standard/typescript.md` first; the rules below "
        "override parts of TypeScript."
    ),
}

# Appended after the prerequisite line in every override module's header.
PRECEDENCE_LINE: str = (
    "On any conflict between this file and another, the file listed last in the "
    "References section of AGENTS.md wins."
)

# Markers we accept as evidence that a directory is a real project before
# writing into it. Generous — any one is enough.
PROJECT_MARKERS: list[str] = [".git", "composer.json", "package.json"]

# Where the standard is materialised inside a project. The directory is the
# namespace, so the module files drop the `coding-` prefix. Its presence (with
# at least one module file) is also how the script tells a scaffolded project
# from a fresh one.
OUTPUT_SUBDIR: str = "agents.d/coding-standard"

# Fail loudly if the maps drift from CANONICAL_ORDER — a new module added to
# CANONICAL_ORDER without MODULE_META (or vice versa) is a bug, not a silent
# half-configuration. OVERRIDE_HEADER must cover exactly the modules that
# declare a `requires` list.
assert set(MODULE_META) == set(CANONICAL_ORDER), (
    "MODULE_META and CANONICAL_ORDER are out of sync"
)
assert set(OVERRIDE_HEADER) == {
    name for name, meta in MODULE_META.items() if meta["requires"]
}, "OVERRIDE_HEADER must cover exactly the modules with a non-empty `requires`"

# Matches a coding-standard module reference in AGENTS.md, capturing the module
# name. Used to prune References for dropped modules during an update.
REFERENCE_RE = re.compile(r"agents\.d/coding-standard/([a-z0-9-]+)\.md")


class ScaffoldArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that exits with code 1 on a usage error.

    argparse's default is exit code 2; mapping usage errors to 1 keeps the
    bad-arguments case aligned with the script's other error path.
    """

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def references_line(module: str) -> str:
    """Build the AGENTS.md References bullet for a module — a pure pointer.

    The module path is backticked so it renders as code and the pointer is
    unambiguous. Prerequisite and precedence information lives in the module
    file's own generated header, so the References line carries no co-load
    note: one home for that knowledge, nothing here to go stale.
    """

    read_when = MODULE_META[module]["read_when"]
    return (
        f"- `{OUTPUT_SUBDIR}/{module}.md` — read before writing or changing {read_when}"
    )


def build_module_file(module: str, body: str) -> str:
    """Assemble the on-demand file for one module.

    The generated H1 + read-when line (and, for override modules, the
    prerequisite + precedence lines) sit above the module body. The module's own
    leading heading is dropped so the generated H1 is the sole title. The output
    is deterministic in (module, body), so comparing it to the file on disk is
    the whole of drift detection.
    """

    label = MODULE_META[module]["label"]
    read_when = MODULE_META[module]["read_when"]

    # Drop the module's own first heading and any surrounding blank lines; the
    # generated H1 replaces it.
    lines = body.splitlines()
    while lines and lines[0].strip() == "":
        lines.pop(0)
    if lines and lines[0].lstrip().startswith("#"):
        lines.pop(0)
    while lines and lines[0].strip() == "":
        lines.pop(0)
    stripped_body = "\n".join(lines).rstrip() + "\n"

    # Build the generated header: title, read-when, then the override block for
    # modules that have prerequisites.
    header = [
        f"# Coding standard — {label}",
        "",
        f"Read before writing or changing {read_when}.",
    ]
    if module in OVERRIDE_HEADER:
        header += ["", OVERRIDE_HEADER[module], "", PRECEDENCE_LINE]
    header += ["", ""]

    return "\n".join(header) + stripped_body


def order_modules(requested: list[str]) -> list[str]:
    """Validate requested modules, close over their prerequisites, and return
    them in canonical order — always including `general`.

    Requesting an override module pulls in everything it builds on: `wordpress`
    adds `php`; `wordpress-block` adds `wordpress`, `typescript`, and
    transitively `php`. Raises ValueError naming any unknown module.
    """

    unknown = [m for m in requested if m not in CANONICAL_ORDER]
    if unknown:
        raise ValueError(
            f"unknown module(s): {', '.join(unknown)}. "
            f"Known modules: {', '.join(CANONICAL_ORDER)}."
        )

    # Seed with the request plus the always-present general module, then pull in
    # each module's prerequisites transitively until the set stops growing.
    wanted = set(requested)
    wanted.add("general")
    queue = list(wanted)
    while queue:
        module = queue.pop()
        for prereq in PREREQUISITES.get(module, []):
            if prereq not in wanted:
                wanted.add(prereq)
                queue.append(prereq)

    return [m for m in CANONICAL_ORDER if m in wanted]


def read_source_bodies(modules_dir: Path, modules: list[str]) -> dict[str, str]:
    """Read each module's source body. A missing file means the plugin itself is
    broken — raise FileNotFoundError rather than producing a half-baked
    standard."""

    bodies: dict[str, str] = {}
    for module in modules:
        path = modules_dir / f"{module}.md"
        if not path.exists():
            raise FileNotFoundError(f"module source missing: {path}")
        bodies[module] = path.read_text(encoding="utf-8")
    return bodies


def scaffolded_modules(project_dir: Path) -> list[str]:
    """Known module stems already materialised under OUTPUT_SUBDIR, in canonical
    order. A non-empty result means the project is scaffolded, which selects
    investigate/update over create."""

    out_dir = project_dir / OUTPUT_SUBDIR
    if not out_dir.exists():
        return []
    return [m for m in CANONICAL_ORDER if (out_dir / f"{m}.md").exists()]


def sync_references(
    *, project_dir: Path, modules: list[str], prune: bool, dry_run: bool
) -> list[str]:
    """Reconcile AGENTS.md's References with `modules`, conservatively.

    Adds a pointer for any module not already referenced; when `prune` is set,
    removes pointers for coding-standard modules no longer in `modules`. Lines
    for kept modules are left exactly as they are — the user owns AGENTS.md's
    prose. Creates a minimal AGENTS.md (title + References) when missing, leaving
    the rest to /agents-md. Returns one action string per change.
    """

    agents_md = project_dir / "AGENTS.md"
    wanted = {module: references_line(module) for module in modules}

    # No AGENTS.md — write a minimal one. Deliberately not the rest of the file;
    # that is /agents-md's job.
    if not agents_md.exists():
        title = project_dir.name or "Project"
        body = "\n".join(wanted[module] for module in modules)
        if dry_run:
            return ["[dry-run] would create AGENTS.md with References"]
        agents_md.write_text(
            f"# {title}\n\n## References\n\n{body}\n", encoding="utf-8"
        )
        return [
            "created minimal AGENTS.md with References — run /agents-md to flesh it out"
        ]

    lines = agents_md.read_text(encoding="utf-8").splitlines()
    actions: list[str] = []

    # Prune References for dropped modules, matching on the file path so a line
    # the user reworded around the path is still recognised.
    if prune:
        kept = set(modules)
        pruned: list[str] = []
        for line in lines:
            match = REFERENCE_RE.search(line)
            if match and match.group(1) not in kept:
                actions.append(f"removed AGENTS.md reference to {match.group(1)}")
                continue
            pruned.append(line)
        lines = pruned

    # Add pointers for modules not yet referenced, in canonical order.
    joined = "\n".join(lines)
    missing = [wanted[m] for m in modules if f"{OUTPUT_SUBDIR}/{m}.md" not in joined]
    if missing:
        ref_index = next(
            (i for i, ln in enumerate(lines) if ln.strip().lower() == "## references"),
            -1,
        )
        if ref_index == -1:
            lines = (
                "\n".join(lines).rstrip().splitlines()
                + ["", "## References", ""]
                + missing
            )
            actions.append("added a References section to AGENTS.md")
        else:
            insert_at = ref_index + 1
            cursor = ref_index + 1
            while cursor < len(lines) and not lines[cursor].startswith("## "):
                if lines[cursor].strip():
                    insert_at = cursor + 1
                cursor += 1
            lines[insert_at:insert_at] = missing
            actions.append("added coding-standard pointers to AGENTS.md References")

    if actions and not dry_run:
        agents_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    elif actions and dry_run:
        actions = ["[dry-run] would update AGENTS.md References"]
    return actions


def ensure_bridge(*, project_dir: Path, dry_run: bool) -> list[str]:
    """Ensure CLAUDE.md imports AGENTS.md with ``@AGENTS.md``.

    Claude Code reads CLAUDE.md, not AGENTS.md; the bridge is what makes the
    References (and everything they point to) reachable.
    """

    claude_md = project_dir / "CLAUDE.md"

    if not claude_md.exists():
        if dry_run:
            return ["[dry-run] would create CLAUDE.md (@AGENTS.md bridge)"]
        claude_md.write_text("@AGENTS.md\n", encoding="utf-8")
        return ["created CLAUDE.md (@AGENTS.md bridge)"]

    existing = claude_md.read_text(encoding="utf-8")
    if "@AGENTS.md" in existing:
        return []

    if dry_run:
        return ["[dry-run] would add @AGENTS.md bridge to CLAUDE.md"]
    claude_md.write_text("@AGENTS.md\n\n" + existing.lstrip(), encoding="utf-8")
    return ["added @AGENTS.md bridge to CLAUDE.md"]


def do_create(
    *,
    project_dir: Path,
    modules: list[str],
    bodies: dict[str, str],
    dry_run: bool,
) -> int:
    """Create mode: nothing scaffolded yet. Write the modules and the wiring.

    There is nothing to clobber — a present module file would have selected
    investigate/update instead — so create simply writes the canonical set.
    """

    out_dir = project_dir / OUTPUT_SUBDIR
    actions: list[str] = []

    for module in modules:
        content = build_module_file(module, bodies[module])
        if dry_run:
            actions.append(f"[dry-run] would write {OUTPUT_SUBDIR}/{module}.md")
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{module}.md").write_text(content, encoding="utf-8")
        actions.append(f"wrote {OUTPUT_SUBDIR}/{module}.md")

    actions += sync_references(
        project_dir=project_dir, modules=modules, prune=False, dry_run=dry_run
    )
    actions += ensure_bridge(project_dir=project_dir, dry_run=dry_run)

    print("created coding standard:")
    for action in actions:
        print(f"  - {action}")
    return 0


def do_investigate(
    *,
    project_dir: Path,
    modules: list[str],
    bodies: dict[str, str],
) -> int:
    """Investigate mode: already scaffolded, no --update. Print a read-only drift
    report and write nothing.

    Drift is a plain content diff: for each expected module present on disk,
    compare it to a fresh regeneration; report which would be added (expected,
    absent) and which would be removed (a scaffolded module no longer expected).
    """

    out_dir = project_dir / OUTPUT_SUBDIR
    expected = modules
    present = scaffolded_modules(project_dir)

    kept = [m for m in CANONICAL_ORDER if m in expected and m in present]
    added = [m for m in expected if m not in present]
    removed = [m for m in present if m not in set(expected)]

    # Compare each kept module's on-disk content to a fresh regeneration.
    statuses: dict[str, str] = {}
    for module in kept:
        fresh = build_module_file(module, bodies[module])
        on_disk = (out_dir / f"{module}.md").read_text(encoding="utf-8")
        statuses[module] = (
            "up to date" if on_disk == fresh else "differs (would be updated)"
        )

    actionable = added or removed or any(s != "up to date" for s in statuses.values())

    # All clear — short and unambiguous.
    if not actionable:
        print("Coding standard — up to date. Nothing to do.")
        return 0

    lines = ["Coding standard — investigate (read-only)", "", "Modules:"]
    width = max((len(m) for m in kept), default=0)
    for module in kept:
        lines.append(f"  {module.ljust(width)}  {statuses[module]}")

    if added or removed:
        lines += ["", "Project profile drift:"]
        lines += [
            f"  + {m}   expected, not yet scaffolded (would be added)" for m in added
        ]
        lines += [
            f"  − {m}   scaffolded, no longer expected (would be removed)"
            for m in removed
        ]

    lines += ["", "→ Run /coding-standard --update to reconcile."]
    print("\n".join(lines))
    return 0


def do_update(
    *,
    project_dir: Path,
    modules: list[str],
    bodies: dict[str, str],
    dry_run: bool,
) -> int:
    """Update mode: reconcile the project to the current --include. Rewrite every
    module whose content differs, add new ones, remove dropped ones and prune
    their References. The plugin owns these files, so there is no local-edit
    protection — any on-disk difference is reconciled to the canonical content."""

    out_dir = project_dir / OUTPUT_SUBDIR
    present = scaffolded_modules(project_dir)
    actions: list[str] = []

    # Reconcile every module the project should have today.
    for module in modules:
        content = build_module_file(module, bodies[module])
        dest = out_dir / f"{module}.md"
        on_disk = dest.read_text(encoding="utf-8") if dest.exists() else None

        # Unchanged — nothing to do.
        if on_disk == content:
            continue

        if dry_run:
            verb = "add" if on_disk is None else "update"
            actions.append(f"[dry-run] would {verb} {OUTPUT_SUBDIR}/{module}.md")
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        actions.append(
            f"{'added' if on_disk is None else 'updated'} {OUTPUT_SUBDIR}/{module}.md"
        )

    # Remove modules dropped from the profile.
    for module in [m for m in present if m not in set(modules)]:
        dest = out_dir / f"{module}.md"
        if dry_run:
            actions.append(f"[dry-run] would remove {OUTPUT_SUBDIR}/{module}.md")
            continue
        if dest.exists():
            dest.unlink()
        actions.append(f"removed {OUTPUT_SUBDIR}/{module}.md")

    actions += sync_references(
        project_dir=project_dir, modules=modules, prune=True, dry_run=dry_run
    )
    actions += ensure_bridge(project_dir=project_dir, dry_run=dry_run)

    if not actions:
        print("coding standard already up to date — nothing to do.")
        return 0

    print("updated coding standard:")
    for action in actions:
        print(f"  - {action}")
    return 0


def main() -> int:
    """Run the scaffolder end to end. Returns the process exit code."""

    parser = ScaffoldArgumentParser(
        description="Materialise and maintain Kntnt's coding standard in a project.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--project-dir", type=Path, required=True, help="Project root.")
    parser.add_argument(
        "--modules-dir",
        type=Path,
        required=True,
        help="Path to the module sources (the plugin's lib/coding-standard).",
    )
    parser.add_argument(
        "--include",
        required=True,
        help=(
            "Comma-separated module names (e.g. 'php,wordpress,typescript'). "
            "'general' and any prerequisites are always included."
        ),
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Reconcile an already-scaffolded project to the current --include.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without writing any files.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Override the project-root sanity check (write into a directory with no project marker).",
    )
    args = parser.parse_args()

    project_dir: Path = args.project_dir.resolve()
    modules_dir: Path = args.modules_dir.resolve()
    requested = [part.strip() for part in args.include.split(",") if part.strip()]

    # Sanity-check the project directory unless --force is set. Refusing to write
    # into a random directory protects against typos.
    if not args.force:
        if not any((project_dir / marker).exists() for marker in PROJECT_MARKERS):
            markers = ", ".join(PROJECT_MARKERS)
            print(
                f"error: {project_dir} doesn't look like a project root "
                f"(no {markers}). Pass --force to override.",
                file=sys.stderr,
            )
            return 1

    try:
        modules = order_modules(requested)
        bodies = read_source_bodies(modules_dir, modules)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # Mode selection: a scaffolded agents.d/coding-standard/ is the marker.
    if not scaffolded_modules(project_dir):
        return do_create(
            project_dir=project_dir,
            modules=modules,
            bodies=bodies,
            dry_run=args.dry_run,
        )
    if not args.update:
        return do_investigate(
            project_dir=project_dir,
            modules=modules,
            bodies=bodies,
        )
    return do_update(
        project_dir=project_dir,
        modules=modules,
        bodies=bodies,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
