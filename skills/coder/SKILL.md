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
argument-hint: "[help]"
---

# coder

This skill applies Kntnt's coding standard to a code task. It is shipped as part of the `kntnt-code-skills` plugin — invoked as `kntnt-code-skills:coder` when referenced explicitly. It is read-only on the project: it loads the standard into context and honours it while writing, refactoring, reviewing, or designing code. It never writes the standard into the project as files — that is the sibling `coding-standard` skill's job (see *Related skills* below).

The standard itself lives in topic modules under the plugin's `lib/coding-standard/`. This file is a **lazy bootstrap**: it never front-loads the standard. When the project already carries its own copy it loads nothing at all; otherwise it pulls in each module only at the moment the working context proves that one is needed.

## 0. Help gate

If the arguments are `help`, `--help`, or `-h`, run `uv run "${CLAUDE_PLUGIN_ROOT}/scripts/help.py" coder`, emit its output verbatim as Markdown, and stop. Do nothing else — no code is read, written, or reviewed.

## How loading works

A skill trigger loads only this file. Before reaching for anything in the plugin, check whether the project already carries the standard — when it does, you load nothing more. Otherwise you load the router and pull modules in one at a time as the context reveals which ones apply, keeping this file and the router resident so you can keep pulling more in whenever a new language or framework surfaces — quietly, in the background. Either way, the context cost stays the minimum the situation allows.

### 1. First: is the standard already in the project?

Check for `agents.d/coding-standard/` carrying module files in the project root — one or more `<module>.md` (or, equivalently, an `AGENTS.md` whose `## References` point into that directory). When it is there, the project has scaffolded its own copy of the standard — one on-demand `<module>.md` per axis, each wired into `AGENTS.md` as a `## References` pointer the agent already follows on its own the moment it sets out to write or change that kind of code. That snapshot is authoritative by design: the project keeps it until someone explicitly runs `/coding-standard --update`, precisely so the standard cannot shift under the project silently.

So when the project carries its own scaffolded standard:

- **Load nothing from the plugin** — not the router, not a single module. The project's own References pull in exactly the modules a task needs, on demand, through the normal `AGENTS.md` mechanism. Loading the plugin's `lib/` copies on top would both double the context and risk applying newer rules than the project's deliberate snapshot. Skip straight to step 4.
- **Do not gate on freshness.** The snapshot is intentional even when the plugin has moved on, so apply it as-is. The project's files are the contract; never reach back into the plugin's `lib/` to "check" or "refresh" them, and never let the plugin's version change which rules you apply.
- **One exception — an axis the scaffold does not cover.** If a language or framework surfaces that the project's `agents.d/coding-standard/` does not have a module for (added to the project since it was scaffolded), there is no snapshot to honour for it: fall back to the lazy path below for that one axis — load just its `lib/` module — and note that `/coding-standard --update` would fold it into the project's own files.

When `agents.d/coding-standard/` is absent (or empty of module files), the project has no scaffolded standard; fall through to the lazy bootstrap.

### 2. Load the router

Load `${CLAUDE_PLUGIN_ROOT}/lib/coding-standard/_index.md` once, now. It carries the module table, the detection signals (which file markers and textual cues imply which language/framework axis), and the canonical precedence order. It holds no rules of its own — only the knowledge of *which* module to reach for *when*, and it is the authority on which languages and frameworks have a module at all. Keep it resident; it is how you route every later load.

### 3. Pull modules in lazily, as the context reveals them

The standing rule, tied to the act of writing: **before writing code in a language whose module you have not loaded, load that module first — if one exists for it** (the router lists which languages and frameworks have a module). Read it from `${CLAUDE_PLUGIN_ROOT}/lib/coding-standard/` the moment its axis is confirmed by a file marker, the code you are about to write, or an explicit statement:

- `general.md` — load it as soon as you do any code work (in practice, at once). It underpins every other module and applies to all code.
- The language module (`php.md`, `typescript.md`, `python.md`, `bash.md`, `javascript-vanilla.md`) when that language appears.
- The framework module when its markers appear — and they keep appearing through a session. PHP that turns out to be WordPress → pull `wordpress.md` then. A WordPress block → pull `wordpress-block.md`, plus `typescript.md` or `javascript-vanilla.md` depending on what the block's UI actually uses.
- A new axis the project's scaffold does not cover (step 1's exception) → pull its `lib/` module and any uncovered prerequisites it names, then drop the one-line `/coding-standard --update` hint.

If a language has **no** module (e.g. Go, Ruby, plain CSS — the router lists none), do not hunt for a file that is not there: apply `general.md` plus that language's own recognised standard and best practice, and proceed.

Each module self-describes the relationships it has with others, so loading them out of order, at different times, stays correct: where modules differ, the later/more-specific one wins (`wordpress.md` over `php.md`, `wordpress-block.md` over `typescript.md`), exactly as the router's canonical order states. Pulling a module in mid-task is normal and silent — load what the moment needs, then apply it.

### 4. Apply

Write, refactor, review, or design the code Thomas asked for, honouring every module in play — whether the project's own scaffolded files (step 1) or the ones you pulled from `lib/` (step 3). The modules are the contract; this file just gets you to the right ones at the right time.

## Related skills

- **`coding-standard`** — materialises the standard into a project as files under `agents.d/coding-standard/` and keeps them in sync (create / investigate drift / update). When Thomas asks to *scaffold*, *set up*, or *update the coding standard* in a project, that is the skill — not this one. `coder` only reads and applies; it writes no standard files.

## Notes

- Updating the standard means editing one or more module files in `lib/coding-standard/`. Projects that have already scaffolded their own `agents.d/coding-standard/` keep their snapshot until they explicitly re-run the `coding-standard` skill with an update; this is intentional, so updates to the standard don't silently change project behaviour.
- Adding a new framework or language to the standard is described in `lib/coding-standard/_index.md` and `scripts/scaffold.py` (the two places the module list and canonical order live).
