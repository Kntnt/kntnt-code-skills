---
name: thomas-coder
description: >
  Apply Thomas Barregren's coding standard to any code-shaped task —
  writing, modifying, refactoring, reviewing, or designing PHP,
  JavaScript, TypeScript, WordPress, Gutenberg blocks, Laravel,
  Svelte, SvelteKit, or any framework added to the standard later;
  starting a new project in any of those; or scaffolding the standard
  itself into a project as files. Trigger on prompts like "skriv
  kod", "implementera", "refaktorera", "fixa buggen", "skapa en
  klass", "skriv en funktion", "review the code", "design a", "skapa
  en plugin", "skapa en WordPress-plugin", "starta en Laravel-app",
  "ny SvelteKit-applikation", "build a CLI in TypeScript", "lägg till
  kodningsstandarden", "scaffold standards", "init coding standards",
  and on any task that mentions one of those languages or frameworks
  or a code construct in them. When in doubt, trigger.
---

# thomas-coder

This skill is the entry point for any code-related task in Thomas's
setup. The actual coding rules live in topic modules; this file is
the router. It decides which modules to load, whether to scaffold
the standard into the project as files, and either way it ends by
applying the standard to the work Thomas asked for.

## The modules

| File | When to load |
|---|---|
| `general.md` | Always. The universal rules every other module presupposes. |
| `php.md` | When PHP is present in the project. |
| `wordpress.md` | When the project is a WordPress plugin or theme (always together with `php.md`). |
| `wordpress-block.md` | When the project includes Gutenberg blocks. Always together with `wordpress.md` and `typescript.md`. Detect by `block.json` files, `@wordpress/scripts` in `package.json`, `register_block_type()` in PHP, or a clear textual statement. |
| `typescript.md` | When TypeScript is present in the project. |
| `javascript-vanilla.md` | When the project has plain browser JavaScript without a build step (typically PHP / WP plugin admin scripts). |

Future additions (Laravel, Svelte, SvelteKit, etc.) follow the same
pattern. To add a new module, see *Adding a new module* at the end
of this file.

## The flow

Run through these four steps for every invocation. Any single task
may use all of them or just the last one.

### 1. Profile the project

Always read `general.md` first — it is the foundation every language
module presupposes (priority order, language, identifiers, comment
philosophy, prefix conventions). Then determine which language and
framework axes apply by inspecting the working directory and the
prompt:

- **PHP** — `composer.json`, `*.php`, or a clear textual statement.
- **TypeScript** — `tsconfig.json`, `*.ts`, `*.tsx`, or a textual
  statement.
- **WordPress** — `wp-config*`, a plugin/theme header in a PHP file,
  a `Plugin Name:` header, or a textual statement.
- **Gutenberg blocks** — `block.json`, `@wordpress/scripts` in
  `package.json`, `register_block_type()` in PHP, or a textual cue
  ("block plugin", "Gutenberg block", "block editor").
- **Plain browser JavaScript** — `*.js` without a TypeScript build
  in the project (typical in WordPress plugins).
- **Future framework axes** (Laravel, Svelte, SvelteKit, …) — detect
  by their conventional markers: `artisan` for Laravel,
  `svelte.config.js` for Svelte, `svelte.config.js` plus a
  `@sveltejs/kit` dependency for SvelteKit, etc. If the framework
  matches but no module file exists yet for it, say so plainly,
  apply `general.md` plus the language module, and proceed.

A project may belong to several axes at once. WordPress plugins are
PHP + WordPress; block plugins add WordPress + TypeScript +
WordPress-block. If the profile is genuinely unclear after looking
— typically when Thomas asks for code in isolation with no
surrounding project context — load the modules that match the
language(s) of the request and proceed without pausing to ask,
unless something materially depends on the answer.

### 2. Decide whether to scaffold the standard into the project

Three buckets:

**Scaffold without asking** when Thomas explicitly requests it:
"scaffolda kodningsstandarden", "lägg till kodningsstandarden",
"init coding standards", "set up coding standards", "scaffold
standards", or similar phrasing. Go straight to step 3.

**Offer to scaffold** (one short question, then proceed on the
answer) when *all* of the following hold:

- The task creates or initialises a real project — "skapa en
  WordPress-plugin", "starta en Laravel-app", "scaffolda en ny
  SvelteKit-applikation", or work that will produce a multi-file
  codebase rather than a single snippet.
- The working directory is either empty (perhaps with `.git`) or
  does not yet contain `docs/coding-standards.md`.
- The profile from step 1 is non-trivial — more than a single
  language axis, or any framework axis (WordPress, WordPress-block,
  Laravel, SvelteKit, …).

The question is roughly: *"This looks like a real project — want me
to scaffold the coding standard into `docs/coding-standards.md` and
wire it into `CLAUDE.md` before I write code?"* If yes, go to step
3. If no, go to step 4.

**Skip scaffolding** otherwise — go straight to step 4. This covers:

