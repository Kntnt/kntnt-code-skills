#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Deterministic file work for the `init` skill.

The `init` skill orchestrates the interactive part of bootstrapping a new
project — the questions, the calls to `agents-md`, `coding-standard`, and
`writing-rules`, the git and GitHub steps. This script owns the error-prone,
testable file work the skill hands off to it, in three commands:

  * **gitignore** — compose a `.gitignore` from the universal baseline plus the
    per-module fragment for each expanded coding-standard module, deduplicated.
  * **templates** — render the generic `lib/templates/` files (README, CHANGELOG,
    CONTRIBUTING, and — only under an Apache licence — NOTICE) by substituting
    the project's identity tokens.
  * **license** — resolve an SPDX id to the canonical licence text (fetched with
    `curl`), fill the year/owner placeholders for the licences that carry them,
    and write `LICENSE`.

Each command is a thin wrapper over a pure function, so the logic is covered by
tests/test_init.py without touching the network or the filesystem.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

# SPDX ids whose `text/<id>.txt` filename differs from the label a person picks.
# The licence-list-data repository files the GPL family under the `-only`
# variant, so map to it before building the fetch URL.
SPDX_ALIASES: dict[str, str] = {
    "GPL-2.0": "GPL-2.0-only",
    "GPL-3.0": "GPL-3.0-only",
}

# The base URL of the SPDX licence-list-data plain-text licences.
SPDX_TEXT_BASE: str = "https://raw.githubusercontent.com/spdx/license-list-data/main/text"

# Licences whose canonical text carries year/owner placeholders meant to be
# filled in by the licensor. Apache and the GPL family are used verbatim — their
# copyright line lives in NOTICE (Apache) or is not substituted (GPL).
PLACEHOLDER_LICENSES: frozenset[str] = frozenset({"BSD-1-Clause", "MIT-0"})

# Placeholder tokens seen in SPDX licence texts, grouped by what fills them.
YEAR_PLACEHOLDERS: tuple[str, ...] = ("<year>", "<YEAR>")
OWNER_PLACEHOLDERS: tuple[str, ...] = (
    "<owner>",
    "<OWNER>",
    "<copyright holders>",
    "<copyright holder>",
    "<COPYRIGHT HOLDERS>",
    "<COPYRIGHT HOLDER>",
    "<name of author>",
)

# Human-readable licence names for the README "License" section, keyed by the
# resolved (alias-mapped) SPDX id. Unknown ids fall back to the id itself.
LICENSE_DISPLAY: dict[str, str] = {
    "Apache-2.0": "the Apache License 2.0",
    "MIT-0": "the MIT No Attribution licence (MIT-0)",
    "BSD-1-Clause": "the BSD 1-Clause License",
    "GPL-2.0-only": "the GNU General Public License v2.0",
    "GPL-3.0-only": "the GNU General Public License v3.0",
    "MIT": "the MIT License",
}

# The generic templates this script renders, paired with their output filename.
TEMPLATE_FILES: tuple[tuple[str, str], ...] = (
    ("README.md", "README.md"),
    ("CHANGELOG.md", "CHANGELOG.md"),
    ("CONTRIBUTING.md", "CONTRIBUTING.md"),
)


def map_spdx(license_id: str) -> str:
    """Resolve a picked licence label to its SPDX text-file id (GPL → `-only`)."""

    return SPDX_ALIASES.get(license_id, license_id)


def license_url(license_id: str) -> str:
    """Build the SPDX licence-list-data URL for a licence's plain text."""

    return f"{SPDX_TEXT_BASE}/{map_spdx(license_id)}.txt"


def license_display(license_id: str) -> str:
    """A human-readable licence name for the README, falling back to the id."""

    return LICENSE_DISPLAY.get(map_spdx(license_id), map_spdx(license_id))


def fill_placeholders(text: str, *, year: str, owner: str) -> str:
    """Replace the year and owner placeholders an SPDX licence text carries."""

    for token in YEAR_PLACEHOLDERS:
        text = text.replace(token, year)
    for token in OWNER_PLACEHOLDERS:
        text = text.replace(token, owner)
    return text


