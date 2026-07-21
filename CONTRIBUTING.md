# Contributing to kntnt-code-skills

Thanks for considering a contribution. The plugin is open source under the Apache License 2.0, which means anyone is free to fork it and modify it for their own purposes. This document describes the *project norm* — what kinds of contributions are likely to be welcomed into the upstream repository at [Kntnt/kntnt-code-skills](https://github.com/Kntnt/kntnt-code-skills). It is not a legal restriction on what you may do with the code; it is editorial guidance on what is likely to be merged.

## Contribution scope

The plugin embodies a specific coding standard. Decisions about what enters the upstream repository follow that standard. The table below describes how different kinds of contributions are likely to be received.

| Category | Examples | Reception |
|---|---|---|
| Welcomed without question | New language or framework modules under `skills/coder/` that follow the shape of the existing modules and the *Adding a new module* checklist in `SKILL.md`; bug reports; bug fixes against existing rules; corrections to broken examples; typo and grammar fixes in prose; clarifications that do not alter rule semantics. | Open a PR. If the change is small and self-evidently correct, it is usually merged quickly. |
| Accepted but discussed first | Adjustments to existing rules; changes to default behaviour (e.g. the standalone-script language preference order, or an override relationship between modules); tightening or loosening of an existing rule. | Open an issue first to align on intent before writing code. A PR without prior discussion may still land, but expect feedback rounds. |
| Unlikely to be merged but free to fork | Fundamental changes that alter the standard's positions (a different brace style, a different default toolchain, dropping `declare(strict_types=1)`); restructuring the architecture in a way that conflicts with the authoring rules in the README. | The Apache 2.0 licence makes forking explicit and lawful. If you want a different standard, build it in your fork. |

## Inbound licensing

By submitting a contribution, you agree it is licensed under Apache 2.0 by virtue of Apache License 2.0 §5 *Submission of Contributions*, which states that any contribution intentionally submitted for inclusion in the work shall be under the terms of that licence unless you explicitly state otherwise. No separate contributor licence agreement is required.

## Behaviour

Be respectful and constructive in issues, pull requests, and discussions. Assume good faith, keep criticism about the work rather than the person, and help keep this a project people want to contribute to.

## How to contribute

1. **Open an issue first** for anything in the *discussed* row of the table above. For *welcomed* items, you can open a PR directly. Use the issue tracker at <https://github.com/Kntnt/kntnt-code-skills/issues>.
2. **Bug reports** should follow the template under `.github/ISSUE_TEMPLATE/bug.md` — which module, which language/framework, which input, observed versus expected outcome.
3. **Read the authoring rules** in the README (the *Authoring rules* section and the audit checklist beneath it) before editing the standard's files. The rules exist to prevent recurring architectural drift.
4. **When adding a new module**, follow the checklist in the README's *Authoring rules*: create `<topic>.md` in `lib/coding-standard/`, add a row and a detection clause to `lib/coding-standard/_index.md`, and add the module to `scripts/scaffold.py`'s `CANONICAL_ORDER` and `MODULE_META` (and an `OVERRIDE_HEADER` sentence if it overrides another module). The script asserts these maps stay in sync; the audit checks the module files against `CANONICAL_ORDER`.
5. **One concern per PR.** Smaller PRs land faster.
6. **Run the full gate before committing.** The project's gate is these five commands, and every one must pass:

   ```sh
   uvx ruff check .
   uvx ruff format --check .
   uv run --with mypy --with pytest mypy scripts tests
   uv run --with pytest pytest -q
   uv run scripts/audit.py
   ```

   `ruff check` lints and `ruff format --check` enforces formatting across the repo; `mypy` type-checks `scripts` and `tests`; `pytest` runs the test suites for the helper scripts; and `audit.py` runs the scriptable checks (plugin.json shape and CHANGELOG version match, module ↔ `CANONICAL_ORDER` symmetry). There is no `pyproject.toml`, so the tools run through `uvx` / `uv run`. Install the pre-commit hook with `pip install pre-commit && pre-commit install` so all five fire automatically; CI re-runs the same five on every push and PR.

## Style and language conventions

- All identifiers and comments in English (this is itself one of the standard's rules — see `lib/coding-standard/general.md`).
- Module prose is written for a reader who may load the module alone, so cross-references between modules use generic phrasing (e.g. "WordPress projects override the PSR-12 surface style") rather than naming sibling files.
- Each module is self-contained: a one-paragraph "When this applies" intro, then sections for baseline, required modern features, surface style, file layout, and tooling. State any override relationships explicitly inside the module.

## Questions

Open an issue. Discussion happens in the open.
