# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) and the versioning policy described in the project README.

## [Unreleased]

## [0.2.1] — 2026-05-29

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

## [0.2.0] — 2026-05-29

### Changed

- Converted the repo into an installable Claude Code plugin and renamed it to `kntnt-code-skills`. The manifest moved to `.claude-plugin/plugin.json`, a single-plugin catalog was added at `.claude-plugin/marketplace.json`, and all skill files were reorganized under `skills/coder/`. The plugin is now installable with the two-step marketplace flow (`/plugin marketplace add Kntnt/kntnt-code-skills` then `/plugin install kntnt-code-skills@kntnt-code-skills`); verified with `claude plugin validate .`.
- `README.md` install instructions and component table updated to the new layout, plus a `--plugin-dir` local-development path.

## [0.1.1] — 2026-05-28

### Changed

- Documentation fixes in `SKILL.md`. *The flow, step 3* dropped its inline canonical-order list (which had gone stale, omitting `python` and `bash`) and now points to step 4 and `bin/scaffold`'s `CANONICAL_ORDER` as the single source of truth. *Adding a new module, step 4* corrected the rule: a new module must always be added to the canonical order, because `bin/scaffold` validates every `--include` against that list and rejects unknown modules; a module's *position* only matters when it has override relationships with an existing module. No behaviour changes.

## [0.1.0] — 2026-05-28

### Added

- **Standalone scripts convention** — when a script is requested with no language given by context, choose by preference order (TypeScript on Bun by default), and package by target directory: command-style in `bin/` (no extension, shebang, executable) versus internal (keep extension, explicit invocation).
- `python.md` (uv + PEP 723, ruff, mypy/pyright) and `bash.md` (GNU Bash 5+, `set -euo pipefail`, shellcheck) modules, wired into the router, the detection step, and the scaffolder.
- `bin/scaffold` — the scaffolder, rewritten from Python into a command-style Bun/TypeScript script that dogfoods the new convention. Behaviour-equivalent to the old `scripts/scaffold.py` and strict-typechecked.

### Changed

- `general.md` — the "latest stable version" rule gained an escape clause for projects and dependencies that require an earlier version; standalone scripts added to the no-prefix-needed list.
- `typescript.md` — documents that Bun strips types at runtime, so type safety needs a separate `tsc --noEmit` pass.

[Unreleased]: https://github.com/Kntnt/kntnt-code-skills/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/Kntnt/kntnt-code-skills/releases/tag/v0.2.1
[0.2.0]: https://github.com/Kntnt/kntnt-code-skills/releases/tag/v0.2.0
[0.1.1]: https://github.com/Kntnt/kntnt-code-skills/releases/tag/v0.1.1
[0.1.0]: https://github.com/Kntnt/kntnt-code-skills/releases/tag/v0.1.0
