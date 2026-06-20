---
description: Manpage-style help for the kntnt-code-skills plugin — list skills or show details for one
argument-hint: [skill-name]
allowed-tools: Bash(uv:*)
disable-model-invocation: true
model: sonnet
---

The user invoked `/kntnt-code-skills:help`. Argument: `$1`

`scripts/help.py` is the single source of truth: it reads the plugin's own files and renders the finished help block — header, column alignment, 80-character wrapping, and single-space separator lines all resolved. Empty argument yields the overview; a known skill name yields its detail; anything else yields the unknown-skill line.

Rendered help:

!`uv run "${CLAUDE_PLUGIN_ROOT}/scripts/help.py" "$1"`

Emit the rendered text above **verbatim** inside a single triple-backtick fenced code block. Preserve every line exactly, including lines that contain only a single space — they are intentional visual separators (Claude.app's fenced renderer collapses truly empty lines but keeps single-space ones). Output nothing outside the fence: no preamble, no commentary, no summary.
