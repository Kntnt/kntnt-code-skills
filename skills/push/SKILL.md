---
name: push
description: >
  Run the push workflow on the current project — reconcile the changelog
  from real changes, then commit and push the current branch. No version
  bump, no tag, no platform release, and no branch integration; those are
  the release skill's job. Trigger on the explicit invocations `/push`,
  `/kntnt-code-skills:push`, and on a plain "push" or "commit and push"
  (or the equivalent request in any language — the examples here are
  English only) when context makes it obvious it means saving work on the
  current project. When it is unclear whether this workflow is meant — for
  instance a bare `git push` with no changelog work intended — ask first
  rather than triggering.
---

# push

Save the current project's work: bring the changelog up to date with what has actually changed, commit, and push the current branch. This is the routine companion to the `release` skill — run it often so the changelog never falls behind. It deliberately stops short of releasing: no version bump, tag, platform release, or branch integration.

This is an outward-facing operation (it pushes). It is `release`'s sibling and shares the same triggering rule: trigger on `/push` or an obviously-push request in any language; **when in doubt, ask** whether the push workflow is intended before doing anything. If the invocation was a bare "push" and it might just mean a raw `git push` with no changelog work, confirm intent first.

The plugin root holds the shared pieces this skill uses. This skill lives at `skills/push/`; the plugin root is two levels up (also available as `${CLAUDE_PLUGIN_ROOT}`). Reach them there: `lib/changelog.md`, `lib/gitignore-base.txt`.

## Arguments

- `"message"` — use this exact commit message instead of an auto-drafted one.
- `--yes` — skip the confirmation gate.

## Flow

### 1. Reconcile the changelog

Load `lib/changelog.md` from the plugin root and follow it exactly. It reconciles `## [Unreleased]` in `CHANGELOG.md` with the real changes since the last release (commit messages first, diffs only as a fallback), merging without duplicating. If it reports that `[Unreleased]` is genuinely empty — nothing has changed since the last release — say so and stop; there is nothing to push.

### 2. Ensure a `.gitignore` exists

Because step 4 stages everything, a missing `.gitignore` risks committing junk. If the project has **no** `.gitignore`, propose one before staging: start from `lib/gitignore-base.txt` (the universal baseline — OS, editor, env, Claude-local) and add entries appropriate to the detected stack (e.g. `node_modules/` for Node/Bun, `/vendor/` for Composer, `__pycache__/` for Python, `/build/` and `/dist/` for build output). Show it, and write it only on confirmation. Never modify an existing `.gitignore`.

### 3. Confirm (single gate)

Show, and wait for one confirmation:

- the changelog diff just produced, and
- the commit message that will be used.

`--yes` (or an explicit "no confirmation") skips this gate.

### 4. Commit and push

```bash
git add -A
git commit -m "<message>"
git push
```

The commit message: use the argument verbatim if one was given (`/push "message"`); otherwise draft a short, concrete subject line from the entries just written to the changelog. Push the **current branch** to its upstream (`git push`, or `git push -u origin <branch>` if it has no upstream yet) — whatever branch is checked out, integration to main is not this skill's concern.

Never bypass commit hooks (`--no-verify`); let any pre-commit checks the project has run on the commit.

## What this skill does not do

No version bump, no tag, no platform release, no merge/rebase to main. The moment a version should ship, that is the `release` skill.

## Files this skill uses

- `lib/changelog.md` — shared changelog-reconciliation procedure (also used by `release`).
- `lib/gitignore-base.txt` — universal `.gitignore` baseline.
