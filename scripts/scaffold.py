#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Materialise and maintain Kntnt's coding standard in a project.

Writes each requested module as its own on-demand file under
``agents.d/coding-standard/<module>.md``, records a ``manifest.json`` beside
them, ensures ``AGENTS.md`` carries a ``## References`` pointer to each one,
and ensures ``CLAUDE.md`` bridges to ``AGENTS.md`` with ``@AGENTS.md``.

The standard is reached on demand: an agent follows a References pointer and
reads only the modules a task needs, rather than paying for the whole standard
on every session. Override modules (WordPress over PHP, Gutenberg blocks over
TypeScript) carry a generated prerequisite + precedence header so the override
resolves however the file is reached. That wiring lives in MODULE_META here, so
the source modules stay generic and portable.

This script owns the deterministic, error-prone file work; the judgement —
which modules a project needs — stays with the calling skill, which always
passes the current profile via ``--include``. It runs in one of three modes,
chosen by the project's state and the ``--update`` flag:

  * **create** — no manifest yet: write the modules, manifest, and wiring.
  * **investigate** — a manifest exists, no ``--update``: print a read-only
    drift report (what changed in the standard, what changed in the project
    profile, which files were locally edited) and write nothing.
  * **update** — a manifest exists, ``--update`` given: reconcile to the
    current ``--include`` — rewrite changed modules, add new ones, remove
    dropped ones, and prune their References — while leaving locally edited
    files untouched unless ``--force`` is set.

Drift is detected from a single stored hash per module — the hash of the file
as this script generated it. Comparing it to the file on disk reveals local
edits; comparing it to a fresh in-memory regeneration reveals changes to the
standard or to this generator.

Typical use:

    scripts/scaffold.py \\
        --project-dir  /path/to/project \\
        --modules-dir  /path/to/plugin/lib/coding-standard \\
        --include      php,wordpress,typescript,wordpress-block
        [--update] [--dry-run] [--force]

Order on the command line does not matter; the canonical order is imposed
internally so override relationships stay correct.

