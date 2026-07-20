# doctor

## NAME

`doctor` — diagnose a project against Kntnt's baseline and propose the fixes

## SYNOPSIS

```
/kntnt-code-skills:doctor [--yes]
/kntnt-code-skills:doctor (help | --help | -h)
```

## DESCRIPTION

`doctor` health-checks a project against the same baseline `init` lays down, then offers to apply the fixes that bring it back into line. It is `init`'s idempotent reconciler: where `init` creates the baseline once, `doctor` re-checks it any time and proposes only what has drifted — a missing `.gitignore` entry, a licence with no NOTICE, a coding standard that has fallen out of sync, or an `AGENTS.md`, `agents.d/*` file, or README that no longer matches the code.

The cheap, deterministic checks (`scripts/doctor.py`) cover git state, `.gitignore` coverage, the coding standard's home and sync, and the licence/NOTICE pairing. A read-only Workflow (`skills/doctor/doctor.workflow.js`) covers the judgement-laden checks — whether `AGENTS.md`, the `agents.d/` files, and the README still match the real code. Findings from both are merged into one report grouped by category, each with its severity and remedy, then presented as a multi-select prompt of which fixes to apply.

`doctor` is read-only until fixes are chosen, and it **never commits** — even under `--yes` — so its own changes are left in the working tree for review; `push` is the next step once they look right.

## OPTIONS

| Option | Description |
|---|---|
| `--yes` | Apply every proposed fix without the selection prompt. Still never commits. |
| `help`, `--help`, `-h` | Print this manual page and stop. |

## EXAMPLES

Diagnose the project and choose which fixes to apply:

```
/kntnt-code-skills:doctor
```

Diagnose and apply every proposed fix, unattended:

```
/kntnt-code-skills:doctor --yes
```

## FILES

| File | Purpose |
|---|---|
| `scripts/doctor.py` | The deterministic checks (git, `.gitignore`, coding-standard location + sync, licence/NOTICE); emits JSON findings. |
| `skills/doctor/doctor.workflow.js` | The read-only heavy analysis (structural + reality checks against the real code); returns structured findings, applies no fixes. |
| `scripts/scaffold.py`, `lib/gitignore/`, `lib/templates/` | The same baseline `init` uses, so `doctor`'s fixes reconcile to what `init` would have produced. |
