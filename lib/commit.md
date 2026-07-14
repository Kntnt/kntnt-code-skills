# Shared procedure — stage and commit

The commit spine shared by `commit`, `push` and `release`. Its purpose is the mechanical part of recording work: make sure a `.gitignore` guards the staging, stage everything, and commit — nothing more. It is the sibling of `lib/changelog.md`, which runs *before* this and leaves `CHANGELOG.md` accurate; this procedure takes the working tree from there to a commit.

This procedure only ever **stages and commits**. It does not reconcile the changelog (that is `lib/changelog.md`), and it does not push, tag, promote the changelog, or publish a release — those belong to the calling skill's own steps. It commits whatever is in the working tree onto the **current branch's HEAD**; choosing the branch, and integrating one, is the caller's concern.

The caller shows its single confirmation gate **before** step 3 executes. The proposed `.gitignore` (step 2) and the commit message (step 3) are part of what that gate shows.

## 1. Confirm there is something to commit

If `git status --porcelain` is empty and nothing is staged, the working tree is clean — there is nothing to commit. Report that to the caller and stop:

```bash
git status --porcelain
```

`commit` and `push` reach this procedure precisely to save a dirty working tree, so a clean tree means "nothing to do". `release` reaches it only after staging its version edits, so the tree is never clean here and this check passes trivially.

## 2. Ensure a `.gitignore` exists

Step 3 stages **everything** (`git add -A`), so a missing `.gitignore` risks committing junk. If the project has **no** `.gitignore`, propose one before staging: start from `lib/gitignore/base.txt` (the universal baseline — OS, editor, env, Claude-local) and add entries appropriate to the detected stack (e.g. `node_modules/` for Node/Bun, `/vendor/` for Composer, `__pycache__/` for Python, `/build/` and `/dist/` for build output). This proposal is part of the caller's confirmation gate; write the file only once that gate is confirmed. **Never modify an existing `.gitignore`.**

## 3. Stage and commit

```bash
git add -A
git commit -m "<message>"
```

**The message.** Use the caller-supplied message verbatim when there is one — an explicit argument (`/commit "message"`, `/push "message"`) or the release's own `Release X.Y.Z: …` subject. Otherwise draft a short, concrete subject line from the entries just written to the changelog; when the change produced no user-facing changelog entry (a pure refactor, formatting, or test-only change), draft it from the actual diff instead.

**Never bypass commit hooks** (`--no-verify`); let any pre-commit checks the project has configured run on the commit. A hook that fails has caught something — stop and report it rather than forcing the commit through.

## 4. Hand back

The commit now exists on the current branch's HEAD. The calling skill takes it from here: `commit` stops, `push` runs `git push`, `release` tags, pushes and publishes — each as its own step.
