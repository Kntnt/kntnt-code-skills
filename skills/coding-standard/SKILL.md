---
name: coding-standard
description: >
  Materialise and maintain Kntnt's coding standard as files in a
  project — create the `agents.d/coding-standard/` files, investigate
  how they have drifted, or update them. Trigger only on the explicit
  invocations `/coding-standard`, `/kntnt-code-skills:coding-standard`,
  or an unmistakable request to scaffold, set up, install, or update
  the coding standard in a project (in any language — the examples here
  are English only). The object is the coding standard itself; a
  request to scaffold an app or write code is the `coder` skill, not
  this one. Because it writes and deletes files in the project, never
  auto-trigger on a vague code task — when in doubt, ask first.
---

# coding-standard

This skill materialises Kntnt's coding standard into a project as files and keeps them in sync. It is the only skill that writes the standard into a project; its sibling `coder` reads the same standard and applies it to code but never writes these files.

The standard's source modules live in the plugin's `lib/coding-standard/`, with a shared `_index.md` listing the modules and how to detect which a project needs. The deterministic file work — writing the modules, the `manifest.json`, the `AGENTS.md` References, the `CLAUDE.md` bridge, and the drift detection — lives in `scripts/scaffold.py`. This file decides *which* modules a project needs and *which mode* to run; the script does the rest.

It is an explicit, deliberate operation. Never run it because a code task happened to touch a project; run it only when Thomas asks for the coding standard to be set up or updated. When the intent is unclear, ask first.

## What gets written

Into the project root:

- `agents.d/coding-standard/<module>.md` — one on-demand file per applicable module, each with a generated header (and, for override modules, a prerequisite + precedence block).
- `agents.d/coding-standard/manifest.json` — private bookkeeping: the plugin version at generation and a content hash per module. Never referenced from `AGENTS.md`, so no agent loads it. It is what makes drift detection possible.
- `AGENTS.md` — a `## References` pointer per module is ensured (a minimal `AGENTS.md` is created if missing; run `/agents-md` to flesh it out).
- `CLAUDE.md` — bridged to `AGENTS.md` with `@AGENTS.md`.

## The flow

### 1. Profile the project

Load `${CLAUDE_PLUGIN_ROOT}/lib/coding-standard/_index.md` and use its detection signals to determine which language/framework axes the project has — exactly as `coder` does. The resulting module list (minus `general`, which the script always adds) is the `--include` value. Always profile freshly: on an update this fresh profile is the source of truth, so a language added or removed since the last run is reflected.

### 2. Pick the mode

The script chooses create vs investigate from the project's state (whether a manifest exists); you choose whether this is an *update* from Thomas's phrasing:

- **Bare invocation** (`/coding-standard`, "set up the coding standard", "scaffold the standard") → run without `--update`. On a fresh project the script **creates**; on an already-scaffolded project it **investigates** and prints a read-only drift report.
- **Update invocation** (`/coding-standard --update`, "update the coding standard", "bring the standard up to date") → run with `--update`. The script reconciles the project to the fresh profile: rewrites changed modules, adds new ones, removes dropped ones and prunes their References, and leaves locally edited files untouched unless `--force` is given.

Use `--dry-run` to preview either path without writing.

### 3. Run the script

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/scaffold.py" \
    --project-dir <project-root> \
    --modules-dir "${CLAUDE_PLUGIN_ROOT}/lib/coding-standard" \
    --include     php,wordpress,typescript,wordpress-block \
    [--update] [--dry-run] [--force]
```

`--include` order does not matter; the script imposes the canonical order. Exit codes: `0` success; `1` bad arguments, missing module source, or the project-directory sanity check failed; `2` (create only) a target file already exists with no manifest and was not overwritten.

### 4. Relay the result

- **create / update** — report what was written, added, removed. If the update left files untouched because they were locally edited, surface that prominently: name them and explain that `--force` would overwrite them (and that backing up first preserves the edits).
- **investigate** — present the drift report as the script prints it: per-module status (up to date / update available / locally edited / locally edited + update available), project-profile drift (`+` added, `−` removed), and the bottom-line recommendation. If updates are available, tell Thomas he can apply them with an update invocation.

If the script returns a non-zero exit code, read its stderr, explain the situation, and don't redo the work by hand — the script is the source of truth for what this looks like.

## Related skills

- **`coder`** — reads the same standard and applies it while writing, refactoring, or reviewing code. It never writes the standard into the project. When the task is to *write code* (including scaffolding an app), that is `coder`; when the task is to *put the standard's files into a project or update them*, it is this skill.

## Notes

- This skill requires filesystem access to the project directory (Claude Code or Cowork). If access is not available — chat-only, no working directory — say so and stop; there is nothing to write.
- Updating the standard itself means editing the module files in `lib/coding-standard/`. A project keeps its scaffolded snapshot until this skill is run again with an update; that lag is intentional, so a change to the standard never silently changes a project's behaviour.
- Adding a new module: add the source file in `lib/coding-standard/`, a row and detection clause in `_index.md`, and an entry in `scripts/scaffold.py`'s `CANONICAL_ORDER` / `MODULE_META` (and `OVERRIDE_HEADER` if it overrides another). The script asserts these stay in sync and `audit.py` checks the module list against `CANONICAL_ORDER`.

## Files in this skill

- `SKILL.md` — this file. The engine and modules live at the plugin root: `scripts/scaffold.py` and `lib/coding-standard/`.
