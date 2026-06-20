# Shared procedure — reconcile `[Unreleased]` with reality

Both `release` and `push` start here. The purpose is to make the `## [Unreleased]` section of `CHANGELOG.md` an accurate, human-quality record of everything that has changed since the last release — because changelog entries are rarely written at the moment a change is made.

This procedure only ever **reads** history and **edits the `[Unreleased]` section**. It never bumps the version, promotes the section, commits, tags, or pushes — those belong to the calling skill's own steps.

## 1. Ensure a changelog exists

Locate `CHANGELOG.md` at the repository root. If it is missing, create it in Keep a Changelog shape and continue:

```markdown
# Changelog

All notable changes to this project are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/) and the project
uses [Semantic Versioning](https://semver.org/).

## [Unreleased]
```

If the file exists but has no `## [Unreleased]` heading, add an empty one directly beneath the intro paragraph.

## 2. Establish the baseline

The baseline is the point the reconciliation looks back from — the last release:

```bash
git describe --tags --abbrev=0 --match 'v*' 2>/dev/null
```

- A tag (e.g. `v0.3.0`) → reconcile everything since that tag.
- Empty output → this is the first release; reconcile the whole history.

## 3. Gather what actually changed

Two sources, both in scope — work is often left uncommitted at this point:

```bash
# Commits since the baseline (oldest first), subject + body.
git log <baseline>..HEAD --reverse --format='%h%x09%s%n%b'

# Uncommitted work in the working tree.
git status --porcelain
git diff HEAD
```

On a first release, drop `<baseline>..` and read `git log --reverse`.

## 4. Read messages first, diffs only as a fallback

Commit subjects are the primary signal — read them first. Only when a message is too thin to write a clear, understandable entry (e.g. "wip", "fix", "commit and push") read that one commit's diff to learn what it actually did:

```bash
git show <sha>            # the full change for one commit
git show <sha> --stat     # just the touched files, when that is enough
```

Do not dump diffs wholesale; reach for them surgically, per unclear commit.

## 5. Write categorized, user-facing entries

Sort the real changes into Keep a Changelog sections, in this order, and include only the sections that have content:

`Added` · `Changed` · `Deprecated` · `Removed` · `Fixed` · `Security`

Quality bar for each line:

- Describe the change from the reader's point of view — what is now different — not the commit mechanics. Never a git-log dump.
- One concrete change per bullet; specific, not "various fixes".
- Match the voice of the entries already in the file.
- Use the language the existing changelog is written in.

## 6. Merge into `[Unreleased]`, deduplicating

Some entries may already be present (most will not be). Read the existing `## [Unreleased]` content and add only what is missing — never duplicate a change that is already recorded. The result is the merged, complete `[Unreleased]` section written back into `CHANGELOG.md`.

This step is idempotent: running it again finds nothing new to add.

## 7. Hand back

Leave `CHANGELOG.md` with an accurate `[Unreleased]` section and stop. The calling skill takes it from here — `push` commits it as-is; `release` promotes it to a dated version. If `[Unreleased]` is still empty after reconciliation, there is genuinely nothing to release or record; report that to the caller rather than inventing entries.
