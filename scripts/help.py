# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Render the manpage-style ``/help`` output for the kntnt-code-skills plugin.

The plugin's own files are the single source of truth:
``.claude-plugin/plugin.json`` supplies the header fields and
``skills/<name>/SKILL.md`` supplies each skill's intro paragraph. The script
extracts that material and emits the fully formatted block — word wrapping,
column alignment, and single-space separator lines all resolved here — so the
slash command only has to print the result verbatim. Pass an optional skill
name for the detail view; pass nothing for the overview.
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path

# Hard line budget for wrapped prose. The header and closing lines are exempt —
# a repository URL cannot be wrapped at a word boundary — so only intro
# paragraphs and the plugin description are held to it.
LINE_WIDTH: int = 80

# Visual separators are emitted as a single space rather than a truly empty
# line: Claude.app's fenced-code renderer collapses empty lines but keeps
# single-space ones, and in a terminal the space is indistinguishable from
# blank.
BLANK: str = " "


def plugin_root() -> Path:
    """Resolve the plugin root, preferring the env var Claude Code injects and
    falling back to the script's own location."""

    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    return Path(env) if env else Path(__file__).resolve().parent.parent


def intro_paragraph(skill_md: Path) -> str:
    """Extract a skill's intro paragraph: the first non-empty paragraph after
    the level-one heading and before the first ``## `` heading.

    Physical line breaks inside the paragraph are normalised to single spaces
    so the caller can re-wrap freely; the words themselves are preserved
    verbatim.
    """

    lines = skill_md.read_text(encoding="utf-8").splitlines()

    # Drop YAML frontmatter so its `---` fences and fields never leak into the
    # body scan.
    if lines and lines[0].strip() == "---":
        closing = next(
            (i for i in range(1, len(lines)) if lines[i].strip() == "---"), None
        )
        if closing is not None:
            lines = lines[closing + 1 :]

    # Locate the level-one heading; the intro paragraph is the first prose block
    # beneath it.
    start = next((i for i in range(len(lines)) if lines[i].startswith("# ")), None)
    if start is None:
        return ""

    # Collect consecutive non-blank lines, skipping leading blanks and stopping
    # at the next section heading or the paragraph's trailing blank line.
    paragraph: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        if line.strip():
            paragraph.append(line.strip())
        elif paragraph:
            break

    return " ".join(paragraph)


def wrap(
    text: str,
    width: int = LINE_WIDTH,
    initial: str = "",
    subsequent: str = "",
) -> list[str]:
    """Word-wrap prose to ``width`` with separate first-line and continuation
    indents, leaving words and hyphens intact.

    Both indents count toward ``width``, so a first line carrying an alignment
    prefix still respects the line budget.
    """

    return textwrap.wrap(
        text,
        width=width,
        initial_indent=initial,
        subsequent_indent=subsequent,
        break_long_words=False,
        break_on_hyphens=False,
    )


def skill_dirs(root: Path) -> list[str]:
    """List skill directory names that carry a SKILL.md, alphabetically."""

    return sorted(
        d.name for d in (root / "skills").iterdir() if (d / "SKILL.md").is_file()
    )


def render_overview(root: Path, names: list[str]) -> str:
    """Render the full overview block: header, wrapped plugin description, and
    one aligned entry per skill."""

    manifest = json.loads(
        (root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )

    # Header line plus the wrapped plugin description.
    header = f"{manifest['name']} {manifest['version']}  ·  {manifest['repository']}"
    out = [header, BLANK]
    out += wrap(manifest["description"])
    out += [BLANK, "Skills:", BLANK]

    # Align every description to a shared column two spaces past the longest
    # slash-name.
    label_width = max(len(f"/{name}") for name in names) + 2
    desc_indent = " " * (2 + label_width)
    for name in names:
        prefix = "  " + f"/{name}".ljust(label_width)
        body = intro_paragraph(root / "skills" / name / "SKILL.md")
        out += wrap(body, initial=prefix, subsequent=desc_indent) or [prefix.rstrip()]
        out.append(BLANK)

    out.append(f"For details on one skill:  /{manifest['name']}:help <skill-name>")
    return "\n".join(out)


def render_detail(root: Path, name: str) -> str:
    """Render the single-skill detail block: the ``/<name>`` heading and its
    wrapped intro paragraph."""

    body = intro_paragraph(root / "skills" / name / "SKILL.md")
    return "\n".join([f"/{name}", BLANK, *wrap(body)])


def render_unknown(arg: str, names: list[str]) -> str:
    """Render the one-line error naming the unrecognised skill and listing the
    known ones."""

    return f"Unknown skill: {arg}. Known: {', '.join(names)}"


def main() -> None:
    """Dispatch on the optional skill argument: empty → overview, known →
    detail, otherwise → unknown."""

    root = plugin_root()
    names = skill_dirs(root)
    arg = sys.argv[1].strip() if len(sys.argv) > 1 else ""

    if not arg:
        print(render_overview(root, names))
    elif arg in names:
        print(render_detail(root, arg))
    else:
        print(render_unknown(arg, names))


if __name__ == "__main__":
    main()
