# kntnt-code-skills

A plugin for Claude Code and Cowork that applies Kntnt's coding standard to any code-related task — writing, modifying, refactoring, reviewing, or designing PHP, JavaScript, TypeScript, Python, Bash, WordPress, Gutenberg blocks, Laravel, Svelte, SvelteKit, and any framework added to the standard later. The actual coding rules live in topic modules under `skills/coder/`, one file per language or framework; a single router skill decides which modules to load for the task at hand. The standard is extensible with one file per additional language or framework.

## What the plugin does

The plugin exposes one model-invoked skill:

- `coder` — the router. It auto-triggers on code-related prompts (in Swedish or English), profiles the project to determine which language and framework axes apply, loads the matching topic modules, and applies their rules to the work. It is also a scaffolder: when a real new project is being started, it offers to assemble `docs/coding-standards.md` from the relevant modules and wire it into `CLAUDE.md` / `AGENTS.md`, so every AI agent working on the codebase has the standard in context before writing code.

The skill's frontmatter `description` defines the trigger boundary — it fires on prompts like *skriv kod*, *implementera*, *refaktorera*, *fixa buggen*, *skapa en klass*, *review the code*, *skapa en WordPress-plugin*, *starta en Laravel-app*, *skriv ett Python-skript*, *scaffold standards*, and on any task that mentions one of the covered languages or frameworks or a code construct in them.

## Modules

The actual coding rules live in topic modules. `SKILL.md` is the router that decides which modules to load; the modules are the contract.

| File | Loaded when |
|---|---|
| `general.md` | Always — the universal rules every other module presupposes (priority order, language, identifiers, comment philosophy, prefix conventions). |
| `php.md` | When PHP is present. |
| `wordpress.md` | When the project is a WordPress plugin or theme (always together with `php.md`; overrides parts of it). |
| `wordpress-block.md` | When the project includes Gutenberg blocks (always together with `wordpress.md` and `typescript.md`; overrides parts of `typescript.md`). |
| `typescript.md` | When TypeScript is present. |
| `javascript-vanilla.md` | When the project has plain browser JavaScript without a build step. |
| `python.md` | When Python is present. |
| `bash.md` | When Bash is present. |

The modules are loaded in a canonical order (later wins on points where they differ); the override relationships are stated explicitly inside each module. See [`skills/coder/SKILL.md`](skills/coder/SKILL.md) for the full flow, the override relationships, and the *Adding a new module* section for how to extend the standard with new frameworks (Laravel, Svelte, SvelteKit, …).

## Installation

The plugin ships as a Claude Code marketplace. In Claude Code or Cowork, run:

```
/plugin marketplace add Kntnt/kntnt-code-skills
/plugin install kntnt-code-skills@kntnt-code-skills
```

The first line registers the marketplace from the GitHub repo (the bare `owner/repo` form is interpreted as a GitHub source); the second installs the plugin from it. Run `/reload-plugins` (or restart the session) if the skill does not appear immediately.

**Local development (fallback).** Load the repo directly without installing:

```bash
claude --plugin-dir /path/to/kntnt-code-skills
```

Release notes for each version live in [`CHANGELOG.md`](CHANGELOG.md). The versioning policy that governs which release class a change lands in is described under *Versioning* below.

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

## File structure

```
kntnt-code-skills/
├── .claude-plugin/
│   ├── plugin.json
│   └── marketplace.json
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   └── bug.md
│   └── workflows/
│       └── audit.yml
├── skills/
│   └── coder/
│       ├── SKILL.md
│       ├── general.md
│       ├── php.md
│       ├── wordpress.md
│       ├── wordpress-block.md
│       ├── typescript.md
│       ├── javascript-vanilla.md
│       ├── python.md
│       ├── bash.md
│       ├── bin/
│       │   └── scaffold
│       └── templates/
│           └── claude-md-template.md
├── scripts/
│   └── audit.py
├── .pre-commit-config.yaml
├── .gitignore
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
├── NOTICE
└── README.md
```

`SKILL.md` is a short router that references the topic modules. The modules are self-contained so each reads correctly whether loaded alone by the router or concatenated into a single `docs/coding-standards.md` by the scaffolder. All files are written in English, per the standard's own language rule.

## Versioning

The plugin follows Semantic Versioning, adapted to a domain where a *change* is usually a coding rule rather than executable behaviour. The unit that determines the bump class is the code the standard would prescribe for a given situation. Each release is recorded in [`CHANGELOG.md`](CHANGELOG.md) using Keep a Changelog 1.1.0.

**Major (X.0.0).** A change that alters what the standard prescribes for a category of prior situations without being a bug fix. Examples: switching the default brace style, changing a default toolchain, dropping `declare(strict_types=1)`, or reversing an override relationship between modules. Re-applying the standard to existing code would now yield materially different code.

**Minor (0.X.0).** A new language or framework module, a new skill, or an extension of an existing rule that does not change what the standard prescribed for prior situations. Example: adding a `laravel.md` module, or adding a new permitted modern-language feature without forbidding the old one.