- Isolated code tasks ("skriv en funktion som …", "fixa den här
  buggen", "review this snippet").
- Existing projects that already have `docs/coding-standards.md` —
  the project's file wins. Reconcile silently and proceed.
- Quick experiments, throwaway scripts, snippets with no project
  context.

### 3. Scaffold (when requested or accepted)

Scaffolding is deterministic file work. Do it through the bundled
script rather than reconstructing the logic each time:

```bash
python3 <skill-dir>/scripts/scaffold.py \
    --project-dir <project-root> \
    --skill-dir <skill-dir> \
    --include php,wordpress,typescript,wordpress-block
```

Pass the same module names you'd load for the project's profile
(omit `general` — the script always includes it). Order on the
command line doesn't matter; the script imposes the canonical order
internally.

The script:

1. Sanity-checks the project directory. Refuses to write into a
   directory with no `.git`, `composer.json`, or `package.json`
   unless `--force` is set.
2. Concatenates the requested modules in the canonical order
   (general → php → wordpress → typescript → wordpress-block →
   javascript-vanilla) into `docs/coding-standards.md`.
3. Refuses to overwrite an existing `docs/coding-standards.md` and
   prints its first 20 lines instead, so the calling agent (or
   Thomas) can decide what to do.
4. Creates `CLAUDE.md` from `templates/claude-md-template.md` if
   missing. If it exists, inserts `@docs/coding-standards.md`
   under a `## Coding standards` heading without disturbing other
   content. If the import is already there, leaves the file alone.
5. With `--touch-agents-md`, mirrors the same operation on
   `AGENTS.md`. Run it that way whenever Thomas asks for `AGENTS.md`
   too, or whenever the project will be edited by non-Claude agents
   (Copilot, Cursor, Codex).
6. Prints a one-line summary of what it did per file.

If the script returns a non-zero exit code, read its stderr,
explain the situation to Thomas, and don't attempt to redo the
work by hand — the script is the source of truth for what
scaffolding looks like.

After scaffolding, continue to step 4 to apply the standard to
whatever task came next.

### 4. Apply the standard

Read the modules matching the project profile, in this canonical
order (later wins on points where they differ):

1. `general.md` (already loaded in step 1)
2. `php.md` (if PHP)
3. `wordpress.md` (if WordPress) — overrides parts of `php.md`
4. `typescript.md` (if TypeScript)
5. `wordpress-block.md` (if Gutenberg blocks) — overrides parts of
   `typescript.md`
6. `javascript-vanilla.md` (if plain browser JS)

The override relationships are stated explicitly inside each
module — WordPress projects override PSR-12 with the WordPress
Coding Standards; block code stays on the `@wordpress/scripts`
happy path instead of the Bun/Biome TypeScript pipeline.

Then write, refactor, review, or design the code Thomas asked for,
honouring the loaded rules. The modules are the contract; this
file just gets you there.

## Adding a new module

When adding a new framework or language to the standard:

1. **Create `<topic>.md`** in this skill folder. Match the existing
   modules' shape — a one-paragraph "When this applies" intro, then
   sections for baseline / required modern features / surface style
   / file layout / tooling. State any override relationships
   explicitly inside the module so a reader who loads the module
   alone still understands the bigger picture.
2. **Add a row to the modules table** at the top of this file,
   including the detection signal.
3. **Add a detection clause to step 1** of the flow above. Match
   the shape of the existing axes.
4. **Update the canonical order** in step 4 (and in
   `scripts/scaffold.py`'s `CANONICAL_ORDER`) if the new module
   has override relationships with an existing one. Later in the
   order wins on differences.
5. **Update the `description` frontmatter** to include the
   framework's name in the trigger list, so the skill keeps
   triggering on "starta en X-app"-style prompts.

The modules are self-contained on purpose. Cross-references between
them use generic phrasing (e.g. "WordPress projects override the
PSR-12 surface style") so each module reads correctly whether
loaded alone in step 4 or concatenated into a single
`docs/coding-standards.md` by the scaffold script.

## Notes

- Updating the standard means editing one or more module files in
  this skill. Projects that have already scaffolded their own
  `docs/coding-standards.md` keep their snapshot until they
  explicitly re-scaffold; this is intentional, so updates to the
  skill don't silently change project behaviour.
- Scaffolding requires file-system access to the project directory
  (Claude Code or Cowork). If access is not available — chat-only,
  no working directory — say so, skip step 3, and apply the
  standard from context instead.

## Files in this skill

- `SKILL.md` — this file.
- `general.md` — universal rules (always loaded).
- `php.md` — PHP rules.
- `wordpress.md` — WordPress overrides and additions.
- `wordpress-block.md` — Gutenberg block-specific rules.
- `typescript.md` — TypeScript rules.
- `javascript-vanilla.md` — plain browser JavaScript rules.
- `scripts/scaffold.py` — assembles `docs/coding-standards.md` and
  wires it into `CLAUDE.md` / `AGENTS.md`.
- `templates/claude-md-template.md` — starter for a fresh
  `CLAUDE.md` (or `AGENTS.md`).
