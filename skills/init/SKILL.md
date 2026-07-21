---
name: init
description: >
  Bootstrap a new project to Kntnt's baseline — git, the AGENTS.md
  skeleton, the coding standard scaffolded into `agents.d/coding-standard/`,
  a licence, the README/CHANGELOG/CONTRIBUTING (and NOTICE under Apache),
  and a stack-aware `.gitignore` — then optionally the first commit and the
  GitHub repo. Activate only when explicitly invoked — `/init`,
  `/kntnt-code-skills:init`, or an unmistakable request to initialise or
  scaffold a new project to the Kntnt baseline. Do not activate on a bare
  "set up a repo" or because a task happened to start a new project; when in
  doubt, ask first. Because it writes files, runs `git init`, and can create
  a GitHub repository, it is explicit-only.
argument-hint: "[help]"
---

# init

Bring a new project up to Kntnt's baseline in one pass: initialise git, lay the `AGENTS.md`/`CLAUDE.md` skeleton, scaffold the coding standard into `agents.d/coding-standard/`, fetch a licence, render the README, CHANGELOG, CONTRIBUTING (and NOTICE under Apache), and write a stack-aware `.gitignore` — then, if you want, make the first commit and create the GitHub repository. It is the common base every Kntnt project starts from; `plugin-maker` calls it before layering a plugin's own files on top.

This skill orchestrates; the deterministic, error-prone file work lives in `scripts/init.py` (the `.gitignore` compose, the template token substitution, the licence fetch and post-processing). Run that script for those steps rather than hand-rolling them.

It is explicit-only and it writes files, runs `git init`, and can create a GitHub repository. Never run it because a task happened to start a new project; run it only when Thomas asks to initialise one. When the intent is unclear, ask first.

## 0. Help gate

If the arguments are `help`, `--help`, or `-h`, run `uv run "${CLAUDE_PLUGIN_ROOT}/scripts/help.py" init`, emit its output verbatim as Markdown, and stop. Do nothing else — no file is written, no git command runs.

## Identity tokens

Resolve the project's identity once, up front, the same way `plugin-maker` does, then confirm rather than assume silently:

- **owner / author** — `git config user.name` / `user.email`, then `gh api user`, then the directory name. For Thomas's projects this is **Thomas Barregren / Kntnt**.
- **author URL** — Thomas's is `https://kntnt.com`; otherwise the eventual repo URL.
- **project name** — the working-directory name.
- **year** — the current year (**2026**).
- **date** — today, ISO `YYYY-MM-DD`, for the initial CHANGELOG entry.

## Flow

### 1. Initialise git

If the directory is not already a git repository, run `git init`. Skip it when one exists — never re-initialise.

### 2. Lay the AGENTS.md skeleton

Invoke **`kntnt-skills:agents-md --force`** by qualified name through the Skill tool. `--force` lays the canonical skeleton (`CLAUDE.md` = `@AGENTS.md`, an `AGENTS.md` with the Ground rules block and an empty `## References`, and `agents.d/` with a `.gitkeep`) even on a bare new project where ordinary discovery would write nothing.

### 3. Scaffold the coding standard

Ask which coding-standard modules apply with an `AskUserQuestion` **multiSelect**. Build the option list **dynamically** from `${CLAUDE_PLUGIN_ROOT}/lib/coding-standard/*.md`, dropping `_index.md` and `general` (so a module added later appears automatically). `general` is always included and need not be offered.

Take the picked modules, **expand their prerequisites** (`scaffold.py` does this — `wordpress` pulls in `php`, `wordpress-block` pulls in `wordpress` + `typescript`, and `general` is always present), and show Thomas the expanded set. Then scaffold them — run `/coding-standard` (or `scripts/scaffold.py` directly) with the picked modules as `--include`:

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/scaffold.py" \
    --project-dir . \
    --modules-dir "${CLAUDE_PLUGIN_ROOT}/lib/coding-standard" \
    --include <picked,modules>
