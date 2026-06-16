#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Release-time CHANGELOG mechanics for the `release` skill.

The judgement-heavy part of a release — deciding what changed and writing
good changelog prose — stays with the calling agent. This script owns the
mechanical, error-prone surgery that is identical for every project and
done the same way every time:

  * promote the `## [Unreleased]` section to a dated `## [X.Y.Z]` heading,
  * open a fresh empty `## [Unreleased]` above it,
  * maintain the reference-link block at the bottom of the file, and
  * extract a version's section as release-note body text, with heading
    levels shifted up one step (`### Added` -> `## Added`).

It is deliberately project-agnostic: it reads the changelog's own existing
style (heading separator, link base URL) rather than imposing one, and
touches nothing but the changelog. Version-string edits across a project's
manifests are the caller's job, because where the version lives varies per
project and is recorded as prose, not machine-readable locators.

Standard library only; the PEP 723 block pins only the Python version so
`uv run scripts/release.py ...` works from anywhere.

Subcommands:

    promote   Promote [Unreleased] -> [X.Y.Z] and print the release body.
    extract   Print an existing version's section as release-note body.

Exit codes:

    0   Success.
    1   Bad arguments, missing file, or a malformed changelog.
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

# A version heading, e.g. `## [0.3.0] – 2026-05-29`, or the dateless
# `## [Unreleased]`. The separator class accepts en-dash, em-dash, or a
# hyphen so an existing heading parses whatever dash it was written with;
# the writer always emits the canonical en-dash (see SEPARATOR).
# The trailing `[ \t]*` matches only same-line whitespace — never a newline —
# so substitution does not eat the blank line that follows a heading.
VERSION_HEADING_RE = re.compile(
    r"^## \[(?P<name>[^\]]+)\](?:[ \t]*[—–\-][ \t]*)?(?P<date>\d{4}-\d{2}-\d{2})?[ \t]*$",
    re.MULTILINE,
)

# The `## [Unreleased]` heading line on its own.
UNRELEASED_RE = re.compile(r"^## \[Unreleased\][ \t]*$", re.MULTILINE)

# A reference-link definition line, e.g. `[Unreleased]: https://…/compare/…`.
UNRELEASED_LINK_RE = re.compile(r"^\[Unreleased\]:.*$", re.MULTILINE)
LINK_BASE_RE = re.compile(
    r"^\[[^\]]+\]:\s*(?P<base>\S+?)/(?:compare|releases/tag)/\S+\s*$", re.MULTILINE
)

# A loose SemVer check — major.minor.patch with an optional pre-release or
# build suffix. Strict enough to catch a fat-fingered argument, loose enough
# not to reject legitimate suffixes.
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")

# The separator the writer emits between a version and its date. Kntnt's
# house style is a spaced en-dash; this is the single source of that choice,
# so a promoted heading is always consistent regardless of older headings.
SEPARATOR = " – "


def fail(message: str) -> None:
    """Print an error to stderr and exit with code 1."""

    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def normalize_repo_url(url: str) -> str:
    """Turn a git remote URL into a browsable https base, e.g.
    `git@github.com:Owner/Repo.git` -> `https://github.com/Owner/Repo`.

    Unrecognised shapes are returned trimmed of a trailing `.git`, so a base
    URL passed in already-normalized still works.
    """

    url = url.strip()
    scp = re.match(r"^git@(?P<host>[^:]+):(?P<path>.+?)(?:\.git)?$", url)
    if scp:
        return f"https://{scp['host']}/{scp['path']}"
    ssh = re.match(r"^ssh://git@(?P<host>[^/]+)/(?P<path>.+?)(?:\.git)?$", url)
    if ssh:
        return f"https://{ssh['host']}/{ssh['path']}"
    return re.sub(r"\.git$", "", url)


def latest_released_version(text: str) -> str | None:
    """The first `## [version]` heading that is not `[Unreleased]`, i.e. the
    version this release will sit on top of. None on a first release."""

    for match in VERSION_HEADING_RE.finditer(text):
        if match["name"].lower() != "unreleased":
            return match["name"]
    return None


def base_url(text: str, repo_url: str | None) -> str | None:
    """The link base to build new reference links from. Prefer a base parsed
    out of the file's existing links (so host and path match exactly); fall
    back to a normalized `repo_url`; give up with None when neither exists."""

    match = LINK_BASE_RE.search(text)
    if match:
        return match["base"]
    return normalize_repo_url(repo_url) if repo_url else None


def shift_headings_up(body: str) -> str:
    """Shift every level-3-to-6 heading up one level (`### ` -> `## `) so an
    extracted section reads as top-level release notes. Done in a single
    pass so a `####` becomes `###`, never `##`."""

    return re.sub(r"^(#{3,6})(?= )", lambda m: m[1][1:], body, flags=re.MULTILINE)


