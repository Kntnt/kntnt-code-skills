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

The standard itself lives in topic modules under the plugin's `lib/coding-standard/`. This file is a **lazy bootstrap**: it pulls in each module only at the moment the working context proves it is needed, and not before — never the whole standard up front.

## How loading works

A skill trigger loads only this file. From here you load the router, then pull modules in one at a time as the context reveals which ones apply. This file plus the router are the bootstrap: they stay resident for the whole session, and you keep using them to pull in further modules whenever a new language or framework surfaces — quietly, in the background, without announcing it.

### 1. Load the router

Load `${CLAUDE_PLUGIN_ROOT}/lib/coding-standard/_index.md` once, now. It carries the module table, the detection signals (which file markers and textual cues imply which language/framework axis), and the canonical precedence order. It holds no rules of its own — only the knowledge of *which* module to reach for *when*. Keep it resident; it is how you route every later load.

Do not load any standard module yet. An empty project with no language cue needs nothing more than this router until code work actually begins.

### 2. Pull modules in lazily, as the context reveals them

Read a module from `${CLAUDE_PLUGIN_ROOT}/lib/coding-standard/` the moment — and only the moment — its axis is confirmed by a file marker, the code you are about to write, or an explicit statement (per the router's detection signals):

- `general.md` — the instant you begin any actual code work. It underpins every other module.
- The language module (`php.md`, `typescript.md`, `python.md`, `bash.md`, `javascript-vanilla.md`) when that language appears.
- The framework module when its markers appear — and they keep appearing through a session. PHP that turns out to be WordPress → pull `wordpress.md` then. A WordPress block → pull `wordpress-block.md`, plus `typescript.md` or `javascript-vanilla.md` depending on what the block's UI actually uses.

Each module self-describes the relationships it has with others, so loading them out of order, at different times, stays correct: where modules differ, the later/more-specific one wins (`wordpress.md` over `php.md`, `wordpress-block.md` over `typescript.md`), exactly as the router's canonical order states. Pulling a module in mid-task is normal and silent — load what the moment needs, then apply it.

If the project already has the standard scaffolded into `agents.d/coding-standard/`, those files are the snapshot the project's own agents load. Reconcile silently and proceed; do not offer to re-scaffold (the `coding-standard` skill owns that).

### 3. Apply

Write, refactor, review, or design the code Thomas asked for, honouring every module you have loaded. The modules are the contract; this file just gets you to the right ones at the right time.

## Standalone scripts

A meta-rule that fires only when step 2's detection finds no language at all — typically a standalone script requested in isolation, with no surrounding project to pin the language. When, and only when, that happens, load `${CLAUDE_PLUGIN_ROOT}/skills/coder/standalone-scripts.md` and follow it to choose and package the language. Do not load it otherwise.

## Related skills

- **`coding-standard`** — materialises the standard into a project as files under `agents.d/coding-standard/` and keeps them in sync (create / investigate drift / update). When Thomas asks to *scaffold*, *set up*, or *update the coding standard* in a project, that is the skill — not this one. `coder` only reads and applies; it writes no standard files.

## Notes

- Updating the standard means editing one or more module files in `lib/coding-standard/`. Projects that have already scaffolded their own `agents.d/coding-standard/` keep their snapshot until they explicitly re-run the `coding-standard` skill with an update; this is intentional, so updates to the standard don't silently change project behaviour.
- Adding a new framework or language to the standard is described in `lib/coding-standard/_index.md` and `scripts/scaffold.py` (the two places the module list and canonical order live).