**Patch (0.0.X).** Bug fixes, documentation changes, prose clarifications that do not change the rule set, and behaviour-neutral refactors — for example correcting a broken example or moving logic between files without changing what it does.

**Borderline cases.** When an existing rule is tightened or loosened, it is a major bump if the prescribed code for a typical situation plausibly changes, otherwise minor. Uncertainty resolves to major — the safer side.

**License change.** The transition to Apache 2.0 is recorded as a *Changed* event in whichever release ships it. It does not itself change what the standard prescribes, so it does not force a major bump.

**Version-bump moment.** A release is one commit that does four things together: (1) bump the `version` field in `.claude-plugin/plugin.json`, (2) bump the matching `version` in `skills/coder/SKILL.md`'s frontmatter, (3) move the `[Unreleased]` block in `CHANGELOG.md` to a concrete version heading with an ISO date, and (4) set a matching git tag. `scripts/audit.py` verifies the first three are consistent; the git tag is a manual responsibility at release time.

## Authoring rules

These rules govern how to edit the files in this plugin. They exist to prevent a recurring failure mode where well-meaning changes reintroduce architectural drift — duplicated prose between modules, cross-references that bind a module to one specific sibling, rules that contradict each other silently. The rules apply to anyone (human or AI) modifying anything under `skills/`.

**1. Modules are self-contained.** Each topic module reads correctly whether the router loads it alone or the scaffolder concatenates it into one file. A module describes its own rules; it does not depend on a sibling module being present to make sense.

**2. Cross-references use generic phrasing.** When a module needs to mention another axis, it does so descriptively (*WordPress projects override the PSR-12 surface style*) rather than by naming a file or assuming load order. The architectural map — who overrides what, in what order — lives in `SKILL.md` and this README, not scattered through the modules.

**3. Override relationships are stated explicitly.** When one module overrides another (WordPress over PHP, WordPress-block over TypeScript), the overriding module says so in its own prose, so a reader who loads it understands the bigger picture.

**4. Universal rules in `general.md`, language rules in their module.** A rule that holds across languages (English identifiers, comment philosophy, priority order) goes in `general.md`. A rule whose realisation depends on the language goes in that language's module.

**5. New module = follow the checklist.** Adding a language or framework means following the five-step *Adding a new module* checklist in `SKILL.md`: create the module file, add a row to the modules table, add a detection clause to the flow, add the module to step 4's canonical order *and* to `bin/scaffold`'s `CANONICAL_ORDER`, and update the `description` frontmatter. The audit enforces the canonical-order half of step 4.

**6. Lean prose, imperative with whys.** Prefer one imperative followed by a short explanation of why, rather than ALL-CAPS, MUSTs, or stacked redundant clauses. Today's models do better with reasoning than with commands.

**7. No vague descriptions.** Phrases like *clean code* without specifying what is meant invite the model to fill the gap with its own interpretation. Either specify or let a concrete rule carry the definition.

### Audit checklist before committing changes

Items marked **(auto)** are enforced by `scripts/audit.py`, which runs as a pre-commit hook and as the `audit` GitHub Actions job on every push and PR. Items marked **(manual)** require human judgement and are not scripted. Install the pre-commit hook locally with `pip install pre-commit && pre-commit install`; from then on the audit fires before every commit and CI re-runs it on the remote.

- **(auto)** `.claude-plugin/plugin.json` parses as JSON, carries the `name`, `version`, and `description` fields, and its `version` matches the latest non-`[Unreleased]` heading in `CHANGELOG.md`.
- **(auto)** The topic-module files in `skills/coder/` and `bin/scaffold`'s `CANONICAL_ORDER` list the same modules — no module file without a canonical-order entry, no entry without a file.
- **(auto)** The `coder` skill's frontmatter `version` matches `plugin.json`'s version.
- **(manual)** Each module is self-contained — no reference to a sibling module by filename, no assumption that another module is loaded.
- **(manual)** Any override relationship a module participates in is stated in that module's own prose.
- **(manual)** The modules table in `SKILL.md`, the detection clauses in step 1 of the flow, and the canonical order in step 4 all agree with the set of module files present.
- **(manual)** All prose and identifiers are in English.

## Requirements

The plugin requires Claude Code or Cowork with support for skills and YAML frontmatter. The `coder` skill applies the standard from context with no external dependencies. The scaffolder (`bin/scaffold`) requires [Bun](https://bun.sh) and file-system access to the project directory; when access is not available (chat-only, no working directory), the skill applies the standard from context and skips scaffolding. The audit script (`scripts/audit.py`) requires Python 3.12+ and uses the standard library only.

## License

Licensed under the Apache License 2.0. The full licence text is in [`LICENSE`](LICENSE), and the copyright and attribution notice is in [`NOTICE`](NOTICE). Contributions are accepted under the same terms by virtue of Apache 2.0 §5 — see [`CONTRIBUTING.md`](CONTRIBUTING.md) for the contribution-scope guidance.

## About

Made by [Kntnt](https://kntnt.com). See [`NOTICE`](NOTICE) for the attribution and copyright statement that accompanies redistributions under the Apache 2.0 licence.
