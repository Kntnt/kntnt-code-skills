---
name: doctor
description: >
  Diagnose a project against Kntnt's baseline and propose the fixes that
  bring it back into line — git state, `.gitignore` coverage, the coding
  standard's home and sync, the licence/NOTICE pairing, and (via a
  read-only Workflow) whether AGENTS.md, the agents.d/ files, and the
  README still match the real code. Activate only when explicitly
  invoked — `/doctor`, `/kntnt-code-skills:doctor`, or an unmistakable
  request to health-check, diagnose, or reconcile a project against the
  Kntnt baseline. Do not activate on a vague "check my project" or
  "what's wrong here"; when in doubt, ask first. `--yes` applies the
  fixes without prompting (it never commits).
---

# doctor

Health-check a project against the same baseline `/init` lays down, then offer to apply the fixes that bring it back into line. It is **init's idempotent reconciler**: where `init` creates the baseline once, `doctor` re-checks it any time and proposes only what has drifted — a missing `.gitignore` entry, a licence with no NOTICE, a coding standard that has fallen out of sync, an AGENTS.md or README that no longer matches the code. It is read-only until you choose which fixes to apply, and it never commits — reviewing doctor's own changes before committing is the point.

The cheap, deterministic checks run in `scripts/doctor.py` (JSON findings); the heavy, judgement-laden analysis — does each context file and the README still hold against the real code? — runs in a read-only **Workflow** (`skills/doctor/doctor.workflow.js`) that returns structured findings and applies no fixes. This SKILL.md consolidates both, asks which to apply, and applies them.

It is explicit-only and it can rewrite files. Run it only when Thomas asks to diagnose or reconcile a project; when the intent is unclear, ask first.

## 0. Help gate

If the arguments are `help`, `--help`, or `-h`, run `uv run "${CLAUDE_PLUGIN_ROOT}/scripts/help.py" doctor`, emit its output verbatim as Markdown, and stop. Do nothing else — no check runs, no fix is applied.

## Arguments

- `--yes` — apply every proposed fix without the selection prompt. It still **never commits** — doctor's fixes are left in the working tree for review.

## Flow

### 1. Run the deterministic checks

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/doctor.py" --project-dir .
```

It emits `{ "findings": [...] }`, each `{category, severity, message, remedy, auto_fixable}`, covering: git repo present and clean (report-only — the remedy is `/push`, **never** an auto-commit); `.gitignore` present and covering the baseline plus the fragments for the project's scaffolded modules; the coding standard in its correct home (`agents.d/coding-standard/`, not a stale `docs/coding-standard/` or `docs/coding-standards.md`) and in sync (it delegates to `scaffold.py investigate`); and a `LICENSE` present, with a `NOTICE` beside it under Apache.

### 2. Run the heavy analysis (Workflow)

Take the cheap inventory (which of `AGENTS.md`, `CLAUDE.md`, `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `NOTICE` exist, and the list of non-standard `agents.d/*` files — everything under `agents.d/` except `coding-standard/`), then launch the read-only Workflow:

```text
Workflow({
  scriptPath: "${CLAUDE_PLUGIN_ROOT}/skills/doctor/doctor.workflow.js",
  args: { projectDir: "<abs>", inventory: {...}, agentsDExtra: [...] },
})
```

It runs two passes — **structural** (Sonnet, batched: context files vs the agents-md shape; project docs vs their templates) and **reality** (Opus, `xhigh`, one agent per file: AGENTS.md, each non-standard `agents.d/*`, and README read the actual code to verify their claims; CHANGELOG checks `[Unreleased]` against the commits; NOTICE a light attribution check). It returns `{ findings: [...] }` and changes nothing. Because this SKILL.md instructs the Workflow call, that is the valid opt-in for the tool.

### 3. Consolidate and choose

Merge the script findings and the Workflow findings into one report **grouped by category** (git, gitignore, coding-standard, license, agents-md, readme, changelog, notice), each with its severity and remedy. Then present a single `AskUserQuestion` **multiSelect**: "which fixes to apply?". With `--yes`, skip the prompt and apply them all.

### 4. Apply the chosen fixes

- **Mechanical fixes inline** — append the missing `.gitignore` entries; migrate `docs/coding-standard*` into `agents.d/coding-standard/` and re-point the `AGENTS.md` References; run `/coding-standard --update` for a drifted scaffold; add a NOTICE from the template under Apache.
- **Judgement fixes dispatch a fixer subagent** (Opus, `xhigh`) — rewriting a README, an AGENTS.md, or an `agents.d/*` file to match the reality the Workflow found. Give it the specific findings and the file; it edits only that file.
- **Never auto-commit, even under `--yes`.** The git "uncommitted changes" finding's remedy is `/push`; doctor's own fixes are left uncommitted so Thomas can review them.

### 5. Report

Summarise what was found, what was fixed (inline vs subagent), what was left (and why), and that nothing was committed — the changes are staged for review, and `/push` is the next step when they look right.

## Files this skill uses

- `scripts/doctor.py` — the deterministic checks (git, gitignore, coding-standard location + sync, licence/NOTICE); JSON findings. Covered by `tests/test_doctor.py`.
- `skills/doctor/doctor.workflow.js` — the read-only heavy analysis (structural + reality), structured findings only.
- `scripts/scaffold.py`, `lib/gitignore/`, `lib/templates/` — the same baseline `/init` uses, so doctor reconciles to exactly what `/init` would have produced.
