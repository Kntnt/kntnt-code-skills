---
name: coder
description: >
  Apply Kntnt's coding standard to any code-shaped task, in any
  language or framework. Writing, modifying, refactoring, reviewing,
  debugging, or designing code; starting a new project; writing a
  standalone script — all count. The standard covers PHP, JavaScript,
  TypeScript, Python, Bash, WordPress, Gutenberg blocks, Laravel,
  Svelte, SvelteKit, and any framework added later, but the skill is
  not limited to those. Trigger on any request to write, implement,
  refactor, fix, review, or design code — a class, function, script,
  plugin, app, module, or CLI; a bug fix — and on any task that
  mentions a programming language, framework, or code construct. This
  skill only reads the standard and applies it; it never writes files
  into the project. To materialise or update the standard as files in a
  project, that is the `coding-standard` skill. The examples here are
  English, but trigger equally on the equivalent request in any
  language. When in doubt, trigger.
---

# coder

This skill applies Kntnt's coding standard to a code task. It is shipped as part of the `kntnt-code-skills` plugin — invoked as `kntnt-code-skills:coder` when referenced explicitly. It is read-only on the project: it loads the standard into context and honours it while writing, refactoring, reviewing, or designing code. It never writes the standard into the project as files — that is the sibling `coding-standard` skill's job (see *Related skills* below).

The standard itself lives in topic modules under the plugin's `lib/coding-standard/`, with a shared `_index.md` that lists the modules and how to detect which ones a project needs. This file is the router: it profiles the project, loads the matching modules, and applies them.

## The flow

Two steps. Every invocation runs both.

### 1. Profile the project

Load `${CLAUDE_PLUGIN_ROOT}/lib/coding-standard/_index.md` first — it carries the module table, the detection signals (which file markers and textual cues imply which language/framework axes), and the canonical order with its override relationships. Using it, inspect the working directory and the prompt to determine which axes apply.

A project may belong to several axes at once: WordPress plugins are PHP + WordPress; block plugins add WordPress + TypeScript + WordPress-block. If the profile is genuinely unclear after looking — typically when code is requested in isolation with no surrounding project context — match the language(s) of the request and proceed without pausing to ask, unless something materially depends on the answer.

If the project already has the standard scaffolded into `agents.d/coding-standard/`, those files are what the project's own agents load, and they are an intentional snapshot. Reconcile silently and proceed; do not offer to re-scaffold (the `coding-standard` skill owns that).

### 2. Apply the standard

Read the modules matching the profile from `${CLAUDE_PLUGIN_ROOT}/lib/coding-standard/`, in the canonical order given by `_index.md` (later wins on points where they differ):

1. `general.md` — always.
2. `php.md` (if PHP)
3. `wordpress.md` (if WordPress) — overrides parts of `php.md`
4. `typescript.md` (if TypeScript)
5. `wordpress-block.md` (if Gutenberg blocks) — overrides parts of `typescript.md`
6. `javascript-vanilla.md` (if plain browser JS)
7. `python.md` (if Python)
8. `bash.md` (if Bash)

Then write, refactor, review, or design the code Thomas asked for, honouring the loaded rules. The modules are the contract; this file just gets you there.

## Standalone scripts

A meta-rule that fires only when step 1's language detection finds nothing — typically when Thomas asks for a standalone script in isolation, with no surrounding project context to lock the language down.

### When this applies

Both of these must hold:

1. The task is to create a standalone script — not a class, not a function in an existing file, not part of a larger codebase.
2. No language is given by the context.

When the context already pins the language, the existing flow wins and this section does nothing:

- A WordPress or PHP codebase → PHP.
- A TypeScript or JavaScript project → TypeScript on Bun (per the TypeScript module's defaults).
- An explicit language in the prompt ("write me a Python script", "write a bash script") → that language.

In all those cases, apply the matching module(s) directly.

### Choosing the language

When the rule fires, pick the language by this order:

1. **TypeScript on Bun** — the default.
2. **Python (uv + PEP 723)** — only when a mature library makes Python the obvious choice for the task at hand.
3. **PHP** — when the script must live long untouched or shares code with a PHP codebase.
4. **Bash** — short, pure orchestration only.

Never default to Python merely because the task is "a script". Then apply the matching language module (`typescript.md`, `python.md`, `php.md`, or `bash.md`) the same way step 2 does.

### Packaging

The packaging shape depends on the script's target directory, not on its language.

**In a directory named `bin/`** → *command-style*. The script is intended to be invoked as a unix command:

- Filename has no extension.
- First line is a shebang (see below).
- File is executable (`chmod +x`).

This applies whether or not `bin/` happens to be on `PATH`. Making a command globally available is the user's decision — never the script's. Never modify `PATH`.

**Anywhere else** → *internal*. The script is invoked by another script, a skill, or a tool, not by a human as a command:

- Filename keeps its extension (`.ts`, `.py`, `.php`, `.sh`).
- No shebang.
- Caller invokes it explicitly: `bun foo.ts`, `php foo.php`, `uv run foo.py`, `bash foo.sh`.

**Shebangs** are env-based without exception:

| Language | Shebang |
|---|---|
| Bash | `#!/usr/bin/env bash` |
| Python | `#!/usr/bin/env -S uv run --script` |
| TypeScript | `#!/usr/bin/env bun` |
| PHP | `#!/usr/bin/env php` |

Never `#!/bin/bash` — Apple's `/bin/bash` is frozen at 3.2 and `bash.md` calls for Bash 5+.

**Single-file dependencies.** When a standalone script needs third-party packages, pin them inline so the file is self-contained:

- **Bun / TypeScript** — pin an exact version in the import specifier (no `^` or `~` ranges): `import { x } from "pkg@1.2.3";`. Bun auto-installs on first run.
- **Python** — declare dependencies and `requires-python` via PEP 723 inline metadata at the top of the file (see `python.md`). `uv run` resolves the environment automatically.

## Related skills

- **`coding-standard`** — materialises the standard into a project as files under `agents.d/coding-standard/` and keeps them in sync (create / investigate drift / update). When Thomas asks to *scaffold*, *set up*, or *update the coding standard* in a project, that is the skill — not this one. `coder` only reads and applies; it writes no standard files.

## Notes

- Updating the standard means editing one or more module files in `lib/coding-standard/`. Projects that have already scaffolded their own `agents.d/coding-standard/` keep their snapshot until they explicitly re-run the `coding-standard` skill with an update; this is intentional, so updates to the standard don't silently change project behaviour.
- Adding a new framework or language to the standard is described in `lib/coding-standard/_index.md` and `scripts/scaffold.py` (the two places the module list and canonical order live).