```

This writes the module files and the `AGENTS.md` References. Once real files live in `agents.d/`, **remove the `agents.d/.gitkeep`** the skeleton left — it is no longer needed.

Keep the expanded module list; steps 4 and 7 reuse it.

### 4. Write the `.gitignore`

Compose it from the universal baseline plus the per-module fragment for each expanded module, deduplicated, via the script:

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/init.py" gitignore \
    --gitignore-dir "${CLAUDE_PLUGIN_ROOT}/lib/gitignore" \
    --include <expanded,modules> \
    --project-dir .
```

### 5. Load the writing rules

Before writing any human-facing file (README, CHANGELOG, CONTRIBUTING), invoke **`kntnt-text-skills:writing-rules en_GB`** by qualified name through the Skill tool, so the prose that follows is on-standard.

### 6. Choose and fetch the licence

Ask which licence with `AskUserQuestion`: **Apache-2.0**, **GPL-2.0**, **GPL-3.0**, **MIT-0**, **BSD-1-Clause**, **other** (an SPDX id Thomas supplies), or **none**. Unless told otherwise, default to **Apache-2.0** (the Kntnt house licence). For anything but *none*, fetch and write `LICENSE`:

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/init.py" license \
    --spdx <SPDX-ID> --year 2026 --owner "Kntnt" --project-dir .
```

The script maps `GPL-2.0` → `GPL-2.0-only` and `GPL-3.0` → `GPL-3.0-only`, fills the year/owner placeholders only for BSD-1-Clause and MIT-0 (Apache and GPL stay verbatim; Apache's copyright lives in NOTICE), and reports — without aborting — if the fetch fails. **On a licence-fetch failure, say so and continue without a `LICENSE`.** For *none*, write no `LICENSE`.

### 7. Render the project docs

Render README, CHANGELOG, CONTRIBUTING (and NOTICE only under Apache) from the generic templates, with the identity tokens substituted:

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/init.py" templates \
    --templates-dir "${CLAUDE_PLUGIN_ROOT}/lib/templates" \
    --project-dir . \
    --project-name "<name>" --owner "Kntnt" \
    --description "<one-line description>" \
    --author-name "Thomas Barregren" --author-url "https://kntnt.com" \
    --year 2026 --date <YYYY-MM-DD> --spdx <SPDX-ID>
```

These are skeletons with the structure and the fixed boilerplate in place; flesh out the prose (Description, Key features, Usage, …) per the writing rules loaded in step 5 — the README especially.

### 8. Offer the first commit

Ask whether to make the initial commit. If yes, `git add -A` and commit with a clear message (and the Co-Authored-By trailer from the global instructions). This is always asked — there is no flag to suppress it.

### 9. Offer the GitHub repository

Ask where to create the repo: (1) the detected `<owner>/<dirname>` — resolve the owner from `gh api user` login plus `gh api user/orgs`, preferring an org like `Kntnt` when present; (2) a manual `owner/name`; or (3) none. Then ask public or private (default **public**):

```bash
gh repo create <owner>/<name> --source=. --remote=origin --push --public
```

If `gh` is missing or unauthenticated, report it, skip this step gracefully, and suggest `gh auth login`.

## Seam with `plugin-maker`

`init` has no `--no-finish` flag: it always asks the commit and GitHub questions. When it runs **under `plugin-maker`**, defer those two sensibly — `plugin-maker` still has plugin-specific files to add and re-asks the commit/GitHub questions at its own finish. `init` lays the common base (git, skeleton, standard, licence, docs, `.gitignore`); `plugin-maker` layers `.claude-plugin/`, the help command, the audit, the skills, and the rest on top.

## Files this skill uses

- `scripts/init.py` — the deterministic file work: `gitignore` (baseline + module fragments, deduped), `templates` (token substitution), and `license` (SPDX fetch + placeholder fill). Covered by `tests/test_init.py`.
- `lib/templates/` — the generic, tokenised README, CHANGELOG, CONTRIBUTING, and NOTICE.
- `lib/gitignore/` — the `.gitignore` baseline (`base.txt`) and per-module fragments.
- `scripts/scaffold.py` + `lib/coding-standard/` — the coding-standard engine and modules (step 3).
