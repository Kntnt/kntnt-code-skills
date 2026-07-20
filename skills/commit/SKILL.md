---
name: commit
description: >
  Run the commit workflow on the current project — reconcile the changelog
  from real changes, then stage and commit the working tree on the current
  branch. It does not push, and it does no version bump, tag, platform
  release, or branch integration; pushing to origin is the push skill's job
  and the rest is the release skill's. Trigger on the explicit invocations
  `/commit`, `/kntnt-code-skills:commit`, and on a plain "commit" or "commit
  this / commit my work" with no push intended (or the equivalent request in
  any language — the examples here are English only) when context makes it
  obvious it means saving work on the current project. Route "commit and
  push" and a bare "push" to the push skill instead. When it is unclear
  whether this workflow is meant — for instance a bare `git commit` with no
  changelog work intended — ask first rather than triggering.
---

# commit

Save the current project's work locally: bring the changelog up to date with what has actually changed, then stage and commit — without pushing. This is the innermost of the three release-workflow skills: `push` is `commit` followed by a push to origin, and `release` wraps a version bump, tag and platform release around the same spine. Reach for it whenever you want your work committed but not yet shared.

Because it stops at the commit, `commit` stays on your machine — nothing leaves it. It shares the family's triggering rule: trigger on `/commit` or an obviously-commit request in any language; route "commit and push" and a bare "push" to the `push` skill; **when in doubt, ask** whether the commit workflow is intended before doing anything. If the invocation was a bare "commit" and it might just mean a raw `git commit` with no changelog work, confirm intent first.

The plugin root holds the shared pieces this skill uses. This skill lives at `skills/commit/`; the plugin root is two levels up (also available as `${CLAUDE_PLUGIN_ROOT}`). Reach them there: `lib/changelog.md`, `lib/commit.md`, `lib/gitignore/base.txt`.

## 0. Help gate

If the arguments are `help`, `--help`, or `-h`, run `uv run "${CLAUDE_PLUGIN_ROOT}/scripts/help.py" commit`, emit its output verbatim as Markdown, and stop. Do nothing else — no changelog reconciliation, no git operation.

## Arguments

- `"message"` — use this exact commit message instead of an auto-drafted one.
- `--yes` — skip the confirmation gate.

## Flow

### 1. Reconcile the changelog

Load `lib/changelog.md` from the plugin root and follow it exactly. It reconciles `## [Unreleased]` in `CHANGELOG.md` with the real changes since the last release (commit messages first, diffs only as a fallback), merging without duplicating. Unlike `release`, an empty `[Unreleased]` afterwards is **not** a stop condition here: a pure refactor, a formatting pass or a test-only change produces no user-facing entry yet is still worth committing. Whether there is anything to commit is decided by the working tree (step 2), not by the changelog.

### 2. Prepare the commit (compute, do not yet apply)

Follow `lib/commit.md` steps 1–2 as a dry run: confirm there is something to commit — a clean working tree means nothing to do, so say so and stop — and, if the project has **no** `.gitignore`, prepare one to propose (baseline from `lib/gitignore/base.txt` plus stack-specific entries).

### 3. Confirm (single gate)

Show, and wait for one confirmation:

- the changelog diff just produced,
- the commit message that will be used, and
- the proposed `.gitignore`, if the project lacks one.

`--yes` (or an explicit "no confirmation") skips this gate.

### 4. Commit

Follow `lib/commit.md` step 3: write the proposed `.gitignore` if one was planned, `git add -A`, and commit. The commit message: use the argument verbatim if one was given (`/commit "message"`); otherwise draft a short, concrete subject line from the entries just written to the changelog, or from the diff when the change produced no user-facing entry. Never bypass commit hooks (`--no-verify`); let any pre-commit checks run. This skill stops here — it does not push.

## What this skill does not do

No push, no version bump, no tag, no platform release, no merge/rebase to main. Pushing the commit to origin is the `push` skill; the moment a version should ship, that is the `release` skill.

## Files this skill uses

- `lib/changelog.md` — shared changelog-reconciliation procedure (also used by `push` and `release`).
- `lib/commit.md` — shared stage-and-commit mechanic (also used by `push` and `release`).
- `lib/gitignore/base.txt` — universal `.gitignore` baseline.