def postprocess_license(license_id: str, text: str, *, year: str, owner: str) -> str:
    """Post-process a fetched licence text. Only the placeholder-bearing licences
    (BSD-1-Clause, MIT-0) get year/owner filled; everything else is verbatim."""

    if map_spdx(license_id) in PLACEHOLDER_LICENSES:
        return fill_placeholders(text, year=year, owner=owner)
    return text


def inbound_licensing(license_id: str) -> str:
    """The CONTRIBUTING "Inbound licensing" paragraph, adapted to the licence.

    Apache carries the §5 submission clause that makes a separate CLA needless;
    every other licence gets the plain "you agree to license under the project's
    licence" statement.
    """

    if map_spdx(license_id).startswith("Apache"):
        return (
            "By submitting a contribution, you agree it is licensed under the "
            "Apache License 2.0 by virtue of its §5 *Submission of Contributions* "
            "— any contribution intentionally submitted for inclusion is under the "
            "terms of that licence unless you state otherwise. No separate "
            "contributor licence agreement is required."
        )
    return (
        "By submitting a contribution, you agree to license it under the project's "
        "licence. No separate contributor licence agreement is required."
    )


def compose_gitignore(base: str, fragments: Sequence[str]) -> str:
    """Compose a `.gitignore` from the baseline plus module fragments, deduped.

    The baseline goes first, recording its entries. Each fragment then appends
    only the entries not already present; a fragment whose every entry is already
    covered is dropped whole (header and all), so the result has no orphan
    comment headers and no duplicated path lines.
    """

    seen: set[str] = set()
    base_lines = base.rstrip("\n").splitlines()
    for line in base_lines:
        entry = line.strip()
        if entry and not entry.startswith("#"):
            seen.add(entry)

    blocks: list[str] = ["\n".join(base_lines)]
    for fragment in fragments:
        kept: list[str] = []
        added = False
        for line in fragment.rstrip("\n").splitlines():
            entry = line.strip()
            if entry and not entry.startswith("#"):
                if entry in seen:
                    continue
                seen.add(entry)
                added = True
            kept.append(line)
        if added:
            blocks.append("\n".join(kept))

    return "\n\n".join(blocks) + "\n"


def read_gitignore(gitignore_dir: Path, modules: Sequence[str]) -> str:
    """Read base.txt plus each module's fragment (when one exists) and compose."""

    base = (gitignore_dir / "base.txt").read_text(encoding="utf-8")
    fragments: list[str] = []
    for module in modules:
        fragment = gitignore_dir / f"{module}.txt"
        if fragment.exists():
            fragments.append(fragment.read_text(encoding="utf-8"))
    return compose_gitignore(base, fragments)


def substitute(template: str, tokens: dict[str, str]) -> str:
    """Replace every ``{{KEY}}`` placeholder with its token value."""

    rendered = template
    for key, value in tokens.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def build_tokens(
    *,
    project_name: str,
    owner: str,
    description: str,
    author_name: str,
    author_url: str,
    year: str,
    date: str,
    license_id: str,
) -> dict[str, str]:
    """Assemble the substitution map the generic templates expect."""

    return {
        "PROJECT_NAME": project_name,
        "OWNER": owner,
        "DESCRIPTION": description,
        "AUTHOR_NAME": author_name,
        "AUTHOR_URL": author_url,
        "YEAR": year,
        "DATE": date,
        "LICENSE": license_display(license_id),
        "INBOUND_LICENSING": inbound_licensing(license_id),
    }


