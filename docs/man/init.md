# init

## NAME

`init` — bootstrap a new project to Kntnt's baseline

## SYNOPSIS

```
/kntnt-code-skills:init
/kntnt-code-skills:init (help | --help | -h)
```

## DESCRIPTION

`init` brings a new project up to Kntnt's baseline in one pass: it initialises git, lays the `AGENTS.md`/`CLAUDE.md` skeleton, scaffolds the coding standard into `agents.d/coding-standard/`, fetches a licence by SPDX id, renders the README, CHANGELOG, CONTRIBUTING (and NOTICE under Apache) from generic templates, and writes a stack-aware `.gitignore` — then, optionally, makes the first commit and creates the GitHub repository.

It resolves the project's identity up front (owner, author, project name, year, date), asks which coding-standard modules apply, and asks which licence to use (defaulting to Apache-2.0). It always asks whether to make the first commit and whether to create the GitHub repository — there is no flag to suppress either question.

It is explicit-only, and it writes files, runs `git init`, and can create a GitHub repository: never run it because a task happened to start a new project — run it only when asked to initialise or scaffold one.

## OPTIONS

| Option | Description |
|---|---|
| `help`, `--help`, `-h` | Print this manual page and stop. |

## EXAMPLES

Bootstrap the current (new) project:

```
/kntnt-code-skills:init
```

## FILES

| File | Purpose |
|---|---|
| `scripts/init.py` | The deterministic file work: `.gitignore` compose, template token substitution, licence fetch + post-processing. |
| `lib/templates/` | The generic, tokenised README, CHANGELOG, CONTRIBUTING, and NOTICE this skill renders. |
| `lib/gitignore/` | The `.gitignore` baseline and per-module fragments this skill composes from. |
| `scripts/scaffold.py`, `lib/coding-standard/` | The coding-standard engine and modules used to scaffold `agents.d/coding-standard/`. |
