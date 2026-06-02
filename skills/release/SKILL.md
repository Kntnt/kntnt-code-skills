---
name: release
description: >
  Run the full release workflow on the current project — reconcile the
  changelog from real changes, bump the version per Semantic Versioning
  across every place it lives, commit, tag `vX.Y.Z`, push, and create the
  platform release (GitHub) with notes from the changelog and, when the
  project ships one, the built user archive. Trigger on the explicit
  invocations `/release`, `/kntnt-code-skills:release`, and on a plain
  "release" (or the equivalent request in any language — the examples here
  are English only) when context makes it obvious it means shipping a
  version of the current project. This is an irreversible, outward-facing
  operation: when there is the slightest doubt that a release is intended,
  ask first rather than triggering.
---

# release

Ship a version of the current project end to end: reconcile the changelog,
bump the version everywhere it lives, integrate any feature branch into
the main branch, commit, tag, push, and publish the platform release with
notes and (when applicable) a built archive. The routine companion is the
`push` skill, which keeps the changelog fresh between releases.

Releasing is **irreversible and outward-facing**. Trigger on `/release` or
an obviously-release request in any language; **when in doubt, ask** first.
A single confirmation gate (step 7) stands before anything that leaves the
machine, so even a bare-word trigger only ever reaches a plan and waits.

The plugin root holds the shared pieces this skill uses. This skill lives
at `skills/release/`; the plugin root is two levels up (also available as
`${CLAUDE_PLUGIN_ROOT}`). Reach them there: the shared procedure
`lib/changelog.md`, the baseline `lib/gitignore-base.txt`, and the helper
`scripts/release.py` (run with `uv run`).

## Arguments

- `minor` / `major` / `X.Y.Z` — force the bump level or an exact version,
  overriding the changelog-derived proposal.
- `--no-build` — skip rebuilding the archive (use when it was just built).
- `--yes` — skip the confirmation gate (never the first-run record
  confirmation).

## Project record (first-run setup)

Two facts vary per project and cannot be guessed safely: **where the
version number lives** (usually several conventional places at once) and
**whether the project ships a user-facing archive** (and how it is built).
Remember them rather than re-deriving them each time — and prefer a home
that *enforces* version sync over one that merely notes it.

**Where the record lives, in order of preference:**

1. **A verification script that always runs before commit (or at least
   before push)** — an `audit.py`-like check, any language or name; detect
   it via `.pre-commit-config.yaml`, git hooks, `package.json` scripts, a
   `Makefile`, or CI. When one exists, the version locations belong there as
   a consistency check: read them from it, and if it does not yet enforce
   them, offer to add the check. This is the strongest option — it prevents
   drift instead of merely recording it. (This plugin's `audit.py` already
   does exactly this for its three version locations, so no separate record
   is needed here.)
2. **An existing `CLAUDE.md`** — record the facts in a `## Release
   configuration` block (plain prose: version locations as a list, the
   build command or "none").
3. **An existing `README.md`** — the same block there.
4. **Otherwise** — keep no record and re-detect each run.

**Never create** a `CLAUDE.md` or a verification script that does not exist;
use only what the project already has. (A plugin's bundled `CLAUDE.md` never
reaches its users anyway — skills are the delivery channel — so there is no
point creating one.) The archive build, when present, is recorded alongside
in options 2–3, or simply re-detected each run otherwise.

**First run:** detect the version locations — stack-aware, at the
conventional places, expecting several: a WordPress plugin's `Version:`
header plus `readme.txt`'s `Stable tag:`; `package.json`; `composer.json`;
`pyproject.toml`; a manifest's `version`; a skill's frontmatter `version:`;
`CHANGELOG.md`'s latest heading; etc. — and whether a build produces an
end-user zip. Confirm everything before recording it; this confirmation is
**never** skipped, even with `--yes` (a wrong version location is the
costliest error). Whenever a new location surfaces later, update the chosen
home automatically.

## Flow

### 1. Confirm intent if ambiguous

If the trigger was a bare word and it is not obvious a full release is
meant, confirm first. Otherwise proceed.

### 2. Establish the record

Determine the version locations and archive build per *Project record*
above — read them from a verification script if one enforces them, else
from an existing `CLAUDE.md`/`README.md`, else detect and confirm them.
Persist per that precedence (or rely on the script); never create a file
solely for this.

### 3. Reconcile the changelog

Follow `lib/changelog.md` to bring `## [Unreleased]` in line with the real
changes since the last release. Reconciliation writes the accurate
`[Unreleased]`; the gate (step 7) shows the diff. If `[Unreleased]` is
genuinely empty afterwards, there is nothing to release — stop.

### 4. Decide the version and pre-check

Propose the bump from the reconciled sections per SemVer: `Removed` or a
breaking change → major; else `Added` → minor; else → patch. **Below 1.0.0,
a breaking change bumps minor, not major.** An explicit argument
(`/release minor`, `/release 1.4.0`) always wins.