def fetch_license_text(license_id: str) -> str:
    """Fetch a licence's canonical text with curl. Raises on any curl failure."""

    result = subprocess.run(
        ["curl", "-fsSL", license_url(license_id)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def cmd_gitignore(args: argparse.Namespace) -> int:
    """Compose a `.gitignore` and write it (or print it with --stdout)."""

    modules = [m.strip() for m in args.include.split(",") if m.strip()]
    content = read_gitignore(args.gitignore_dir.resolve(), modules)
    if args.stdout:
        sys.stdout.write(content)
    else:
        (args.project_dir / ".gitignore").write_text(content, encoding="utf-8")
        print(f"wrote {args.project_dir / '.gitignore'}")
    return 0


def cmd_templates(args: argparse.Namespace) -> int:
    """Render README/CHANGELOG/CONTRIBUTING (+ NOTICE on Apache) into the project."""

    templates_dir = args.templates_dir.resolve()
    project_dir = args.project_dir.resolve()
    tokens = build_tokens(
        project_name=args.project_name,
        owner=args.owner,
        description=args.description,
        author_name=args.author_name,
        author_url=args.author_url,
        year=args.year,
        date=args.date,
        license_id=args.spdx,
    )

    written: list[str] = []
    for template_name, out_name in TEMPLATE_FILES:
        template = (templates_dir / template_name).read_text(encoding="utf-8")
        (project_dir / out_name).write_text(substitute(template, tokens), encoding="utf-8")
        written.append(out_name)

    # NOTICE belongs only with the Apache licence (its copyright line lives there).
    if map_spdx(args.spdx).startswith("Apache"):
        notice = (templates_dir / "NOTICE").read_text(encoding="utf-8")
        (project_dir / "NOTICE").write_text(substitute(notice, tokens), encoding="utf-8")
        written.append("NOTICE")

    print("wrote: " + ", ".join(written))
    return 0


def cmd_license(args: argparse.Namespace) -> int:
    """Fetch, post-process, and write LICENSE. A curl failure is reported as an
    error so the skill can continue without a LICENSE rather than abort."""

    try:
        text = fetch_license_text(args.spdx)
    except (subprocess.CalledProcessError, OSError) as exc:
        print(
            f"error: could not fetch licence text for {map_spdx(args.spdx)} "
            f"from {license_url(args.spdx)}: {exc}",
            file=sys.stderr,
        )
        return 1
    text = postprocess_license(args.spdx, text, year=args.year, owner=args.owner)
    (args.project_dir / "LICENSE").write_text(text, encoding="utf-8")
    print(f"wrote {args.project_dir / 'LICENSE'} ({map_spdx(args.spdx)})")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch on the subcommand. Returns the process exit code."""

    parser = argparse.ArgumentParser(
        description="Deterministic file work for the init skill.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    gi = sub.add_parser("gitignore", help="Compose a .gitignore from baseline + fragments.")
    gi.add_argument("--gitignore-dir", type=Path, required=True)
    gi.add_argument("--include", required=True, help="Comma-separated expanded module names.")
    gi.add_argument("--project-dir", type=Path, default=Path("."))
    gi.add_argument("--stdout", action="store_true", help="Print instead of writing the file.")
    gi.set_defaults(func=cmd_gitignore)

    tp = sub.add_parser("templates", help="Render the generic project templates.")
    tp.add_argument("--templates-dir", type=Path, required=True)
    tp.add_argument("--project-dir", type=Path, default=Path("."))
    tp.add_argument("--project-name", required=True)
    tp.add_argument("--owner", required=True)
    tp.add_argument("--description", required=True)
    tp.add_argument("--author-name", required=True)
    tp.add_argument("--author-url", required=True)
    tp.add_argument("--year", required=True)
    tp.add_argument("--date", required=True)
    tp.add_argument("--spdx", required=True, help="The chosen licence id (drives NOTICE + wording).")
    tp.set_defaults(func=cmd_templates)

    lc = sub.add_parser("license", help="Fetch, fill, and write LICENSE.")
    lc.add_argument("--spdx", required=True)
    lc.add_argument("--year", required=True)
    lc.add_argument("--owner", required=True)
    lc.add_argument("--project-dir", type=Path, default=Path("."))
    lc.set_defaults(func=cmd_license)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
