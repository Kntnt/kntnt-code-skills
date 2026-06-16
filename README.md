# kntnt-code-skills

`kntnt-code-skills` is a plugin for Claude Code and Cowork — a growing toolbox of generally useful tools for working with code, meant to take the routine and friction out of a developer's day. Today it holds three: **Kntnt's coding standard**, a set of rules applied automatically to any code-related task across PHP, JavaScript, TypeScript, Python, Bash, WordPress, Gutenberg blocks, Laravel, Svelte, SvelteKit, and any framework added later; a **release workflow** — `/release` and `/push` — that automates the bump-commit-tag-push-release cycle for any project; and an **issue-to-code orchestrator** — `/orchestrate` — that turns a project's open issues into implemented, independently verified, integrated code through a fleet of sub-agents. More tools will join them as common developer chores prove worth packaging.

## What you get

The plugin exposes one router skill, two release-workflow skills, an orchestration skill, and one command:

- **`coder`** — the router for the coding standard. It auto-triggers on code-related prompts (in any language), profiles the project to see which language and framework axes apply, loads the matching topic modules, and applies their rules. It can also scaffold the standard into a project as files (see *The coding standard* below).
- **`/release`** — the full release workflow on whatever project you invoke it in: reconcile the changelog with the real changes since the last release, bump the version per Semantic Versioning across every place it lives, integrate a feature branch into the main branch, commit, tag `vX.Y.Z`, push, and publish the platform release. Every irreversible step waits behind a single confirmation.
- **`/push`** — the routine companion: reconcile the changelog, commit, and push the current branch — no bump, tag, or release. Run it often so the changelog never falls behind.
- **`/orchestrate`** — an away-from-keyboard build that turns a project's open issues into finished code: it plans from the issues' dependency graph, dispatches one implementer sub-agent per issue (test-first), runs fresh independent sub-agents that adversarially verify what the gates cannot, integrates in dependency order, and ends with one consolidated report. It stops short of releasing.
- **`/help`** — a typed-only command (`/kntnt-code-skills:help [skill-name]`): a manpage-style overview of the plugin's skills, or one skill's details. Its output is rendered from the plugin's own `.claude-plugin/plugin.json` and `skills/<name>/SKILL.md` by `scripts/help.py`, so it never drifts from the actual skills.

## Installation

The plugin ships as a Claude Code marketplace. In Claude Code or Cowork, run:

```
/plugin marketplace add Kntnt/kntnt-code-skills
/plugin install kntnt-code-skills@kntnt-code-skills
```

The first line registers the marketplace from the GitHub repo (the bare `owner/repo` form is interpreted as a GitHub source); the second installs the plugin. Run `/reload-plugins` (or restart the session) if the skills do not appear immediately.

## The coding standard (`coder`)

