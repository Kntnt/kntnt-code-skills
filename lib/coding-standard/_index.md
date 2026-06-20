# Coding standard — index

Shared profiling knowledge for the coding standard: which modules exist, how to detect which ones a project needs, and the order in which they apply. Both the `coder` skill (which reads the modules to *apply* the standard) and the `coding-standard` skill (which writes them into a project) load this file. It carries no rules of its own — the rules live in the module files beside it.

This file's name starts with `_` because it is not a standard module: it is never materialised into a project's `agents.d/coding-standard/`. Only the modules listed below are.

## The modules

| File | When it applies |
|---|---|
| `general.md` | Always. The universal rules every other module presupposes. |
| `php.md` | When PHP is present in the project. |
| `wordpress.md` | When the project is a WordPress plugin or theme (always together with `php.md`). |
| `wordpress-block.md` | When the project includes Gutenberg blocks. Always together with `wordpress.md` and `typescript.md`. |
| `typescript.md` | When TypeScript is present in the project. |
| `javascript-vanilla.md` | When the project has plain browser JavaScript without a build step (typically PHP / WP plugin admin scripts). |
| `python.md` | When Python is present in the project. |
| `bash.md` | When Bash is present in the project. |

Future additions (Laravel, Svelte, SvelteKit, …) follow the same pattern — a new module file beside this one, a row here, a detection clause below, and a place in the canonical order.

## Detecting which modules a project needs

Inspect the working directory and the prompt. A project may match several axes at once: WordPress plugins are PHP + WordPress; block plugins add WordPress + TypeScript + WordPress-block.

- **PHP** — `composer.json`, `*.php`, or a clear textual statement.
- **TypeScript** — `tsconfig.json`, `*.ts`, `*.tsx`, or a textual statement.
- **WordPress** — `wp-config*`, a plugin/theme header in a PHP file, a `Plugin Name:` header, or a textual statement.
- **Gutenberg blocks** — `block.json`, `@wordpress/scripts` in `package.json`, `register_block_type()` in PHP, or a textual cue ("block plugin", "Gutenberg block", "block editor").
- **Plain browser JavaScript** — `*.js` without a TypeScript build in the project (typical in WordPress plugins).
- **Python** — `pyproject.toml`, `requirements.txt`, `*.py`, or a textual statement.
- **Bash** — `*.sh`, `*.bash`, a `#!/usr/bin/env bash` shebang, or a textual statement.
- **Future framework axes** (Laravel, Svelte, SvelteKit, …) — detect by their conventional markers: `artisan` for Laravel, `svelte.config.js` for Svelte, `svelte.config.js` plus a `@sveltejs/kit` dependency for SvelteKit, etc. If the framework matches but no module file exists yet, say so plainly, apply `general.md` plus the language module, and proceed.

If the profile is genuinely unclear after looking — typically when code is requested in isolation with no surrounding project context — match the language(s) of the request and proceed without pausing to ask, unless something materially depends on the answer.

## Canonical order

The modules apply in this order. Later modules override earlier ones on the points where they differ, so the order is also the precedence order:

1. `general.md`
2. `php.md`
3. `wordpress.md` — overrides parts of `php.md` (WordPress Coding Standards over PSR-12)
4. `typescript.md`
5. `wordpress-block.md` — overrides parts of `typescript.md` (the `@wordpress/scripts` happy path over the Bun/Biome pipeline)
6. `javascript-vanilla.md`
7. `python.md`
8. `bash.md`

The override relationships are stated explicitly inside each module too, so a module read alone still makes sense. `scripts/scaffold.py` encodes the same order and override wiring in code (it generates the on-demand file headers); keep the two in step when adding a module.
