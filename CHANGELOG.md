# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) and the versioning policy described in the project README.

## [Unreleased]

## [0.8.1] – 2026-06-20

### Changed

- `README.md` prose was reworked to British English typographic conventions: every em-dash (`—`) became a spaced en-dash (`–`), the serial (Oxford) commas were dropped from lists of three or more items (one deliberately retained where the items' own internal *or* would otherwise read ambiguously), and the two American `-ize` spellings (*organized*, *authorizes*) became British `-ise` (*organised*, *authorises*). Prose wording and meaning are unchanged — only mechanics.

### Fixed

- A stale cross-reference in `README.md` pointed at a section called *How `coder` is organized*; the actual heading is *How the coding standard is organised*. The reference now matches the heading.

## [0.8.0] – 2026-06-20

### Added

- New `/coding-standard` skill — materialises the coding standard into a project as files and keeps them in sync, as a deliberate, explicitly-invoked operation. On a fresh project it creates `agents.d/coding-standard/<module>.md` (one on-demand file per applicable module) plus a private `manifest.json`, wires a `## References` pointer to each into `AGENTS.md`, and bridges `CLAUDE.md` with `@AGENTS.md`. On an already-scaffolded project a bare invocation **investigates** instead of overwriting — it prints a read-only drift report covering which modules the standard has updates for, which files have been edited locally, and which languages have been added to or dropped from the project since — and `--update` reconciles the files to the project's current profile, adding new modules and removing dropped ones (pruning their References too), while leaving locally edited files untouched unless `--force`. Drift is detected from a per-module content hash recorded in the manifest, so the report tells an upstream change apart from a local edit.

### Changed

- The `coder` skill now loads the standard as a **lazy, context-driven bootstrap** instead of profiling the project and reading every matching module up front. A trigger loads only `SKILL.md` plus the standard's router (`lib/coding-standard/_index.md`, kept resident); each topic module is then pulled in only when the working context proves its axis applies, under a standing rule — *before writing code in a language whose module you have not loaded, load it first, if one exists*. So `general.md` loads as soon as code work begins and a language or framework module loads the moment its markers surface, including mid-session as new axes appear; a language with no module (Go, Ruby, plain CSS) falls back to `general.md` plus that language's own recognised standard rather than stalling. When the project has already scaffolded the standard into `agents.d/coding-standard/` (via `/coding-standard`), `coder` loads **nothing at all** from the plugin and defers to the project's own on-demand `AGENTS.md` References, which the harness already follows when a task needs them — that snapshot is authoritative by design until `/coding-standard --update` is run, so deferring is both leaner and more correct than re-reading the plugin's `lib/` copies; the one exception is an axis added to the project since it was scaffolded, where `coder` pulls that single module from `lib/` and hints at `--update`. No rules changed — only when each module is loaded.
- Standalone-script guidance was refactored so it lives where it loads when needed. The packaging mechanics — env-based shebangs per language (`#!/usr/bin/env php` / `bun` / `-S uv run --script`; Bash already carried its own), command-style (`bin/`, no extension, `chmod +x`) versus internal packaging, and inline-pinned single-file dependencies — moved out of `coder`'s bootstrap into the language modules plus a shared *Standalone-script packaging* section in `general.md`, so the rules load whenever the language is in play rather than only when a script's language is unpinned. The opinionated language-selection policy (which language to reach for when none is given) was dropped from the plugin as out of scope for a coding standard, and the separate `skills/coder/standalone-scripts.md` file was removed.
- Markdown sources across the plugin (the `coder` standard modules and its `SKILL.md`, `skills/push/SKILL.md`, `commands/help.md`, `lib/changelog.md`, and `skills/coder/templates/claude-md-template.md`) were reflowed so each paragraph is a single physical line instead of being hard-wrapped at a fixed column width. The prose is byte-for-byte identical once whitespace is normalized — only the intra-paragraph line breaks were removed, and code blocks, tables, blockquotes, and YAML frontmatter were left untouched — so the files render cleanly in viewers that show hard breaks and future edits produce one-line-per-paragraph diffs.
- The coding standard is now split across two skills. `coder` **applies** it while writing, refactoring, or reviewing code and never writes any files into the project; the new `/coding-standard` skill **materialises and updates** it. `coder`'s former behaviour of offering to scaffold the standard mid-task is gone — putting the standard into a project is now always an explicit `/coding-standard` invocation. The standard is still written as on-demand, per-axis files so an agent reads only the modules a task needs the moment it sets out to write or change code, with override modules (WordPress over PHP, Gutenberg blocks over TypeScript) carrying a generated prerequisite-and-precedence header.
- The standard's source modules moved from `skills/coder/` to `lib/coding-standard/`, beside a new shared `_index.md` (module table, detection signals, canonical order and override relationships) that both skills load to profile a project. The scaffolding engine moved from `skills/coder/bin/scaffold` to `scripts/scaffold.py` and gained a `tests/test_scaffold.py` suite.
- Scaffolded files now live together in `agents.d/coding-standard/` — one `<module>.md` per module, the `coding-` filename prefix dropped because the directory is the namespace — instead of flat `agents.d/coding-<module>.md` files, isolating the plugin's footprint from other contributors to `agents.d/`. `AGENTS.md` References are now pure pointers; the prerequisite and precedence wiring an override module needs lives only in that module's generated header.
- The `coder` standard modules were tightened for the on-demand model — roughly 15% fewer words overall, and about 25% in `general.md` — by dropping definitions every coding agent already knows (SOLID, Red/Green/Refactor) and examples that merely re-illustrate an unambiguous rule, while preserving every normative rule and all code samples that disambiguate one.
- The plugin version now lives in `.claude-plugin/plugin.json` alone; the per-skill `version` frontmatter field (previously carried by `coder`) has been dropped, and `scripts/audit.py` no longer checks it.

### Removed

- `skills/coder/templates/claude-md-template.md` — the scaffolder now generates the `CLAUDE.md` bridge and a minimal `AGENTS.md` inline, so the starter template is no longer used.

### Fixed

- `.claude-plugin/marketplace.json` — the bundled plugin's `source` was the string shorthand `"./"`, which a local `/plugin marketplace add` accepts but Claude Cowork's remote sync rejects: Cowork clones the repository server-side and requires each plugin's `source` to be an object whose `source` field is one of `github`, `url`, or `git-subdir`, so adding the repository as a marketplace failed with `REMOTE_SYNC_FAILED`. The entry now uses the `github` object form (`{ "source": "github", "repo": "Kntnt/kntnt-code-skills" }`), so the Cowork marketplace add syncs successfully while the local `/plugin marketplace add` keeps resolving as before.

## [0.7.0] – 2026-06-18

### Added

- `/orchestrate` plan output (`scripts/orchestrate.py`) — the deterministic plan now records dependency provenance and integration guidance: a `dependency_edges` list giving each derived edge with the keyword it came from, a `soft_notes` list that surfaces non-blocking mentions (`Relates to`, "touches the same files as …") without turning them into edges, and a `merge_required` flag with a human-readable `merge_note`, raised whenever the in-scope graph has any cross-issue edge so a coupled set is integrated in merge mode rather than branching dependents off bare `main`. The fields are additive — the five existing top-level plan keys are unchanged, so the Workflow engine that consumes the plan is unaffected. `skills/orchestrate/SKILL.md` documents the new `merge_required` signal.

### Fixed

- `/orchestrate` engine (`skills/orchestrate/orchestrate.workflow.js`) — the Workflow engine read its run configuration as if `args` were an object, but the harness delivers `args` as a JSON **string**, so every field was `undefined`: the wave loop ran zero iterations and the run returned an empty success in milliseconds with no agents — a silent no-op indistinguishable from a legitimately empty plan. The engine now normalizes `args` once at entry (tolerating both a JSON string and an already-parsed object) and routes every configuration read through the normalized object; a misdelivered or empty plan now emits a prominent warning and a non-success status instead of masquerading as a clean run.
- `/orchestrate` planner (`scripts/orchestrate.py`) — dependencies written as inline prose or a bold label (e.g. `**Depends on:** #44`, `Blocked by: #44, #45`, or a label followed by a bullet list of `#N`) were invisible to the planner, which recognized only a `## Blocked by` heading; a coupled issue set then collapsed into a single wave that built dependents before their prerequisites and raced parallel edits on a shared file. The planner now derives edges from labelled, directional forms (`Blocked by`, `Depends on`, `Depends upon`, `Requires`, `Needs`) anywhere in an issue body or agent brief, producing a correct multi-wave, dependency-ordered plan. Vague, non-directional mentions and self-references are deliberately not treated as edges.

## [0.6.0] – 2026-06-16

### Added

- `coder` standard — a **Defensive coding** rule in `general.md`. A guard is written only where a real, present condition needs it (an untrusted boundary, a documented platform quirk, a contract a caller can plausibly break); defensive code against states the surrounding invariants already rule out — redundant null checks, `try`/`catch` around calls that cannot throw, re-validation of already-validated data, dead `else` branches, fallbacks for a self-constructed dependency — is forbidden, and a warranted guard names the threat it defends against in its `//` topic sentence.
- `.claude/settings.json` — a tracked, curated settings file carrying the recommended `Bash(uv:*)` permission for contributors, while `.gitignore` is narrowed (`.claude/*` plus `!.claude/settings.json`) so that one shared file is versioned and per-user `.claude/` state (`settings.local.json`, and the like) stays ignored.

### Changed

- `coder` standard — the **TDD** rule in `general.md` strengthened to require a *demonstrable* RED step (a test seen failing before the code that satisfies it exists, never inferred after the fact) and to define test-automation scope: automate every test that can meaningfully constrain behaviour at the lowest layer that captures it, escalating to integration or end-to-end only where a unit test cannot, and reserve human verification for the irreducibly subjective.
- `scripts/release.py` — `promote` now writes version headings with a single canonical **en-dash** separator instead of detecting and mirroring the file's existing dash; the heading parser still accepts en-dash, em-dash, or hyphen so existing changelogs keep resolving. `CHANGELOG.md` headings were normalized from em-dash to en-dash to match.

## [0.5.0] – 2026-06-16

### Added

- `/orchestrate` skill (`skills/orchestrate/SKILL.md`) — an away-from-keyboard, multi-agent build that turns a project's **`ready-for-agent`** issues (from the `to-issues` → `triage` pipeline, each with an agent brief and a `Blocked by` graph) into implemented, independently verified, integrated code. A deterministic helper (`scripts/orchestrate.py`, with a pytest suite in `tests/`) computes the dependency graph and concurrency waves, checks red-before-green commit ordering, and folds the sub-agents' verdicts into the final report; a Workflow-tool engine (`skills/orchestrate/orchestrate.workflow.js`) drives the per-issue lifecycle — implement (test-first, demonstrating the red), independently verify (adversarial, only what the gates cannot), integrate in dependency order — with the Agent tool (optionally `/goal`) as the portable fallback. Every sub-agent runs inside the interactive session (subscription pool, never headless `claude -p`), with the strong model and high effort spent on implementers and verifiers rather than routing; it excludes `ready-for-human` issues, scales verification to risk, caps the fix↔verify loop, and stops short of releasing — bump, tag, and platform release stay with `/release`. Auto-discovered by `scripts/help.py`, so `/help` lists it without further wiring.

## [0.4.0] – 2026-06-02

### Added

- `/release` and `/push` slash commands (skills) that automate the "bump, commit, tag, push, release" workflow across any project. `/release` reconciles `CHANGELOG.md` against the real changes since the last release, bumps the version per Semantic Versioning across every place it lives, integrates a feature branch into the main branch by rebase and fast-forward, commits, tags `vX.Y.Z`, pushes, and creates the platform release (GitHub) with notes drawn from the changelog and, when the project ships one, the built user archive. `/push` is the routine companion — it reconciles the changelog, commits, and pushes the current branch, without bumping, tagging, or releasing. Both are deliberately general-purpose (WordPress plugins, Laravel, Bun, React, Python, …) and gate every irreversible step behind a single confirmation, with a "when in doubt, ask" triggering posture.
- `lib/` — shared text resources that skills include: `changelog.md`, the changelog-reconciliation procedure used by both `/release` and `/push`, and `gitignore-base.txt`, a universal `.gitignore` baseline offered on first run when a project has none.
- `scripts/release.py` — a standalone PEP 723 script run via `uv` that performs the deterministic CHANGELOG mechanics: `promote` (promote `[Unreleased]` to a dated version heading, open a fresh `[Unreleased]`, maintain the reference-link block, and emit the release-note body with heading levels shifted up one) and `extract` (re-emit an existing version's body when resuming a partial release).

### Changed

- `README.md` restructured around three audiences (users, then builders, then contributors) and expanded to document the `/release` and `/push` skills, the planned forge support — GitHub today via `gh`; GitLab via `glab` and the Gitea/Forgejo family (including Codeberg) via `tea`, detected by the remote's host rather than a fixed domain — and the new `lib/` and `scripts/release.py`. *Versioning* now names both governing standards (Semantic Versioning and Keep a Changelog 1.1.0).

## [0.3.0] – 2026-05-29

### Added

- `/help` slash command (`/kntnt-code-skills:help [skill-name]`) and its renderer `scripts/help.py` — a manpage-style overview of the plugin's skills, or details for one. The command is disabled for model invocation, so it runs only when typed; `scripts/help.py` renders the whole block from `.claude-plugin/plugin.json` and each `skills/<name>/SKILL.md`, so the help text can never drift from the actual skills. The renderer is a standalone PEP 723 script run via `uv`.

### Changed

- The `coder` skill's frontmatter `description` rewritten to English only and broadened — it now triggers on any code-shaped task in any language or framework, with the listed languages explicitly non-exhaustive. The skill still triggers on prompts in any language; only the examples are now English.
- `bin/scaffold` reverted from a Bun/TypeScript script to a command-style Python script run via `uv` (`#!/usr/bin/env -S uv run --script` shebang, PEP 723 inline metadata, standard-library only). Behaviour-equivalent to the TypeScript version — same flags, exit codes, and `CANONICAL_ORDER`.
- `scripts/audit.py` is now a standalone PEP 723 script run via `uv` rather than a `python3` shebang script: PEP 723 metadata pins `requires-python`, the deprecated `typing.Callable` import moved to `collections.abc`, and the source is ruff-formatted. The pre-commit hook and the `audit` GitHub Actions job invoke it with `uv run`, and its `CANONICAL_ORDER` matcher now tolerates the annotated Python declaration in `bin/scaffold`.
- `README.md` updated throughout to reflect the Python scaffolder, the uv-run helper scripts, and the new `/help` command.

## [0.2.1] – 2026-05-29

### Added

- `LICENSE` (Apache License 2.0) and `NOTICE` — the project's licence text and the copyright / attribution statement that accompanies redistributions.
- `CONTRIBUTING.md` — contribution-scope guidance: which kinds of changes are welcomed, which want an issue first, and which are better kept in a fork.
- `CHANGELOG.md` — this file, reconstructed for the three prior releases from their GitHub release notes.
- `.pre-commit-config.yaml` and `.github/workflows/audit.yml` — the audit runs as a pre-commit hook locally and as a GitHub Actions job on every push and PR.
- `.github/ISSUE_TEMPLATE/bug.md` — a structured bug-report template (which module, which language/framework, input, observed vs expected).
- `scripts/audit.py` — standard-library audit script. Verifies that `plugin.json` is well-formed and its `version` matches the latest changelog heading, that the topic-module files and `bin/scaffold`'s `CANONICAL_ORDER` agree, and that the `coder` skill's frontmatter version tracks `plugin.json`.

### Changed

- License changed from MIT to Apache 2.0. The `license` field in `.claude-plugin/plugin.json` was `MIT` but no licence file ever shipped; the project now declares Apache 2.0 with a full `LICENSE`, a `NOTICE`, and matching `CONTRIBUTING.md` guidance.
- `README.md` refreshed and restructured to mirror the `kntnt-text-skills` layout — added *File structure*, *Versioning*, *Authoring rules* with an audit checklist, *Requirements*, *License*, and *About* sections.
- CI actions bumped to their Node 24 majors — `actions/checkout@v4` → `@v6` and `actions/setup-python@v5` → `@v6` — clearing the Node 20 deprecation warning. Removed a dead `*.skill` stanza from `.gitignore` that documented output of a `package_skill.py` not present in this repo.

## [0.2.0] – 2026-05-29

### Changed

- Converted the repo into an installable Claude Code plugin and renamed it to `kntnt-code-skills`. The manifest moved to `.claude-plugin/plugin.json`, a single-plugin catalog was added at `.claude-plugin/marketplace.json`, and all skill files were reorganized under `skills/coder/`. The plugin is now installable with the two-step marketplace flow (`/plugin marketplace add Kntnt/kntnt-code-skills` then `/plugin install kntnt-code-skills@kntnt-code-skills`); verified with `claude plugin validate .`.
- `README.md` install instructions and component table updated to the new layout, plus a `--plugin-dir` local-development path.

## [0.1.1] – 2026-05-28

### Changed

- Documentation fixes in `SKILL.md`. *The flow, step 3* dropped its inline canonical-order list (which had gone stale, omitting `python` and `bash`) and now points to step 4 and `bin/scaffold`'s `CANONICAL_ORDER` as the single source of truth. *Adding a new module, step 4* corrected the rule: a new module must always be added to the canonical order, because `bin/scaffold` validates every `--include` against that list and rejects unknown modules; a module's *position* only matters when it has override relationships with an existing module. No behaviour changes.

## [0.1.0] – 2026-05-28

### Added

- **Standalone scripts convention** — when a script is requested with no language given by context, choose by preference order (TypeScript on Bun by default), and package by target directory: command-style in `bin/` (no extension, shebang, executable) versus internal (keep extension, explicit invocation).
- `python.md` (uv + PEP 723, ruff, mypy/pyright) and `bash.md` (GNU Bash 5+, `set -euo pipefail`, shellcheck) modules, wired into the router, the detection step, and the scaffolder.
- `bin/scaffold` — the scaffolder, rewritten from Python into a command-style Bun/TypeScript script that dogfoods the new convention. Behaviour-equivalent to the old `scripts/scaffold.py` and strict-typechecked.

### Changed

- `general.md` — the "latest stable version" rule gained an escape clause for projects and dependencies that require an earlier version; standalone scripts added to the no-prefix-needed list.
- `typescript.md` — documents that Bun strips types at runtime, so type safety needs a separate `tsc --noEmit` pass.

[Unreleased]: https://github.com/Kntnt/kntnt-code-skills/compare/v0.8.1...HEAD
[0.8.1]: https://github.com/Kntnt/kntnt-code-skills/releases/tag/v0.8.1
[0.8.0]: https://github.com/Kntnt/kntnt-code-skills/releases/tag/v0.8.0
[0.7.0]: https://github.com/Kntnt/kntnt-code-skills/releases/tag/v0.7.0
[0.6.0]: https://github.com/Kntnt/kntnt-code-skills/releases/tag/v0.6.0
[0.5.0]: https://github.com/Kntnt/kntnt-code-skills/releases/tag/v0.5.0
[0.4.0]: https://github.com/Kntnt/kntnt-code-skills/releases/tag/v0.4.0
[0.3.0]: https://github.com/Kntnt/kntnt-code-skills/releases/tag/v0.3.0
[0.2.1]: https://github.com/Kntnt/kntnt-code-skills/releases/tag/v0.2.1
[0.2.0]: https://github.com/Kntnt/kntnt-code-skills/releases/tag/v0.2.0
[0.1.1]: https://github.com/Kntnt/kntnt-code-skills/releases/tag/v0.1.1
[0.1.0]: https://github.com/Kntnt/kntnt-code-skills/releases/tag/v0.1.0
