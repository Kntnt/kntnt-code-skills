# coding-standard

## NAME

`coding-standard` — materialise Kntnt's coding standard into a project as files

## SYNOPSIS

```
/kntnt-code-skills:coding-standard [--update] [--dry-run]
/kntnt-code-skills:coding-standard (help | --help | -h)
```

## DESCRIPTION

`coding-standard` materialises Kntnt's coding standard into a project as files under `agents.d/coding-standard/` and keeps them in sync. It profiles the project — via the same detection signals `coder` uses — to decide which modules apply, then runs `scripts/scaffold.py` to do the deterministic file work: one on-demand `agents.d/coding-standard/<module>.md` per applicable module (prerequisites pulled in automatically), a backticked `## References` pointer per module in `AGENTS.md`, and `CLAUDE.md` bridged to it via `@AGENTS.md`.

The script picks its mode from the project's own state. On a fresh project (no scaffolded module files yet) it **creates** them. On an already-scaffolded project, a bare invocation **investigates**: it prints a read-only drift report — each module `up to date` or `differs (would be updated)`, plus modules that would be added or removed — and changes nothing. `--update` **reconciles**: it rewrites every module whose content differs from the canonical source, adds new modules, and removes dropped ones, pruning their References. The plugin owns these files — they are canonical and verbatim, never a starting point to hand-edit — so an update reconciles every difference; there is no local-edit protection.

It is explicit-only: never run it because a code task happened to touch a project — only when asked to scaffold, set up, or update the coding standard. When the intent is unclear, ask first.

## OPTIONS

| Option | Description |
|---|---|
| `--update` | Reconcile the project's scaffolded files to the freshly profiled module set: rewrite every module that differs from the canonical source, add new ones, remove dropped ones. Without it, an already-scaffolded project is only investigated, never changed. |
| `--dry-run` | Preview the create/investigate/update path without writing anything. |
| `help`, `--help`, `-h` | Print this manual page and stop. |

## EXAMPLES

Scaffold the standard into a fresh project, or investigate an already-scaffolded one:

```
/kntnt-code-skills:coding-standard
```

Reconcile an already-scaffolded project to the current standard:

```
/kntnt-code-skills:coding-standard --update
```

Preview what an update would change, without writing anything:

```
/kntnt-code-skills:coding-standard --update --dry-run
```

## FILES

| File | Purpose |
|---|---|
| `agents.d/coding-standard/<module>.md` | Written by this skill — one per applicable module, canonical and verbatim. |
| `AGENTS.md` | A `## References` pointer per module is ensured here. |
| `CLAUDE.md` | Bridged to `AGENTS.md` via `@AGENTS.md`. |
| `lib/coding-standard/_index.md`, `lib/coding-standard/<module>.md` | The plugin's own source modules this skill regenerates from. |
| `scripts/scaffold.py` | The deterministic engine behind this skill; also runnable by hand — see the README's *Advanced usage*. |
