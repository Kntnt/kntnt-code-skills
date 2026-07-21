# orchestrate

## NAME

`orchestrate` — away-from-keyboard, multi-agent build from a project's ready-for-agent issues

## SYNOPSIS

```
/kntnt-code-skills:orchestrate [scope] [--level=XS|S|M|L|XL] [--merge | --pr]
                                [--max-fix-rounds=N] [--max-lenses=N]
                                [--plan | --dry-run] [--yes]
/kntnt-code-skills:orchestrate (help | --help | -h)
```

## DESCRIPTION

`orchestrate` turns a project's `ready-for-agent` issues into implemented, independently verified, integrated code without supervision. A deterministic helper (`scripts/orchestrate.py`) plans the issues' dependency graph and the concurrency waves; a fleet of sub-agents then drives each issue through three stages — **implement** (test-first, demonstrating red before green), **verify** (fresh, independent sub-agents that adversarially review only what the gates cannot), and **integrate** (in dependency order) — and the run ends with one consolidated report of what shipped and what still needs a human. It owns the quality bar and the decisions but never writes production code or reads diffs itself, and it stops short of releasing — that is the `release` skill.

It excludes `ready-for-human` issues by definition. The single `--level` ambition dial sets both how hard every sub-agent tries (model and reasoning effort, per role) and how much verification rigor each issue gets (verifier-panel size, fix-round cap); rigor **saturates at `M`** — `XS`/`S` are the lean fast lane (1 broad lens, 1 fix round) and `M`/`L`/`XL` share the full 3-lens, 2-round tier, so above `M` the dial buys thinking depth, not more process. `--max-fix-rounds` and `--max-lenses` override the level-derived rigor for one run. By default it opens a pull request per issue and leaves the merge to a human; `--merge` grants merge authority for the run (or a project's own standing merge policy does), integrating each verified issue onto the default branch as it lands; `--pr` is the explicit, per-run override back to the conservative PR default — supplying both in one run is an error. A single confirmation gate stands before the run begins — `--yes` waives only that go/no-go, never merge authority — and `--plan`/`--dry-run` stop at the plan itself, before the gate.

Trigger only on an explicit invocation or an unmistakable request to build the issues with sub-agents — never on a vague "implement this."

## OPTIONS

| Option | Description |
|---|---|
| `[scope]` | Which issues to take on: a label (`--label=…`), a milestone (`--milestone=…`), an explicit list (`#42,#43,#48`), or nothing — which defaults to the open `ready-for-agent` issues. |
| `--level` | The single ambition dial — `XS`, `S`, `M`, `L`, or `XL` (default `M`): the per-role model/effort every sub-agent gets, and the verification-rigor baseline (verifier-panel size, fix-round cap). |
| `--merge` | Grant merge authority for this run: integrate each finished issue into the default branch automatically. |
| `--pr` | Force PR mode for this run, overriding a merge-granting project policy without changing the policy itself. |
| `--max-fix-rounds=N` | Override the level-derived fix↔verify cap. The only way to reach `0` rounds (a scan/triage run). |
| `--max-lenses=N` | Override the level-derived per-issue verifier-panel size. `N=0` is the only route to a zero panel — it skips the per-issue independent verify stage entirely (the implementer's own test-first, red-before-green demonstration becomes self-attested); the mandatory integration review still holds regardless. |
| `--plan`, `--dry-run` | Produce the plan (scope, dependency graph, waves, merge-or-PR decision) and stop, before the confirmation gate. |
| `--yes` | Yes to the single pre-run confirmation gate, and nothing more — it does not grant merge authority. |
| `help`, `--help`, `-h` | Print this manual page and stop. |

## EXAMPLES

Plan the default `ready-for-agent` scope and stop, for review:

```
/kntnt-code-skills:orchestrate --plan
```

Run the default scope, opening one pull request per issue:

```
/kntnt-code-skills:orchestrate
```

Run unattended at the strongest ambition, landing straight on the default branch:

```
/kntnt-code-skills:orchestrate --level=XL --merge --yes
```

## FILES

| File | Purpose |
|---|---|
| `scripts/orchestrate.py` | Deterministic helper: `plan` (issues JSON → dependency graph + waves), `redgreen` (git log → red-before-green verdict), `report` (verdicts JSON → consolidated report). Never calls `claude`. |
| `skills/orchestrate/orchestrate.workflow.js` | The Workflow-tool engine: implement → verify → integrate over the planned waves. |
| `agents.d/coding-standard/` | The scaffolded standard every sub-agent codes to. |
