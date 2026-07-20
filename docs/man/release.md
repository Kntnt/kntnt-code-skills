# release

## NAME

`release` — ship a version of the current project end to end

## SYNOPSIS

```
/kntnt-code-skills:release [minor | major | X.Y.Z] [--no-build] [--yes]
/kntnt-code-skills:release (help | --help | -h)
```

## DESCRIPTION

`release` runs the full release workflow on the current project: it reconciles `CHANGELOG.md`'s `## [Unreleased]` section against the real changes since the last release, bumps the version per Semantic Versioning across every place it lives, integrates any feature branch into the main branch, commits, tags `vX.Y.Z`, pushes, and publishes the platform release with notes from the changelog and, when the project ships one, the built user archive.

On first run it detects (or asks about) where the version number lives and whether the project ships a build archive, then remembers the answer per the skill's own *Project record*. A single confirmation gate stands before anything irreversible or outward-facing — even a bare-word trigger only ever reaches a plan and waits.

Releasing is irreversible and outward-facing: trigger on an explicit invocation or an unmistakable release request; when in doubt, ask first.

## OPTIONS

| Option | Description |
|---|---|
| `minor`, `major`, `X.Y.Z` | Force the bump level or an exact version, overriding the changelog-derived proposal. |
| `--no-build` | Skip rebuilding the archive (use when it was just built). |
| `--yes` | Suppress all interactive prompts, no exceptions: skips the confirmation gate and, on a first run, proceeds on the best-detected project record instead of confirming it, reporting what it detected. |
| `help`, `--help`, `-h` | Print this manual page and stop. |

## EXAMPLES

Release the changelog-derived proposal, confirming first:

```
/kntnt-code-skills:release
```

Force a major release, unattended:

```
/kntnt-code-skills:release major --yes
```

Release an exact version without rebuilding the archive:

```
/kntnt-code-skills:release 1.4.0 --no-build
```

## FILES

| File | Purpose |
|---|---|
| `lib/changelog.md` | The shared changelog-reconciliation procedure (also used by `commit` and `push`). |
| `lib/commit.md` | The shared stage-and-commit mechanic (also used by `commit` and `push`). |
| `lib/gitignore/base.txt` | The universal `.gitignore` baseline, proposed when the project has none. |
| `scripts/release.py` | `promote` (CHANGELOG surgery + release-note body) and `extract`. |
