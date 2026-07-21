---
name: push
description: >
  Run the push workflow on the current project — reconcile the changelog
  from real changes, then commit and push the current branch. It is the
  commit skill plus a push to origin. No version bump, no tag, no platform
  release, and no branch integration; those are the release skill's job.
  Trigger on the explicit invocations `/push`, `/kntnt-code-skills:push`,
  and on a plain "push" or "commit and push" (or the equivalent request in
  any language — the examples here are English only) when context makes it
  obvious it means saving work on the current project. A plain "commit"
  with no push is the commit skill, not this one. When it is unclear
  whether this workflow is meant — for instance a bare `git push` with no
  changelog work intended — ask first rather than triggering.
argument-hint: "[\"message\"] [--yes] [help]"
---

# push

Save the current project's work and share it: bring the changelog up to date with what has actually changed, commit, and push the current branch. It is the `commit` skill plus a push — everything `commit` does locally, then `git push`. This is the routine companion to the `release` skill — run it often so the changelog never falls behind. It deliberately stops short of releasing: no version bump, tag, platform release, or branch integration.

This is an outward-facing operation (it pushes). It is `release`'s sibling and shares the same triggering rule: trigger on `/push` or an obviously-push request in any language; **when in doubt, ask** whether the push workflow is intended before doing anything. If the invocation was a bare "push" and it might just mean a raw `git push` with no changelog work, confirm intent first.

The plugin root holds the shared pieces this skill uses. This skill lives at `skills/push/`; the plugin root is two levels up (also available as `${CLAUDE_PLUGIN_ROOT}`). Reach them there: `lib/changelog.md`, `lib/commit.md`, `lib/gitignore/base.txt`.

## 0. Help gate

If the arguments are `help`, `--help`, or `-h`, run `uv run "${CLAUDE_PLUGIN_ROOT}/scripts/help.py" push`, emit its output verbatim as Markdown, and stop. Do nothing else — no changelog reconciliation, no git operation.

## Arguments

- `"message"` — use this exact commit message instead of an auto-drafted one.
- `--yes` — skip the confirmation gate.

## Flow

### 1. Reconcile the changelog

Load `lib/changelog.md` from the plugin root and follow it exactly. It reconciles `## [Unreleased]` in `CHANGELOG.md` with the real changes since the last release (commit messages first, diffs only as a fallback), merging without duplicating. Unlike `release`, an empty `[Unreleased]` afterwards is **not** a stop condition here: a pure refactor, a formatting pass or a test-only change produces no user-facing entry yet still belongs in a commit and on the remote. Whether there is anything to do is decided by the working tree and any unpushed commits (step 4), not by the changelog.

### 2. Prepare the commit (compute, do not yet apply)

Follow `lib/commit.md` steps 1–2 as a dry run: check whether there is something to commit, and, if the project has **no** `.gitignore`, prepare one to propose (baseline from `lib/gitignore/base.txt` plus stack-specific entries). A clean working tree does not by itself mean there is nothing to do — there may still be unpushed commits to send in step 4.

### 3. Confirm (single gate)

Show, and wait for one confirmation:

- the changelog diff just produced,
- the commit message that will be used, and
- the proposed `.gitignore`, if the project lacks one.

`--yes` (or an explicit "no confirmation") skips this gate.

### 4. Commit and push

Follow `lib/commit.md` step 3 to commit when there is something to commit: write the proposed `.gitignore` if planned, `git add -A`, then commit — never `--no-verify`. The message: use the argument verbatim if one was given (`/push "message"`); otherwise draft a short, concrete subject line from the entries just written to the changelog, or from the diff for a non-user-facing change.

Then push the **current branch** to its upstream:

```bash
git push          # or: git push -u origin <branch>   (no upstream yet)
```

Whatever branch is checked out, integration to main is not this skill's concern. When the working tree was clean, skip the commit but still push any unpushed commits; if there is also nothing to push (git reports "Everything up-to-date"), there was nothing to do — say so.

## What this skill does not do

No version bump, no tag, no platform release, no merge/rebase to main. The moment a version should ship, that is the `release` skill.

## Files this skill uses

- `lib/changelog.md` — shared changelog-reconciliation procedure (also used by `commit` and `release`).
- `lib/commit.md` — shared stage-and-commit mechanic (also used by `commit` and `release`).
- `lib/gitignore/base.txt` — universal `.gitignore` baseline.