With the target version known, pre-check that it is not already released:

```bash
git tag -l "vX.Y.Z"; git ls-remote --tags origin "vX.Y.Z"; gh release view "vX.Y.Z"
```

If the tag or release already exists, this is a resume, not a fresh
release — see *Resuming* below.

### 5. Integrate a feature branch (only if not on the main branch)

Determine the main branch (`git symbolic-ref refs/remotes/origin/HEAD`,
falling back to `main`/`master`). If a different branch is checked out,
integrate it by **rebasing onto an up-to-date main branch and
fast-forwarding** it, so the branch's commits land linearly and any pending
work becomes part of the release commit. On a rebase conflict that cannot
be resolved automatically, **stop and hand it back** — never substitute a
merge commit. The release commit and tag are always made on the main
branch's HEAD.

### 6. Prepare the rest of the plan (compute, do not yet apply)

- **Version edits**: from the record, the surgical edit for each location —
  change only the canonical version occurrence in each file (never a blind
  find-and-replace, which would corrupt old versions inside `CHANGELOG.md`).
- **Changelog promotion** (preview): the date comes from the system, so let
  the script supply it.

  ```bash
  uv run "${CLAUDE_PLUGIN_ROOT}/scripts/release.py" promote \
      --changelog CHANGELOG.md --version X.Y.Z \
      --repo-url "$(git remote get-url origin)" --dry-run
  ```

  Its stdout is the release-note body; it does not write under `--dry-run`.
- **Release notes**: an optional short framing line that may go at the top
  (unlike the title, the body may carry a brief explanation), then the body
  above, then a final line: `**Full changelog:** <base>/blob/vX.Y.Z/CHANGELOG.md`.
- **Archive** (if the record has a build command): plan to build unless
  `--no-build` is given, then ensure the artifact is named exactly
  `<repo>.zip` (rename if the build emits another name — this keeps a README
  link to the latest release's archive stable).
- **`.gitignore`**: if the project has none, plan to add one (baseline from
  `lib/gitignore-base.txt` + stack-specific entries) — `git add -A` in
  step 8 stages everything. Never touch an existing `.gitignore`.

### 7. Confirmation gate (single)

Show the whole plan and wait for one confirmation: target version and bump,
the changelog diff, every version-file edit, the promotion preview, the
commit message, the tag, the branch integration, the build, and the release
title/body/asset. `--yes` skips this gate (but never the first-run record
confirmation in step 2).

### 8. Execute

Apply everything, stopping and reporting on any failure:

1. Write the `.gitignore` if planned; apply the surgical version edits.
2. Promote the changelog (same command as step 6, without `--dry-run`); it
   rewrites `CHANGELOG.md` and prints the body.
3. `git add -A` and commit: `Release X.Y.Z: <short comma-separated summary>`
   drawn from the changelog highlights. Never `--no-verify` — let any
   configured pre-commit checks run (in this plugin, for example, the commit
   triggers a version-consistency audit that catches a half-applied bump).
4. Build the archive if planned (after the commit, so it reflects the
   released code), and rename it to `<repo>.zip`.
5. Tag: `git tag -a vX.Y.Z -m "vX.Y.Z"` on the main branch's HEAD.
6. Push: the main branch and the tag (`git push origin <main> && git push origin vX.Y.Z`).
7. Publish the platform release.

### 9. Publish the release (platform-aware)

Detect the platform from the remote. **GitHub** (`gh`):

```bash
gh release create "vX.Y.Z" --title "vX.Y.Z" --notes-file <body-file> [<repo>.zip]
```

The title is exactly `vX.Y.Z` — nothing after it. Detect the forge from the
remote's **host**, never a hardcoded `.com`, so self-hosted and EU-hosted
instances count as first-class. GitHub via `gh` is supported today; planned
are GitLab via `glab` (gitlab.com, self-managed, GitLab by Stackhero,
EU-hosted) and the Gitea/Forgejo family via `tea` (including Codeberg, the
EU-hosted Forgejo). On a forge that is not yet supported, do every git step
but skip the platform release and say so.

## Resuming a partial release

If step 4 finds the tag or release already exists, do only what remains
rather than redoing finished work:

- Tag exists, release missing → recreate the body with
  `uv run "${CLAUDE_PLUGIN_ROOT}/scripts/release.py" extract --changelog CHANGELOG.md --version X.Y.Z`,
  then `gh release create` (build/upload the archive if applicable).
- Local commit/tag made but not pushed → push, then publish.
- Release already exists → report that it is done.

## Files this skill uses

- `lib/changelog.md` — shared changelog-reconciliation procedure (also used
  by `push`).
- `lib/gitignore-base.txt` — universal `.gitignore` baseline.
- `scripts/release.py` — `promote` (CHANGELOG surgery + body) and `extract`.