The `coder` skill is the entry point for code work. It triggers on any request to write, implement, refactor, fix, review, or design code — in any language — profiles the project, loads the rules that apply, and writes to them. Nothing to invoke explicitly, nothing to configure. Its trigger boundary is broad on purpose: it fires on any code-shaped task and on anything that mentions a covered language, framework, or construct, in any language (the description's examples are English, but the equivalent request in any language triggers it equally).

It covers:

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

A project can sit on several axes at once — a WordPress block plugin is PHP + WordPress + TypeScript + Gutenberg — and the skill loads them all. How that load order and the override relationships work, and how to extend the standard with a new language or framework, is in *How `coder` is organized* below.

**Scaffolding into a project.** When you start a real new project, `coder` offers to write the relevant rules into `docs/coding-standards.md` and wire them into `CLAUDE.md` / `AGENTS.md`, so every AI agent on the codebase has the standard in context before writing a line. To run the scaffolder by hand, see *Advanced usage*.

## Releasing (`/release` and `/push`)

`/release` and `/push` automate the "bump, commit, tag, push, release" cycle for any project — not only this one. `/release` reconciles `CHANGELOG.md` against the real changes since the last release (commit messages first, diffs only as a fallback), bumps the version per Semantic Versioning across every place it lives, integrates a feature branch into the main branch by rebase and fast-forward, commits, tags `vX.Y.Z`, pushes, and publishes the platform release with notes from the changelog — plus the built user archive when the project ships one. Every irreversible step waits behind a single confirmation. `/push` is the routine companion: it reconciles the changelog, commits, and pushes the current branch, without bumping, tagging, or releasing.

Release notes for each version live in [`CHANGELOG.md`](CHANGELOG.md). The classification policy that decides which release class a change lands in is under *Versioning* below.

**Platform support.** Today `/release` publishes to **GitHub** via the `gh` CLI. Further forges are planned, detected by the remote's **host** rather than a fixed domain — so self-hosted and EU-hosted instances are first-class, not afterthoughts:

- **GitLab** — gitlab.com, self-managed, GitLab by Stackhero, and EU-hosted instances — via `glab`.
- **Gitea** and **Forgejo** — including **Codeberg** (EU-hosted Forgejo) — via `tea`.

On a remote whose forge is not yet supported, `/release` performs every git step (bump, commit, tag, push) and skips only the platform release, telling you so.

## Orchestrating issues (`/orchestrate`)

`/orchestrate` runs an away-from-keyboard build that turns a project's **`ready-for-agent`** issues into implemented, independently verified, integrated code. It is the last stage of the issue pipeline: once `/grill-with-docs`, `/to-issues`, and triage have produced fully-specified issues — each with an agent brief, acceptance criteria, and a `Blocked by` graph — invoke it once and walk away. A deterministic helper (`scripts/orchestrate.py`) reads the issues and computes the dependency graph and the concurrency **waves**; then a fleet of sub-agents runs three stages per issue — **implement** (one sub-agent, test-first red/green/refactor, demonstrating the failing test before the code), **verify** (fresh, independent sub-agents that adversarially review only what the gates cannot — correctness against intent, test quality, security and edge cases), and **integrate** (merge in dependency order, rebasing dependents). The orchestrator owns the quality bar and the decisions but never writes code or reads diffs itself; it reads the sub-agents' verdicts and ends with one consolidated report of what shipped and what still needs a human.

The control flow runs through the **Workflow tool** (engine: `skills/orchestrate/orchestrate.workflow.js`) where available — so the wave order, the capped fix↔verify loop, and worktree isolation are deterministic code rather than a long prose procedure an LLM re-interprets — and falls back to the Agent tool, optionally driven by `/goal`, where it is not. Every sub-agent runs **inside the interactive session** (counting against your subscription, never the headless `claude -p` credit pool), with the strong model and high reasoning effort spent on the implementers and adversarial verifiers rather than on routing. It **excludes `ready-for-human`** issues, scales verification depth to each issue's risk, and caps the fix↔verify loop so a stubborn issue is parked in the report rather than burning tokens. By default it opens a pull request per issue and leaves the merge to you; `--merge` integrates automatically where the project authorizes it. It stops short of releasing — when the merged work is ready to ship, that is `/release`. See [`skills/orchestrate/SKILL.md`](skills/orchestrate/SKILL.md) for the full flow, the cost model, and the arguments.

## Requirements

- **Claude Code or Cowork** with support for skills and YAML frontmatter.
- **[uv](https://docs.astral.sh/uv/)** — runs the bundled Python scripts (`bin/scaffold`, `scripts/audit.py`, `scripts/help.py`, `scripts/orchestrate.py`, `scripts/release.py`); it provisions Python 3.12+ from each script's PEP 723 metadata, and all of them use the standard library only. The test suite runs via `uv run --with pytest pytest`.
- **git**, and for `/release`'s platform publishing, the relevant forge CLI — **`gh`** for GitHub today.
- The `coder` skill itself applies the standard from context with no external dependencies. When there is no file-system access (chat-only, no working directory), it skips scaffolding and applies the standard from context.

## Advanced usage

Most usage is just invoking the skills. Two things are available for going further, short of contributing to the plugin itself.

**Running the scaffolder directly.** `coder` calls `bin/scaffold` automatically when scaffolding is appropriate, but it can also be run by hand. It is a command-style Python script — executable via its `#!/usr/bin/env -S uv run --script` shebang, with [uv](https://docs.astral.sh/uv/) as its only runtime dependency (it provisions Python from the script's PEP 723 metadata; the script itself is standard-library only):

```bash
skills/coder/bin/scaffold \
    --project-dir /path/to/new-project \
    --skill-dir   /path/to/kntnt-code-skills/skills/coder \
    --include     php,wordpress,typescript,wordpress-block \
    --touch-agents-md
```

Pass the modules that match the project's profile; `general` is always included automatically. The script writes `docs/coding-standards.md` and adds the import to `CLAUDE.md` (and to `AGENTS.md` with `--touch-agents-md`). It refuses to overwrite an existing `docs/coding-standards.md` and prints its first 20 lines instead. Run `skills/coder/bin/scaffold --help` for the full set of options, including `--dry-run` and `--force`.

**Release-skill arguments.** `/release` and `/push` take optional arguments:

- `/release minor` / `major` / `1.4.0` — force the bump level or an exact version, overriding the changelog-derived proposal.
- `/release --no-build` — skip rebuilding the user archive (when you just built it).
- `/release --yes` — skip the confirmation gate (never the first-run detection of where the version lives).
- `/push "message"` — use an exact commit message instead of an auto-drafted one.

## Contributing

Contributions are welcome within the project's scope. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for which kinds of changes are wanted, which want an issue first, and which are better kept in a fork. The rest of this section is the reference for changing the plugin safely.

For local development, load the repo directly without installing:

```bash
claude --plugin-dir /path/to/kntnt-code-skills
```

## Repository layout

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
├── commands/
│   └── help.md
├── skills/
│   ├── coder/
│   │   ├── SKILL.md
│   │   ├── general.md
│   │   ├── php.md
│   │   ├── wordpress.md
│   │   ├── wordpress-block.md
│   │   ├── typescript.md
│   │   ├── javascript-vanilla.md
│   │   ├── python.md
│   │   ├── bash.md
│   │   ├── bin/
│   │   │   └── scaffold
│   │   └── templates/
│   │       └── claude-md-template.md
│   ├── orchestrate/
│   │   ├── SKILL.md
│   │   └── orchestrate.workflow.js
│   ├── push/
│   │   └── SKILL.md
│   └── release/
│       └── SKILL.md
├── lib/
│   ├── changelog.md
│   └── gitignore-base.txt
├── scripts/
│   ├── audit.py
│   ├── help.py
│   ├── orchestrate.py
│   └── release.py
├── tests/
│   └── test_orchestrate.py
├── .pre-commit-config.yaml
├── .gitignore
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
├── NOTICE
└── README.md
```

`commands/` holds the typed-only `/help` command. `skills/` holds the four skills: `coder` (the coding-standard router and its topic modules), the `release`/`push` workflow skills, and `orchestrate` (the away-from-keyboard issue-to-code build). `lib/` holds text resources that skills include — `changelog.md` (the reconciliation procedure shared by `release` and `push`) and `gitignore-base.txt` (the universal `.gitignore` baseline). `scripts/` holds the standalone `uv`-run tools: the audit, the `/help` renderer, `release.py`'s deterministic CHANGELOG mechanics, and `orchestrate.py`'s dependency-graph, red/green, and report mechanics for `/orchestrate` (whose Workflow engine, `orchestrate.workflow.js`, lives beside its skill). `tests/` holds the pytest suite for `orchestrate.py`, run by both the audit workflow and the pre-commit hook.

## How `coder` is organized

The coding rules live in topic modules under `skills/coder/`, one file per language or framework. `SKILL.md` is a short **router** that decides which modules to load for a given project; the modules are the contract. They load in a canonical order (later wins on points where they differ), and override relationships are stated explicitly inside each module — WordPress overrides parts of PHP, the Gutenberg-block module overrides parts of TypeScript. The full flow, the override map, and the five-step *Adding a new module* checklist are in [`skills/coder/SKILL.md`](skills/coder/SKILL.md). The modules are self-contained, so each reads correctly whether the router loads it alone or the scaffolder concatenates it into one `docs/coding-standards.md`. All files are written in English, per the standard's own language rule.

**Updating the standard** means editing one or more module files in `skills/coder/`. Projects that have already scaffolded their own `docs/coding-standards.md` keep that snapshot until they explicitly re-scaffold — intentional, so a change to the standard never silently changes a project's behaviour.

## Versioning

Two standards govern releases: **Semantic Versioning** for the version number, and **[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) 1.1.0** for [`CHANGELOG.md`](CHANGELOG.md). SemVer is adapted here to a domain where a *change* is usually a coding rule rather than executable behaviour; the unit that determines the bump class is the code the standard would prescribe for a given situation.

**Major (X.0.0).** A change that alters what the standard prescribes for a category of prior situations without being a bug fix. Examples: switching the default brace style, changing a default toolchain, dropping `declare(strict_types=1)`, or reversing an override relationship between modules. Re-applying the standard to existing code would now yield materially different code.

**Minor (0.X.0).** A new language or framework module, a new skill or command, or an extension of an existing rule that does not change what the standard prescribed for prior situations. Example: adding a `laravel.md` module, or adding a new permitted modern-language feature without forbidding the old one.

**Patch (0.0.X).** Bug fixes, documentation changes, prose clarifications that do not change the rule set, and behaviour-neutral refactors — for example correcting a broken example or moving logic between files without changing what it does.

**Borderline cases.** When an existing rule is tightened or loosened, it is a major bump if the prescribed code for a typical situation plausibly changes, otherwise minor. Uncertainty resolves to major — the safer side.

**License change.** The transition to Apache 2.0 is recorded as a *Changed* event in whichever release ships it. It does not itself change what the standard prescribes, so it does not force a major bump.

**Version-bump moment.** A release is one commit that does four things together: (1) bump the `version` field in `.claude-plugin/plugin.json`, (2) bump the matching `version` in `skills/coder/SKILL.md`'s frontmatter, (3) move the `[Unreleased]` block in `CHANGELOG.md` to a concrete version heading with an ISO date, and (4) set a matching git tag. `scripts/audit.py` verifies the first three are consistent; the git tag is a manual responsibility at release time. The `/release` skill performs all four steps end to end.

## Authoring rules

These rules govern how to edit the files in this plugin. They exist to prevent a recurring failure mode where well-meaning changes reintroduce architectural drift — duplicated prose between modules, cross-references that bind a module to one specific sibling, rules that contradict each other silently. They apply to anyone (human or AI) modifying anything under `skills/`.

**1. Modules are self-contained.** Each topic module reads correctly whether the router loads it alone or the scaffolder concatenates it into one file. A module describes its own rules; it does not depend on a sibling module being present to make sense.

**2. Cross-references use generic phrasing.** When a module needs to mention another axis, it does so descriptively (*WordPress projects override the PSR-12 surface style*) rather than by naming a file or assuming load order. The architectural map — who overrides what, in what order — lives in `SKILL.md` and this README, not scattered through the modules.

**3. Override relationships are stated explicitly.** When one module overrides another (WordPress over PHP, WordPress-block over TypeScript), the overriding module says so in its own prose, so a reader who loads it understands the bigger picture.

**4. Universal rules in `general.md`, language rules in their module.** A rule that holds across languages (English identifiers, comment philosophy, priority order) goes in `general.md`. A rule whose realisation depends on the language goes in that language's module.

**5. New module = follow the checklist.** Adding a language or framework means following the five-step *Adding a new module* checklist in `SKILL.md`: create the module file, add a row to the modules table, add a detection clause to the flow, add the module to step 4's canonical order *and* to `bin/scaffold`'s `CANONICAL_ORDER`, and update the `description` frontmatter. The audit enforces the canonical-order half of step 4.

**6. Lean prose, imperative with whys.** Prefer one imperative followed by a short explanation of why, rather than ALL-CAPS, MUSTs, or stacked redundant clauses. Today's models do better with reasoning than with commands.

**7. No vague descriptions.** Phrases like *clean code* without specifying what is meant invite the model to fill the gap with its own interpretation. Either specify or let a concrete rule carry the definition.

### Audit checklist before committing changes

Items marked **(auto)** are enforced by `scripts/audit.py`, which runs as a pre-commit hook and as the `audit` GitHub Actions job on every push and PR. Both run it with [uv](https://docs.astral.sh/uv/) (`uv run scripts/audit.py`), which provisions Python from the script's PEP 723 metadata. Items marked **(manual)** require human judgement. Install the pre-commit hook locally with `uv tool install pre-commit && pre-commit install`; from then on the audit fires before every commit and CI re-runs it on the remote.

- **(auto)** `.claude-plugin/plugin.json` parses as JSON, carries the `name`, `version`, and `description` fields, and its `version` matches the latest non-`[Unreleased]` heading in `CHANGELOG.md`.
- **(auto)** The topic-module files in `skills/coder/` and `bin/scaffold`'s `CANONICAL_ORDER` list the same modules — no module file without a canonical-order entry, no entry without a file.
- **(auto)** The `coder` skill's frontmatter `version` matches `plugin.json`'s version.
- **(manual)** Each module is self-contained — no reference to a sibling module by filename, no assumption that another module is loaded.
- **(manual)** Any override relationship a module participates in is stated in that module's own prose.
- **(manual)** The modules table in `SKILL.md`, the detection clauses in step 1 of the flow, and the canonical order in step 4 all agree with the set of module files present.
- **(manual)** All prose and identifiers are in English.

## License

Licensed under the Apache License 2.0. The full licence text is in [`LICENSE`](LICENSE), and the copyright and attribution notice is in [`NOTICE`](NOTICE). Contributions are accepted under the same terms by virtue of Apache 2.0 §5 — see [`CONTRIBUTING.md`](CONTRIBUTING.md) for the contribution-scope guidance.

## About

Made by [Kntnt](https://kntnt.com). See [`NOTICE`](NOTICE) for the attribution and copyright statement that accompanies redistributions under the Apache 2.0 licence.