Exit codes:

    0   Completed successfully (create, investigate, or update).
    1   Bad arguments, missing module source file, or sanity-check failed.
    2   create only: a target file already exists and was not overwritten.
        Stderr names the clashing files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import NoReturn

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
#                builds on them; drives the prerequisite header. Empty for
#                standalone modules.
MODULE_META: dict[str, dict[str, object]] = {
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

# Where the standard is materialised inside a project, and the bookkeeping file
# beside it. The directory is the namespace, so the module files drop the
# `coding-` prefix; the manifest is private state, never referenced from
# AGENTS.md, so no agent ever loads it.
OUTPUT_SUBDIR: str = "agents.d/coding-standard"
MANIFEST_NAME: str = "manifest.json"
MANIFEST_VERSION: int = 1

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

    argparse's default is exit code 2, but this script reserves 2 for "a target
    file already exists". Mapping usage errors to 1 keeps the bad-arguments case
    distinct from the exit code alone.
    """

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def plugin_version() -> str:
    """Read the plugin's version from its manifest, for the `generatedWith`
    label. This script lives at ``scripts/``; the plugin root is its parent."""

    path = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("version", "unknown"))
    except (OSError, json.JSONDecodeError):
        return "unknown"


def sha256_text(text: str) -> str:
    """Self-describing content hash for the manifest."""

    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def references_line(module: str) -> str:
    """Build the AGENTS.md References bullet for a module — a pure pointer.

    Prerequisite and precedence information lives in the module file's own
    generated header, so the References line carries no co-load note: one home
    for that knowledge, nothing here to go stale.
    """

    read_when = MODULE_META[module]["read_when"]
    return (
        f"- {OUTPUT_SUBDIR}/{module}.md — read before writing or changing {read_when}"
    )


def build_module_file(module: str, body: str) -> str:
    """Assemble the on-demand file for one module.

    The generated H1 + read-when line (and, for override modules, the
    prerequisite + precedence lines) sit above the module body. The module's own
    leading heading is dropped so the generated H1 is the sole title. The output
    is deterministic in (module, body), so its hash is a stable fingerprint of
    what this generator produces.
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
    """Validate requested modules and return them in canonical order, always
    including `general`. Raises ValueError naming any unknown module."""

    unknown = [m for m in requested if m not in CANONICAL_ORDER]
    if unknown:
        raise ValueError(
            f"unknown module(s): {', '.join(unknown)}. "
            f"Known modules: {', '.join(CANONICAL_ORDER)}."
        )
    wanted = set(requested)
    wanted.add("general")
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


def manifest_path(project_dir: Path) -> Path:
    """Path to the project's coding-standard manifest."""

    return project_dir / OUTPUT_SUBDIR / MANIFEST_NAME


def load_manifest(project_dir: Path) -> dict | None:
    """Load the manifest, or None when the project has not been scaffolded.

    A present-but-unreadable manifest is treated as absent: the safest fallback
    is to behave as if nothing was scaffolded rather than act on garbage.
    """

    path = manifest_path(project_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_manifest(project_dir: Path, modules: dict[str, str]) -> None:
    """Write the manifest with the current plugin version and module hashes."""

    data = {
        "manifestVersion": MANIFEST_VERSION,
        "generatedWith": plugin_version(),
        "modules": modules,
    }
    path = manifest_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def disk_hash(path: Path) -> str | None:
    """Hash of a materialised module file as it sits on disk, or None when the
    file is absent."""

    if not path.exists():
        return None
    return sha256_text(path.read_text(encoding="utf-8"))


def module_status(stored: str, on_disk: str | None, fresh: str) -> str:
    """Classify a kept module from its three hashes into one of the drift
    states shown in the investigate report."""

    if on_disk is None:
        return "missing — would be recreated"
    edited = on_disk != stored
    changed = fresh != stored
    if not edited and not changed:
        return "up to date"
    if not edited and changed:
        return "update available"
    if edited and not changed:
        return "locally edited"
    return "locally edited + update available"


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
        return ["created minimal AGENTS.md with References — run /agents-md to flesh it out"]

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
    force: bool,
    dry_run: bool,
) -> int:
    """Create mode: nothing scaffolded yet. Write the modules, manifest, and
    wiring. Refuse to clobber pre-existing files unless --force."""

    out_dir = project_dir / OUTPUT_SUBDIR

    # Refuse to overwrite files we did not record (no manifest means we cannot
    # tell what is safe to touch). --force overrides.
    if not force:
        clashes = [m for m in modules if (out_dir / f"{m}.md").exists()]
        if clashes:
            names = ", ".join(f"{OUTPUT_SUBDIR}/{m}.md" for m in clashes)
            print(
                f"existing file(s) found with no manifest: {names}\n"
                "refusing to overwrite. Pass --force, or move them aside.",
                file=sys.stderr,
            )
            return 2

    actions: list[str] = []
    manifest_modules: dict[str, str] = {}
    for module in modules:
        content = build_module_file(module, bodies[module])
        manifest_modules[module] = sha256_text(content)
        if dry_run:
            actions.append(f"[dry-run] would write {OUTPUT_SUBDIR}/{module}.md")
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{module}.md").write_text(content, encoding="utf-8")
        actions.append(f"wrote {OUTPUT_SUBDIR}/{module}.md")

    if dry_run:
        actions.append(f"[dry-run] would write {OUTPUT_SUBDIR}/{MANIFEST_NAME}")
    else:
        write_manifest(project_dir, manifest_modules)
        actions.append(f"wrote {OUTPUT_SUBDIR}/{MANIFEST_NAME}")

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
    manifest: dict,
) -> int:
    """Investigate mode: a manifest exists, no --update. Print a read-only drift
    report and write nothing."""

    out_dir = project_dir / OUTPUT_SUBDIR
    stored = manifest.get("modules", {})
    generated_with = manifest.get("generatedWith", "unknown")
    current = plugin_version()

    today = set(modules)
    recorded = set(stored)
    kept = [m for m in CANONICAL_ORDER if m in today and m in recorded]
    added = [m for m in CANONICAL_ORDER if m in today and m not in recorded]
    removed = [m for m in CANONICAL_ORDER if m in recorded and m not in today]

    # Classify each kept module from its three hashes.
    statuses: dict[str, str] = {}
    for module in kept:
        fresh = sha256_text(build_module_file(module, bodies[module]))
        statuses[module] = module_status(
            stored[module], disk_hash(out_dir / f"{module}.md"), fresh
        )

    edited = [m for m in kept if statuses[m].startswith("locally edited")]
    actionable = added or removed or any(s != "up to date" for s in statuses.values())

    # All clear — short and unambiguous.
    if not actionable:
        print(
            f"Coding standard — up to date (plugin {current}). "
            "Project profile unchanged.\n"
            "Nothing to do."
        )
        return 0

    lines = [
        f"Coding standard — generated with plugin {generated_with} (current: {current})",
        "",
        "Modules:",
    ]
    width = max((len(m) for m in kept), default=0)
    for module in kept:
        lines.append(f"  {module.ljust(width)}  {statuses[module]}")

    if added or removed:
        lines += ["", "Project profile drift:"]
        lines += [
            f"  + {m}   detected in project, not yet scaffolded (would be added)"
            for m in added
        ]
        lines += [
            f"  - {m}   scaffolded, no longer detected (would be removed)"
            for m in removed
        ]

    lines += ["", "→ Updates available. Run /coding-standard --update to apply."]
    if edited:
        verb = "has" if len(edited) == 1 else "have"
        lines.append(
            f"  Note: {', '.join(edited)} {verb} local edits — left untouched by --update."
        )
        lines.append(
            "  To replace with the current standard, back up your edits and pass --force."
        )

    print("\n".join(lines))
    return 0


