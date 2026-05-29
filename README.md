# kntnt-code-skills

A Claude Code plugin that applies Kntnt's coding standard to any code-related task — writing, modifying, refactoring, reviewing, or designing PHP, JavaScript, TypeScript, Python, Bash, WordPress, Gutenberg blocks, Laravel, Svelte, SvelteKit, and any framework added to the standard later.

The plugin's `coder` skill is also a scaffolder: when a real new project is being started, it offers to assemble `docs/coding-standards.md` and wire it into `CLAUDE.md` / `AGENTS.md` so every AI agent working on the codebase has the standard in context before writing code.

## Components

| Path | What it is |
|---|---|
| `.claude-plugin/plugin.json` | Plugin manifest. |
| `.claude-plugin/marketplace.json` | Single-plugin marketplace catalog, so the repo can be added with `/plugin marketplace add`. |
| `skills/coder/SKILL.md` | The router skill — auto-triggers on code-related prompts and orchestrates the flow. |
| `skills/coder/*.md` | Topic modules with the actual coding rules. |
| `skills/coder/bin/scaffold` | Command-style Bun/TypeScript script that assembles `docs/coding-standards.md` and wires it into `CLAUDE.md` / `AGENTS.md`. |
| `skills/coder/templates/` | Starter templates for `CLAUDE.md` / `AGENTS.md`. |

## Modules

The actual coding rules live in topic modules. `SKILL.md` is the router that decides which modules to load.

| File | Loaded when |
|---|---|
| `general.md` | Always — universal rules every other module presupposes. |
| `php.md` | When PHP is present. |
| `wordpress.md` | When the project is a WordPress plugin or theme. |
| `wordpress-block.md` | When the project includes Gutenberg blocks. |
| `typescript.md` | When TypeScript is present. |
| `javascript-vanilla.md` | When the project has plain browser JavaScript without a build step. |
| `python.md` | When Python is present. |
| `bash.md` | When Bash is present. |

See `skills/coder/SKILL.md` for the full flow, the override relationships between modules, and the *Adding a new module* section for how to extend the standard with new frameworks (Laravel, Svelte, SvelteKit, …).

## Installation

Install via Claude Code's plugin system. This is a two-step process: add the repo as a marketplace, then install the plugin from it.

```
/plugin marketplace add Kntnt/kntnt-code-skills
/plugin install kntnt-code-skills@kntnt-code-skills
```

Then run `/reload-plugins` (or restart Claude Code) to activate it.

For local development, load the repo directly without installing:

```bash
claude --plugin-dir /path/to/kntnt-code-skills
```

## Scaffolding the standard into a project

The `coder` skill calls `bin/scaffold` automatically when scaffolding is appropriate, but the script can also be run directly. It is a command-style Bun/TypeScript script — executable via its shebang, with Bun as its only runtime dependency:

```bash
skills/coder/bin/scaffold \
    --project-dir /path/to/new-project \
    --skill-dir   /path/to/kntnt-code-skills/skills/coder \
    --include     php,wordpress,typescript,wordpress-block \
    --touch-agents-md
```

Pass the modules that match the project's profile. `general` is always included automatically. The script writes `docs/coding-standards.md` and adds the import to `CLAUDE.md` (and to `AGENTS.md` if `--touch-agents-md` is set). It refuses to overwrite an existing `docs/coding-standards.md` and prints its first 20 lines instead, so you can decide what to do.

Run `skills/coder/bin/scaffold --help` for the full set of options, including `--dry-run` and `--force`.

## Updating the standard

Updating the standard means editing one or more module files in `skills/coder/`. Projects that have already scaffolded their own `docs/coding-standards.md` keep their snapshot until they explicitly re-scaffold; this is intentional, so updates to the standard don't silently change project behaviour.

## License

Internal — Kntnt.
