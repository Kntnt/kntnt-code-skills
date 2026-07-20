# commit

## NAME

`commit` — reconcile the changelog and commit the working tree, without pushing

## SYNOPSIS

```
/kntnt-code-skills:commit ["message"] [--yes]
/kntnt-code-skills:commit (help | --help | -h)
```

## DESCRIPTION

`commit` saves the current project's work locally: it reconciles `CHANGELOG.md`'s `## [Unreleased]` section against the real changes since the last release (commit messages first, diffs only as a fallback), then stages and commits the working tree on the current branch. It is the innermost of the three release-workflow skills — `push` is `commit` followed by a push to origin, and `release` wraps a version bump, tag, and platform release around the same spine.

Unlike `push` and `release`, an empty `[Unreleased]` afterwards is not a stop condition: a pure refactor, a formatting pass, or a test-only change produces no user-facing changelog entry yet is still worth committing. Whether there is anything to commit is decided by the working tree — a clean tree means nothing to do.

Before committing, the skill shows the changelog diff, the commit message, and — if the project has no `.gitignore` — a proposed one, then waits for one confirmation. It never bypasses commit hooks (`--no-verify`).

`commit` never pushes, bumps a version, tags, or releases — see the sibling skills for those.

## OPTIONS

| Option | Description |
|---|---|
| `"message"` | Use this exact commit message instead of an auto-drafted one. |
| `--yes` | Skip the confirmation gate. |
| `help`, `--help`, `-h` | Print this manual page and stop. |

## EXAMPLES

Reconcile the changelog and commit, confirming first:

```
/kntnt-code-skills:commit
```

Commit unattended, with an auto-drafted message:

```
/kntnt-code-skills:commit --yes
```

Commit with an exact message:

```
/kntnt-code-skills:commit "Fix off-by-one in the pagination helper"
```

## FILES

| File | Purpose |
|---|---|
| `lib/changelog.md` | The shared changelog-reconciliation procedure (also used by `push` and `release`). |
| `lib/commit.md` | The shared stage-and-commit mechanic (also used by `push` and `release`). |
| `lib/gitignore/base.txt` | The universal `.gitignore` baseline, proposed when the project has none. |
