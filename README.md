# thomas-coder

A Claude skill that applies Thomas Barregren's coding standard to any code-related task — writing, modifying, refactoring, reviewing, or designing PHP, JavaScript, TypeScript, WordPress, Gutenberg blocks, Laravel, Svelte, SvelteKit, and any framework added to the standard later.

The skill is also a scaffolder: when a real new project is being started, it offers to assemble `docs/coding-standards.md` and wire it into `CLAUDE.md` / `AGENTS.md` so every AI agent working on the codebase has the standard in context before writing code.

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

See `SKILL.md` for the full flow, the override relationships between modules, and the *Adding a new module* section for how to extend the standard with new frameworks (Laravel, Svelte, SvelteKit, …).

## Installation

Drop the folder under your Claude skills directory, or install the packaged `.skill` file using your environment's skill installer.

To rebuild the `.skill` package from source:

```bash
python3 /path/to/skill-creator/scripts/package_skill.py \
    /path/to/thomas-coder \
    /path/to/output-dir
```

## Scaffolding the standard into a project

The skill calls `scripts/scaffold.py` automatically when scaffolding is appropriate, but the script can also be run directly:

```bash
python3 scripts/scaffold.py \
    --project-dir /path/to/new-project \
    --skill-dir   /path/to/thomas-coder \
    --include     php,wordpress,typescript,wordpress-block \
    --touch-agents-md
```

Pass the modules that match the project's profile. `general` is always included automatically. The script writes `docs/coding-standards.md` and adds the import to `CLAUDE.md` (and to `AGENTS.md` if `--touch-agents-md` is set). It refuses to overwrite an existing `docs/coding-standards.md` and prints its first 20 lines instead, so you can decide what to do.

Run `python3 scripts/scaffold.py --help` for the full set of options, including `--dry-run` and `--force`.

## Updating the standard

Updating the standard means editing one or more module files in this repo. Projects that have already scaffolded their own `docs/coding-standards.md` keep their snapshot until they explicitly re-scaffold; this is intentional, so updates to the standard don't silently change project behaviour.

## License

Internal — Kntnt.