def extract_body(text: str, version: str) -> str:
    """Return the body of `## [version]` — everything up to the next version
    heading, the reference-link block, or end of file — with heading levels
    shifted up one step. Raises ValueError when the version is absent."""

    pattern = re.compile(
        r"^## \[" + re.escape(version) + r"\][^\n]*\n(?P<body>.*?)"
        r"(?=^## \[|^\[[^\]]+\]:\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise ValueError(f"no section found for version {version}")
    return shift_headings_up(match["body"].strip("\n")).strip()


def update_links(text: str, version: str, repo_url: str | None) -> str:
    """Maintain the reference-link block: point `[Unreleased]` at a compare
    from the new tag to HEAD, and add a `[version]` link to the new tag.

    Reuses the file's own base URL when present, so a stale `[Unreleased]`
    compare (a common hand-maintenance slip) gets corrected in passing. When
    no base can be determined the block is left untouched rather than guessed.
    """

    base = base_url(text, repo_url)
    if base is None:
        return text
    unreleased_link = f"[Unreleased]: {base}/compare/v{version}...HEAD"
    version_link = f"[{version}]: {base}/releases/tag/v{version}"
    block = f"{unreleased_link}\n{version_link}"

    # Replace the existing [Unreleased] link in place and slot the new
    # version link directly beneath it; otherwise append a fresh block.
    existing = UNRELEASED_LINK_RE.search(text)
    if existing:
        return text[: existing.start()] + block + text[existing.end() :]
    return text.rstrip("\n") + f"\n\n{block}\n"


def promote(
    text: str, version: str, date: str, repo_url: str | None
) -> tuple[str, str]:
    """Promote `[Unreleased]` to a dated `[version]` heading, open a fresh
    empty `[Unreleased]` above it, maintain the link block, and return the
    `(new_changelog_text, release_body)` pair.

    Raises ValueError when there is no `[Unreleased]` heading to promote.
    """

    if not UNRELEASED_RE.search(text):
        raise ValueError("no '## [Unreleased]' heading found")

    promoted = f"## [Unreleased]\n\n## [{version}]{SEPARATOR}{date}"
    new_text = UNRELEASED_RE.sub(lambda _: promoted, text, count=1)
    new_text = update_links(new_text, version, repo_url)

    body = extract_body(new_text, version)
    if not body:
        print(
            "warning: the promoted section is empty — nothing was reconciled "
            "into [Unreleased] before promotion.",
            file=sys.stderr,
        )
    return new_text, body


def cmd_promote(args: argparse.Namespace) -> int:
    """Run the `promote` subcommand. Writes the changelog (unless --dry-run)
    and prints the release body to stdout in both modes, so the caller
    captures the body the same way whether previewing or committing."""

    if not VERSION_RE.match(args.version):
        fail(f"'{args.version}' is not a major.minor.patch version")
    changelog = Path(args.changelog)
    if not changelog.exists():
        fail(f"changelog not found: {changelog}")

    date = args.date or datetime.date.today().isoformat()
    try:
        new_text, body = promote(
            changelog.read_text(encoding="utf-8"), args.version, date, args.repo_url
        )
    except ValueError as exc:
        fail(str(exc))

    if args.dry_run:
        print(
            f"[dry-run] would promote [Unreleased] -> [{args.version}] {date} "
            f"in {changelog}",
            file=sys.stderr,
        )
    else:
        changelog.write_text(new_text, encoding="utf-8")
        print(
            f"promoted [Unreleased] -> [{args.version}] {date} in {changelog}",
            file=sys.stderr,
        )
    print(body)
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    """Run the `extract` subcommand — print an existing version's section as
    release-note body text. Useful when resuming a half-finished release whose
    changelog was already promoted."""

    changelog = Path(args.changelog)
    if not changelog.exists():
        fail(f"changelog not found: {changelog}")
    try:
        print(extract_body(changelog.read_text(encoding="utf-8"), args.version))
    except ValueError as exc:
        fail(str(exc))
    return 0


def main() -> int:
    """Parse arguments, dispatch to the chosen subcommand, return its code."""

    parser = argparse.ArgumentParser(
        description="Release-time CHANGELOG mechanics for the release skill.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    promote_parser = subparsers.add_parser(
        "promote", help="Promote [Unreleased] -> [X.Y.Z] and print the body."
    )
    promote_parser.add_argument(
        "--changelog", required=True, help="Path to CHANGELOG.md."
    )
    promote_parser.add_argument(
        "--version", required=True, help="New version, e.g. 0.4.0."
    )
    promote_parser.add_argument(
        "--date", help="Release date as YYYY-MM-DD (default: today, from the system)."
    )
    promote_parser.add_argument(
        "--repo-url",
        help="Git remote or web URL, used to build reference links when the "
        "changelog has no existing link block.",
    )
    promote_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the body without writing the file.",
    )
    promote_parser.set_defaults(func=cmd_promote)

    extract_parser = subparsers.add_parser(
        "extract", help="Print an existing version's section as release-note body."
    )
    extract_parser.add_argument(
        "--changelog", required=True, help="Path to CHANGELOG.md."
    )
    extract_parser.add_argument(
        "--version", required=True, help="Version to extract, e.g. 0.4.0."
    )
    extract_parser.set_defaults(func=cmd_extract)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
