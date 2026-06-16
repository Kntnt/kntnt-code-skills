# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) and the versioning policy described in the project README.

## [Unreleased]

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

[Unreleased]: https://github.com/Kntnt/kntnt-code-skills/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/Kntnt/kntnt-code-skills/releases/tag/v0.5.0
[0.4.0]: https://github.com/Kntnt/kntnt-code-skills/releases/tag/v0.4.0
[0.3.0]: https://github.com/Kntnt/kntnt-code-skills/releases/tag/v0.3.0
[0.2.1]: https://github.com/Kntnt/kntnt-code-skills/releases/tag/v0.2.1
[0.2.0]: https://github.com/Kntnt/kntnt-code-skills/releases/tag/v0.2.0
[0.1.1]: https://github.com/Kntnt/kntnt-code-skills/releases/tag/v0.1.1
[0.1.0]: https://github.com/Kntnt/kntnt-code-skills/releases/tag/v0.1.0
