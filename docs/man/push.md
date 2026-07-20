# push

## NAME

`push` — reconcile the changelog, commit, and push the current branch

## SYNOPSIS

```
/kntnt-code-skills:push ["message"] [--yes]
/kntnt-code-skills:push (help | --help | -h)
```

## DESCRIPTION

`push` saves the current project's work and shares it: it is the `commit` skill plus a push — everything `commit` does locally (reconcile `CHANGELOG.md`'s `## [Unreleased]` section, then stage and commit the working tree), followed by `git push` on the current branch. It is the routine companion to the `release` skill: run it often so the changelog never falls behind. It deliberately stops short of releasing — no version bump, tag, platform release, or branch integration.

Before committing, the skill shows the changelog diff, the commit message, and — if the project has no `.gitignore` — a proposed one, then waits for one confirmation. A clean working tree does not by itself mean there is nothing to do — there may still be unpushed commits to send.

## OPTIONS

| Option | Description |
|---|---|
| `"message"` | Use this exact commit message instead of an auto-drafted one. |
| `--yes` | Skip the confirmation gate. |
| `help`, `--help`, `-h` | Print this manual page and stop. |

## EXAMPLES

Reconcile, commit, and push, confirming first:

```
/kntnt-code-skills:push
```

Push unattended:

```
/kntnt-code-skills:push --yes
```

## FILES

| File | Purpose |
|---|---|
| `lib/changelog.md` | The shared changelog-reconciliation procedure (also used by `commit` and `release`). |
| `lib/commit.md` | The shared stage-and-commit mechanic (also used by `commit` and `release`). |
| `lib/gitignore/base.txt` | The universal `.gitignore` baseline, proposed when the project has none. |
