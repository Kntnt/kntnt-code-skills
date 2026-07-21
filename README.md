# kntnt-code-skills

[![License](https://img.shields.io/github/license/Kntnt/kntnt-code-skills)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/Kntnt/kntnt-code-skills)](https://github.com/Kntnt/kntnt-code-skills/releases/latest)

`kntnt-code-skills` is a plugin for Claude Code and Cowork – a growing toolbox of generally useful tools for working with code, meant to take the routine and friction out of a developer's day.

## Description

`kntnt-code-skills` is for developers who work with Claude Code or Cowork and want the repetitive parts of the job handled consistently. It is a growing toolbox rather than a single tool: each skill or command takes one recurring chore off your hands, and more join them as common developer chores prove worth packaging.

### Key features

- **Kntnt's coding standard** – a set of rules across PHP, JavaScript, TypeScript, Python, Bash, WordPress, Gutenberg blocks, Laravel, Svelte, SvelteKit and any framework added later, applied automatically to any code task by the `coder` skill and materialised into a project as files by the `/coding-standard` skill.
- **Project initialiser and reconciler** – `/init` brings a new project up to the Kntnt baseline (git, AGENTS.md skeleton, coding standard, licence, README/CHANGELOG/CONTRIBUTING, `.gitignore`), and `/doctor` re-checks an existing project against that baseline and proposes the fixes.
- **Release workflow** – `/release`, `/push` and `/commit` automate the bump-commit-tag-push-release cycle for any project.
- **Issue-to-code orchestrator** – `/orchestrate` turns a project's open issues into implemented, independently verified, integrated code through a fleet of sub-agents.
- **Typed `/help` command** – the plugin overview, or a single skill's full manual page, echoed verbatim from the plugin's own metadata so it can never drift from the manual pages.

### The problem

Much of a developer's day goes on routine, friction-laden chores rather than on the work itself: holding code to a consistent standard across many languages and frameworks, standing a new project up correctly, running the bump-commit-tag-push-release cycle by hand each time, and turning fully-specified issues into code one at a time. Each is repetitive and easy to let slip.

### How this project helps

The plugin packages each of these chores as a Claude Code or Cowork skill or command, so the plugin does the routine part and leaves the judgement to you. The coding standard is applied automatically to any code task and can be scaffolded into a project as files; `/init` and `/doctor` set up and reconcile a project against the Kntnt baseline; `/release`, `/push` and `/commit` drive the release cycle; and `/orchestrate` runs an away-from-keyboard build from a project's `ready-for-agent` issues. More tools will join them as common developer chores prove worth packaging.

## Requirements

- **Claude Code or Cowork** with support for skills and YAML frontmatter.
- **[uv](https://docs.astral.sh/uv/)** – runs the bundled Python scripts (`scripts/scaffold.py`, `scripts/init.py`, `scripts/doctor.py`, `scripts/audit.py`, `scripts/help.py`, `scripts/orchestrate.py`, `scripts/release.py`); it provisions Python 3.12+ from each script's PEP 723 metadata, and all of them use the standard library only. The test suite runs via `uv run --with pytest pytest`.
- **git**, and for `/release`'s platform publishing and `/init`'s repo creation, the relevant forge CLI – **`gh`** for GitHub today. `/init` also uses **`curl`** to fetch licence texts by SPDX id.
- The `coder` skill applies the standard from context with no external dependencies and writes no files into the project. `/coding-standard` needs file-system access to the project directory; without it (chat-only, no working directory) there is nothing to materialise, and `coder` still applies the standard from context.

## Installation

The plugin ships as a Claude Code marketplace. In Claude Code or Cowork, run:

```
/plugin marketplace add Kntnt/kntnt-code-skills
/plugin install kntnt-code-skills@kntnt-code-skills
```

The first line registers the marketplace from the GitHub repo (the bare `owner/repo` form is interpreted as a GitHub source); the second installs the plugin. Run `/reload-plugins` (or restart the session) if the skills do not appear immediately.

## Usage

Most usage is just invoking the skills. This section describes what each one does and how to reach further.

### What you get

The plugin exposes two coding-standard skills, two project-lifecycle skills, three release-workflow skills, an orchestration skill and one command:

- **`coder`** – applies the coding standard. It auto-triggers on code-related prompts (in any language) and loads as a lazy bootstrap: at trigger it reads only the standard's router, then pulls in each topic module the moment the working context proves a language or framework axis applies – never the whole standard up front – and keeps pulling more as new axes surface through the session. When a project has already scaffolded the standard into `agents.d/coding-standard/` (via `/coding-standard`), it loads nothing from the plugin at all and defers to the project's own on-demand `AGENTS.md` References – the deliberate snapshot – which the harness already follows on its own. It writes code to those rules and is read-only on the project: it never writes the standard into the project as files.
- **`/coding-standard`** – materialises the standard into a project as files under `agents.d/coding-standard/` and keeps them in sync. Explicitly invoked only: it creates the files on a fresh project, reports how they have drifted on an already-scaffolded one and reconciles them on `--update` (see *The coding standard* below).
- **`/init`** – bootstraps a new project to the Kntnt baseline in one pass: `git init`, the `AGENTS.md`/`CLAUDE.md` skeleton, the coding standard scaffolded into `agents.d/coding-standard/`, a licence fetched by SPDX id, the README/CHANGELOG/CONTRIBUTING (and NOTICE under Apache) from generic templates, and a stack-aware `.gitignore` – then, optionally, the first commit and the GitHub repository. Explicitly invoked only.
- **`/doctor`** – init's idempotent reconciler: it re-checks an existing project against that same baseline and proposes the fixes. Cheap deterministic checks (git state, `.gitignore` coverage, the coding standard's home and sync, the licence/NOTICE pairing) run in `scripts/doctor.py`; a read-only Workflow checks whether `AGENTS.md`, the `agents.d/` files and the README still match the real code. It applies only the fixes you pick (`--yes` applies all) and never commits.
- **`/release`** – the full release workflow on whatever project you invoke it in: reconcile the changelog with the real changes since the last release, bump the version per Semantic Versioning across every place it lives, integrate a feature branch into the main branch, commit, tag `vX.Y.Z`, push and publish the platform release. Every irreversible step waits behind a single confirmation.
- **`/push`** – the routine companion: reconcile the changelog, commit and push the current branch – no bump, tag or release. Run it often so the changelog never falls behind.
- **`/commit`** – `/push` without the push: reconcile the changelog, then commit the working tree on the current branch and stop, leaving the result on your machine. Everything `/push` does locally, for when you want work saved but not yet shared.
- **`/orchestrate`** – an away-from-keyboard build that turns a project's open issues into finished code: it plans from the issues' dependency graph, dispatches one implementer sub-agent per issue (test-first), runs fresh independent sub-agents that adversarially verify what the gates cannot, integrates in dependency order and ends with one consolidated report. It stops short of releasing.
- **`/help`** – a typed-only command (`/kntnt-code-skills:help [skill-name]`): the plugin overview, or one skill's full manual page. `scripts/help.py` echoes it verbatim from the plugin's own `.claude-plugin/plugin.json` and `docs/man/*.md`, so the help text can never drift from the manual pages themselves; `--help`/`-h`/`help` on any skill reaches the same page.

The full option reference for every skill lives in its manual page — [`coder`](docs/man/coder.md), [`coding-standard`](docs/man/coding-standard.md), [`init`](docs/man/init.md), [`doctor`](docs/man/doctor.md), [`release`](docs/man/release.md), [`push`](docs/man/push.md), [`commit`](docs/man/commit.md), and [`orchestrate`](docs/man/orchestrate.md) — also reachable as `/kntnt-code-skills:help <skill>` or `/<skill> --help`.

### The coding standard (`coder` and `/coding-standard`)

The `coder` skill is the entry point for code work. It triggers on any request to write, implement, refactor, fix, review or design code – in any language – and loads the rules lazily: a minimal bootstrap that pulls in each module only as the context reveals it needs it, then writes to them. Nothing to invoke explicitly, nothing to configure. Its trigger boundary is broad on purpose: it fires on any code-shaped task and on anything that mentions a covered language, framework or construct, in any language (the description's examples are English, but the equivalent request in any language triggers it equally). It only reads the standard and applies it – it never writes the standard's files into a project.

It covers:

| File | Loaded when |
|---|---|
| `general.md` | Always – the universal rules every other module presupposes (priority order, language, identifiers, comment philosophy, prefix conventions). |
| `php.md` | When PHP is present. |
| `wordpress.md` | When the project is a WordPress plugin or theme (always together with `php.md`; overrides parts of it). |
| `wordpress-block.md` | When the project includes Gutenberg blocks (always together with `wordpress.md` and `typescript.md`; overrides parts of `typescript.md`). |
| `typescript.md` | When TypeScript is present. |
| `javascript-vanilla.md` | When the project has plain browser JavaScript without a build step. |
| `python.md` | When Python is present. |
| `bash.md` | When Bash is present. |

A project can sit on several axes at once – a WordPress block plugin is PHP + WordPress + TypeScript + Gutenberg – and the skill pulls each module in as its axis surfaces rather than all at once: PHP code that turns out to be WordPress draws in the WordPress module then; a block draws in the Gutenberg and TypeScript modules when the block's UI appears. How the precedence and override relationships work, and how to extend the standard with a new language or framework, is in *How the coding standard is organised* below.

**Materialising into a project (`/coding-standard`).** `coder` itself writes no files into a project. To put the standard into a project as files, invoke the `/coding-standard` skill explicitly. It writes the relevant rules into `agents.d/coding-standard/<module>.md` (one on-demand file per module, with prerequisites pulled in automatically), wires a backticked `## References` pointer to each into `AGENTS.md` and bridges `CLAUDE.md` to it via `@AGENTS.md`. The standard is then loaded on demand – an agent reads only the modules a task needs, the moment it sets out to write or change code – rather than paid for on every session.

The plugin **owns** these scaffolded files: they are canonical and verbatim, regenerated from the standard's source whenever you update – not a starting point to hand-edit. A project's own deviations from the standard belong in `AGENTS.md` prose, not in edits to a module file. So there is no private bookkeeping file and no "locally edited" state. Run `/coding-standard` again later and it does not blindly overwrite: on an already-scaffolded project it **investigates** instead, printing a read-only drift report – which modules differ from a fresh regeneration, and which languages have been added to or dropped from the project since. Run `/coding-standard --update` to apply: it reconciles every difference to the canonical content, adds new modules, removes dropped ones and prunes their References. The presence of the module files is itself the marker of a scaffolded project. To run the engine by hand, see *Advanced usage*.

### How the coding standard is organised

The coding rules live in topic modules under `lib/coding-standard/`, one file per language or framework, beside a shared `_index.md` that lists the modules, the detection signals for profiling a project and the canonical order with its override relationships. Both skills load `_index.md` to profile: `coder` to know which modules to apply, `coding-standard` to know which to write. The modules load in a canonical order (later wins on points where they differ), and override relationships are stated explicitly inside each module – WordPress overrides parts of PHP, the Gutenberg-block module overrides parts of TypeScript. The modules are self-contained, so each reads correctly whether `coder` loads it alone or `coding-standard` writes it to its own `agents.d/coding-standard/<module>.md` file. The prerequisite wiring an override module needs (read X first) is generated by `scripts/scaffold.py`, never written into the module prose. All files are written in English, per the standard's own language rule.

**Updating the standard** means editing one or more module files in `lib/coding-standard/`. Projects that have already scaffolded their own `agents.d/coding-standard/` files keep that snapshot until they explicitly re-run `/coding-standard` with an update – intentional, so a change to the standard never silently changes a project's behaviour.

### Releasing (`/release`, `/push` and `/commit`)

`/release` and `/push` automate the "bump, commit, tag, push, release" cycle for any project – not only this one. `/release` reconciles `CHANGELOG.md` against the real changes since the last release (commit messages first, diffs only as a fallback), bumps the version per Semantic Versioning across every place it lives, integrates a feature branch into the main branch by rebase and fast-forward, commits, tags `vX.Y.Z`, pushes and publishes the platform release with notes from the changelog – plus the built user archive when the project ships one. Every irreversible step waits behind a single confirmation. `/push` is the routine companion: it reconciles the changelog, commits and pushes the current branch, without bumping, tagging or releasing. `/commit` is `/push` without the push – it reconciles the changelog and commits, leaving the result on your machine for when you want work saved but not yet shared. The three share one commit spine (`lib/changelog.md` to reconcile, `lib/commit.md` to stage and commit); `/push` adds the push and `/release` wraps the bump, tag and platform release around it.

Release notes for each version live in [`CHANGELOG.md`](CHANGELOG.md). The classification policy that decides which release class a change lands in is under *Changelog* below.

**Platform support.** Today `/release` publishes to **GitHub** via the `gh` CLI. Further forges are planned, detected by the remote's **host** rather than a fixed domain – so self-hosted and EU-hosted instances are first-class, not afterthoughts:

- **GitLab** – gitlab.com, self-managed, GitLab by Stackhero and EU-hosted instances – via `glab`.
- **Gitea** and **Forgejo** – including **Codeberg** (EU-hosted Forgejo) – via `tea`.

On a remote whose forge is not yet supported, `/release` performs every git step (bump, commit, tag, push) and skips only the platform release, telling you so.

### Orchestrating issues (`/orchestrate`)

`/orchestrate` runs an away-from-keyboard build that turns a project's **`ready-for-agent`** issues into implemented, independently verified, integrated code. It is the last stage of the issue pipeline: once `/grill-with-docs`, `/to-issues` and triage have produced fully-specified issues – each with an agent brief, acceptance criteria and a `Blocked by` graph – invoke it once and walk away. A deterministic helper (`scripts/orchestrate.py`) reads the issues and computes the dependency graph and the concurrency **waves**; then a fleet of sub-agents runs three stages per issue – **implement** (one sub-agent, test-first red/green/refactor, demonstrating the failing test before the code), **verify** (fresh, independent sub-agents that adversarially review only what the gates cannot – correctness against intent, test quality, security and edge cases) and **integrate** (merge in dependency order, rebasing dependents). The orchestrator owns the quality bar and the decisions but never writes code or reads diffs itself; it reads the sub-agents' verdicts and ends with one consolidated report of what shipped and what still needs a human.

The control flow runs through the **Workflow tool** (engine: `skills/orchestrate/orchestrate.workflow.js`) where available – so the wave order, the capped fix↔verify loop, and worktree isolation are deterministic code rather than a long prose procedure an LLM re-interprets – and falls back to the Agent tool, optionally driven by `/goal`, where it is not. Every sub-agent runs **inside the interactive session** (counting against your subscription, never the headless `claude -p` credit pool). A single `--level` ambition dial (`XS`–`XL`, default `M`) sets both how hard every sub-agent thinks — model and reasoning effort derived per role, the strongest tier on the adversarial verifiers and, as the level climbs, on the implementers too — and how much rigor each issue gets; the implementer's *mode* slides with it, from executing a pre-authored recipe at the low end to reasoning autonomously from goals at the high end. It **excludes `ready-for-human`** issues, scales verification depth to each issue's level and risk, and caps the fix↔verify loop so a stubborn issue is parked in the report rather than burning tokens. By default it opens a pull request per issue and leaves the merge to you; `--merge` integrates automatically where the project authorises it. It stops short of releasing – when the merged work is ready to ship, that is `/release`. See [`skills/orchestrate/SKILL.md`](skills/orchestrate/SKILL.md) for the full flow, the cost model and the arguments.

**Two modi operandi: merge or PR.** `/orchestrate` runs one of two ways, and the choice is a standing policy, not a per-call guess. `orchestrate: merge-policy: merge` suits the **solo-maintainer-on-`main`** workflow: every finished issue lands straight on the default branch and the run's own ephemeral feature branches self-prune, so `--yes` alone is a genuine walk-away. The **PR default** suits a **multiple-users** repo: nothing lands without a teammate's own review and merge, so a run against a shared `main` never surprises anyone mid-review. The policy is declared once, not asked per run – an `orchestrate: merge-policy: merge|pr` marker in the project's own `AGENTS.md`/`CLAUDE.md` (a repo-local override), with your global `~/.claude/CLAUDE.md` marker as the once-per-maintainer fallback a repo-local marker overrides; no marker at all means the conservative PR default. `--pr` and `--merge` are the **per-run exceptions**: force one run's mode against the standing policy without touching it – a one-off PR for review on a repo whose policy is merge, or a one-off walk-away merge on a repo whose policy is PR. Supplying both in one run is an error, and merge authority is **never inferred** – only the explicit flag or the declared policy grants it.

**Quick orchestrating, and the retroactive review idiom.** For a large, homogeneous, low-risk batch – a bulk rename, a batch of docstrings, a mechanical migration – the fast idiom is:

```
/orchestrate --level=XL --max-lenses=0 --merge
```

the strongest implementer reasoning autonomously, no per-issue independent verifier lens (test-first, red-before-green, and the mandatory integration review still hold), landing straight on the default branch. It is not a substitute for judgment on a small or risky task – two dependent trivial functions reach for a lighter tool (`tdd`/`coder`, or plain `--level=XS`), not a verification-off orchestrate run. To recoup some of what the skipped lens would have caught, run `/code-review <base>` afterwards against the commit the batch started from: it reviews the merged changes since that point along both Standards and each issue's own Spec, exactly the per-issue-contract dimension the skipped lens would have covered.

### Advanced usage

Most usage is just invoking the skills. Two things are available for going further, short of contributing to the plugin itself.

**Running the engine directly.** `/coding-standard` calls `scripts/scaffold.py`, but it can also be run by hand. (For the skill itself, see its manual page: [`coding-standard`](docs/man/coding-standard.md).) The script is a `uv`-run Python script (it provisions Python from its PEP 723 metadata; standard-library only):

```bash
uv run scripts/scaffold.py \
    --project-dir /path/to/project \
    --modules-dir /path/to/kntnt-code-skills/lib/coding-standard \
    --include     php,wordpress,typescript,wordpress-block \
    [--update] [--dry-run] [--force]
```

Pass the modules that match the project's profile; `general` and any prerequisites are always included automatically. The script picks its mode from the project's state: when `agents.d/coding-standard/` holds no module file it **creates** the files (one `agents.d/coding-standard/<module>.md` per module, the `AGENTS.md` References and the `CLAUDE.md` bridge); when it is already scaffolded and no `--update` is given it **investigates** and prints a read-only drift report (each module `up to date` or `differs (would be updated)`, plus modules that would be added or removed); with `--update` it **reconciles** the files to the given `--include`, rewriting every module whose content differs, adding new modules and removing dropped ones (and pruning their References). `--dry-run` previews any path; `--force` only overrides the project-root sanity check. Exit codes: `0` success; `1` bad arguments, missing module source or failed sanity check. Run `uv run scripts/scaffold.py --help` for the full set of options.

**Release-skill arguments.** `/release`, `/push` and `/commit` take optional arguments; the full reference is each skill's own manual page — [`release`](docs/man/release.md), [`push`](docs/man/push.md), [`commit`](docs/man/commit.md) — also reachable as `/release --help`, `/push --help`, `/commit --help`, or `/kntnt-code-skills:help <skill>`.

## Questions, bugs, and feature requests

Have a usage question or something to discuss? Please use [Discussions](https://github.com/Kntnt/kntnt-code-skills/discussions).

Found a bug or want to request a feature? Please [open an issue](https://github.com/Kntnt/kntnt-code-skills/issues). Search the existing issues first to avoid duplicates.

## Development

For local development, load the repo directly without installing:

```bash
claude --plugin-dir /path/to/kntnt-code-skills
```

The coding standard this project follows is materialised under `agents.d/coding-standard/` — read `general.md` plus the module(s) for the language or framework you touch.

Before committing, run the project's gate — these five commands, and every one must pass:

```sh
uvx ruff check .
uvx ruff format --check .
uv run --with mypy --with pytest mypy scripts tests
uv run --with pytest pytest -q
uv run scripts/audit.py
```

`ruff check` lints and `ruff format --check` enforces formatting across the repo; `mypy` type-checks `scripts` and `tests`; `pytest` runs the test suites for the helper scripts; and `audit.py` runs the scriptable checks (plugin.json shape and CHANGELOG version match, module ↔ `CANONICAL_ORDER` symmetry). There is no `pyproject.toml`, so the tools run through `uvx` / `uv run`. Install the pre-commit hook with `uv tool install pre-commit && pre-commit install`; from then on the audit fires before every commit and CI re-runs the same five on every push and PR.

### Repository layout

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
│   │   └── SKILL.md
│   ├── coding-standard/
│   │   └── SKILL.md
│   ├── init/
│   │   └── SKILL.md
│   ├── doctor/
│   │   ├── SKILL.md
│   │   └── doctor.workflow.js
│   ├── orchestrate/
│   │   ├── SKILL.md
│   │   └── orchestrate.workflow.js
│   ├── commit/
│   │   └── SKILL.md
│   ├── push/
│   │   └── SKILL.md
│   └── release/
│       └── SKILL.md
├── lib/
│   ├── coding-standard/
│   │   ├── _index.md
│   │   ├── general.md
│   │   ├── php.md
│   │   ├── wordpress.md
│   │   ├── wordpress-block.md
│   │   ├── typescript.md
│   │   ├── javascript-vanilla.md
│   │   ├── python.md
│   │   └── bash.md
│   ├── gitignore/
│   │   ├── base.txt
│   │   ├── php.txt
│   │   ├── typescript.txt
│   │   ├── python.txt
│   │   └── wordpress-block.txt
│   ├── templates/
│   │   ├── README.md
│   │   ├── CHANGELOG.md
│   │   ├── CONTRIBUTING.md
│   │   └── NOTICE
│   └── changelog.md
├── scripts/
│   ├── audit.py
│   ├── doctor.py
│   ├── help.py
│   ├── init.py
│   ├── orchestrate.py
│   ├── release.py
│   └── scaffold.py
├── tests/
│   ├── test_doctor.py
│   ├── test_init.py
│   ├── test_orchestrate.py
│   └── test_scaffold.py
├── .pre-commit-config.yaml
├── .gitignore
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
├── NOTICE
└── README.md
```

`commands/` holds the typed-only `/help` command. `skills/` holds the eight skills: `coder` (applies the coding standard), `coding-standard` (materialises it into a project), `init` (bootstraps a new project to the baseline), `doctor` (reconciles an existing one against it), the `commit`/`push`/`release` workflow skills and `orchestrate` (the away-from-keyboard issue-to-code build). `lib/` holds text resources that skills include – `coding-standard/` (the standard's topic modules and their shared `_index.md`, loaded by both `coder` and `coding-standard`), `gitignore/` (the `.gitignore` baseline and per-module fragments), `templates/` (the generic, tokenised README/CHANGELOG/CONTRIBUTING/NOTICE that `init` renders) and `changelog.md` with `commit.md` (the reconcile and stage-and-commit procedures shared by `commit`, `push` and `release`). `scripts/` holds the standalone `uv`-run tools: the audit, the `/help` renderer, `scaffold.py` (the coding-standard engine behind `/coding-standard`), `init.py` (the deterministic file work behind `/init`), `doctor.py` (the deterministic checks behind `/doctor`), `release.py`'s deterministic CHANGELOG mechanics and `orchestrate.py`'s dependency-graph, red/green and report mechanics for `/orchestrate` (whose Workflow engine, `orchestrate.workflow.js`, lives beside its skill, as `doctor.workflow.js` lives beside `doctor`). `tests/` holds the pytest suites for `scaffold.py`, `init.py`, `doctor.py` and `orchestrate.py`, run by both the audit workflow and the pre-commit hook.

### Authoring rules

These rules govern how to edit the files in this plugin. They exist to prevent a recurring failure mode where well-meaning changes reintroduce architectural drift – duplicated prose between modules, cross-references that bind a module to one specific sibling, rules that contradict each other silently. They apply to anyone (human or AI) modifying anything under `skills/`.

**1. Modules are self-contained.** Each topic module reads correctly whether the router loads it alone or the scaffolder writes it to its own `agents.d/` file. A module describes its own rules; it does not depend on a sibling module being present to make sense.

**2. Cross-references use generic phrasing.** When a module needs to mention another axis, it does so descriptively (*WordPress projects override the PSR-12 surface style*) rather than by naming a file or assuming load order. The architectural map – who overrides what, in what order – lives in `lib/coding-standard/_index.md` and this README, not scattered through the modules.

**3. Override relationships are stated explicitly.** When one module overrides another (WordPress over PHP, WordPress-block over TypeScript), the overriding module says so in its own prose, so a reader who loads it understands the bigger picture.

**4. Universal rules in `general.md`, language rules in their module.** A rule that holds across languages (English identifiers, comment philosophy, priority order) goes in `general.md`. A rule whose realisation depends on the language goes in that language's module.

**5. New module = follow the checklist.** Adding a language or framework means: create the module file in `lib/coding-standard/`, add a row and a detection clause to `lib/coding-standard/_index.md` and add the module to `scripts/scaffold.py`'s `CANONICAL_ORDER` and `MODULE_META` (and `OVERRIDE_HEADER` if it overrides another). The script asserts those maps stay in sync; the audit enforces that the module files and `CANONICAL_ORDER` list the same modules.

**6. Lean prose, imperative with whys.** Prefer one imperative followed by a short explanation of why, rather than ALL-CAPS, MUSTs or stacked redundant clauses. Today's models do better with reasoning than with commands.

**7. No vague descriptions.** Phrases like *clean code* without specifying what is meant invite the model to fill the gap with its own interpretation. Either specify or let a concrete rule carry the definition.

#### Audit checklist before committing changes

Items marked **(auto)** are enforced by `scripts/audit.py`, which runs as a pre-commit hook and as the `audit` GitHub Actions job on every push and PR. Both run it with [uv](https://docs.astral.sh/uv/) (`uv run scripts/audit.py`), which provisions Python from the script's PEP 723 metadata. Items marked **(manual)** require human judgement. Install the pre-commit hook locally with `uv tool install pre-commit && pre-commit install`; from then on the audit fires before every commit and CI re-runs it on the remote.

- **(auto)** `.claude-plugin/plugin.json` parses as JSON, carries the `name`, `version` and `description` fields, and its `version` matches the latest non-`[Unreleased]` heading in `CHANGELOG.md`.
- **(auto)** The topic-module files in `lib/coding-standard/` and `scripts/scaffold.py`'s `CANONICAL_ORDER` list the same modules – no module file without a canonical-order entry, no entry without a file.
- **(manual)** Each module is self-contained – no reference to a sibling module by filename, no assumption that another module is loaded.
- **(manual)** Any override relationship a module participates in is stated in that module's own prose.
- **(manual)** The modules table, the detection clauses and the canonical order in `lib/coding-standard/_index.md` all agree with the set of module files present.
- **(manual)** All prose and identifiers are in English.

## How you can contribute

Contributions are welcome, small or large. Before you start, read [`CONTRIBUTING.md`](CONTRIBUTING.md) — it covers which kinds of change are likely to be merged and how inbound licensing works.

## License

Licensed under the Apache License 2.0. The full licence text is in [`LICENSE`](LICENSE), and the copyright and attribution notice is in [`NOTICE`](NOTICE). Contributions are accepted under the same terms by virtue of Apache 2.0 §5 – see [`CONTRIBUTING.md`](CONTRIBUTING.md) for the contribution-scope guidance. Made by [Kntnt](https://kntnt.com).

## Changelog

Release notes for each version live in [`CHANGELOG.md`](CHANGELOG.md).

The project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) 1.1.0 and [Semantic Versioning](https://semver.org/).

### Versioning

SemVer is adapted here to a domain where a *change* is usually a coding rule rather than executable behaviour; the unit that determines the bump class is the code the standard would prescribe for a given situation.

**Major (X.0.0).** A change that alters what the standard prescribes for a category of prior situations without being a bug fix. Examples: switching the default brace style, changing a default toolchain, dropping `declare(strict_types=1)` or reversing an override relationship between modules. Re-applying the standard to existing code would now yield materially different code.

**Minor (0.X.0).** A new language or framework module, a new skill or command, or an extension of an existing rule that does not change what the standard prescribed for prior situations. Example: adding a `laravel.md` module, or adding a new permitted modern-language feature without forbidding the old one.

**Patch (0.0.X).** Bug fixes, documentation changes, prose clarifications that do not change the rule set and behaviour-neutral refactors – for example correcting a broken example or moving logic between files without changing what it does.

**Borderline cases.** When an existing rule is tightened or loosened, it is a major bump if the prescribed code for a typical situation plausibly changes, otherwise minor. Uncertainty resolves to major – the safer side.

**License change.** The transition to Apache 2.0 is recorded as a *Changed* event in whichever release ships it. It does not itself change what the standard prescribes, so it does not force a major bump.

**Version-bump moment.** A release is one commit that does three things together: (1) bump the `version` field in `.claude-plugin/plugin.json`, (2) move the `[Unreleased]` block in `CHANGELOG.md` to a concrete version heading with an ISO date and (3) set a matching git tag. `scripts/audit.py` verifies (1) and (2) are consistent; the git tag is a manual responsibility at release time. The `/release` skill performs all three steps end to end. The version lives in `plugin.json` alone – the skills carry no version field of their own.