def do_update(
    *,
    project_dir: Path,
    modules: list[str],
    bodies: dict[str, str],
    manifest: dict,
    force: bool,
    dry_run: bool,
) -> int:
    """Update mode: reconcile the project to the current --include. Rewrite
    changed modules, add new ones, remove dropped ones and prune their
    References, and leave locally edited files untouched unless --force."""

    out_dir = project_dir / OUTPUT_SUBDIR
    stored = manifest.get("modules", {})
    actions: list[str] = []
    skipped: list[str] = []
    new_modules: dict[str, str] = {}

    # Reconcile every module the project should have today.
    for module in modules:
        content = build_module_file(module, bodies[module])
        fresh = sha256_text(content)
        dest = out_dir / f"{module}.md"

        # New module — write it.
        if module not in stored:
            new_modules[module] = fresh
            if dry_run:
                actions.append(f"[dry-run] would add {OUTPUT_SUBDIR}/{module}.md")
            else:
                out_dir.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
                actions.append(f"added {OUTPUT_SUBDIR}/{module}.md")
            continue

        # Kept module — protect local edits, then rewrite only if needed.
        on_disk = disk_hash(dest)
        if on_disk is not None and on_disk != stored[module] and not force:
            new_modules[module] = stored[module]
            skipped.append(module)
            continue
        new_modules[module] = fresh
        if on_disk == fresh:
            continue
        if dry_run:
            actions.append(f"[dry-run] would update {OUTPUT_SUBDIR}/{module}.md")
        else:
            out_dir.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
            verb = "recreated" if on_disk is None else "updated"
            actions.append(f"{verb} {OUTPUT_SUBDIR}/{module}.md")

    # Remove modules dropped from the profile.
    for module in [m for m in stored if m not in set(modules)]:
        dest = out_dir / f"{module}.md"
        if dry_run:
            actions.append(f"[dry-run] would remove {OUTPUT_SUBDIR}/{module}.md")
            continue
        if dest.exists():
            dest.unlink()
        actions.append(f"removed {OUTPUT_SUBDIR}/{module}.md")

    # Rewrite the manifest unless nothing about the module set or its hashes
    # changed (skipped files keep their old hash, so an all-skip run is a no-op).
    if dry_run:
        actions.append(f"[dry-run] would update {OUTPUT_SUBDIR}/{MANIFEST_NAME}")
    elif new_modules != stored:
        write_manifest(project_dir, new_modules)
        actions.append(f"updated {OUTPUT_SUBDIR}/{MANIFEST_NAME}")

    actions += sync_references(
        project_dir=project_dir, modules=modules, prune=True, dry_run=dry_run
    )
    actions += ensure_bridge(project_dir=project_dir, dry_run=dry_run)

    if not actions and not skipped:
        print("coding standard already up to date — nothing to do.")
        return 0

    print("updated coding standard:")
    for action in actions:
        print(f"  - {action}")
    if skipped:
        print(
            f"  - left untouched (local edits): {', '.join(skipped)} "
            "— pass --force to overwrite"
        )
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
            "'general' is always included."
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
        help="Override safety refusals (sanity check; overwrite locally edited files).",
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

    # Mode selection: the manifest is the marker of a scaffolded project.
    manifest = load_manifest(project_dir)
    if manifest is None:
        return do_create(
            project_dir=project_dir,
            modules=modules,
            bodies=bodies,
            force=args.force,
            dry_run=args.dry_run,
        )
    if not args.update:
        return do_investigate(
            project_dir=project_dir,
            modules=modules,
            bodies=bodies,
            manifest=manifest,
        )
    return do_update(
        project_dir=project_dir,
        modules=modules,
        bodies=bodies,
        manifest=manifest,
        force=args.force,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
