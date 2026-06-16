---
name: orchestrate
description: >
  Run an away-from-keyboard multi-agent build that turns a project's open
  issues into implemented, independently verified, integrated code. The
  orchestrator plans from the issues' dependency graph, dispatches one
  implementer sub-agent per issue (test-first, red/green/refactor), then
  fresh independent verifier sub-agents that adversarially review what the
  gates cannot, integrates in dependency order, and ends with one
  consolidated report. It does not bump, tag, or release — that is the
  release skill. Trigger only on the explicit invocations `/orchestrate`,
  `/kntnt-code-skills:orchestrate`, or an unmistakable request to
  orchestrate or implement the open issues with sub-agents (in any
  language — the examples here are English only). Because it spawns many
  sub-agents and can integrate code, it never auto-triggers on a vague
  "implement this": when in doubt, ask first.
---

# orchestrate

Turn a project's open issues into finished code without supervision: the orchestrator reads the issues, plans from their dependency graph, and drives a fleet of sub-agents through implement → independently verify → integrate, then hands you one consolidated report of what shipped and what still needs a human. It owns the quality bar and the decisions; it never writes production code or reads diffs itself. It stops short of releasing — bump, tag, and platform release stay with the `release` skill.

This is an outward-facing, autonomous run: it spawns many sub-agents and, when authorized, integrates code. It shares the *when in doubt, ask* posture of `release` and `push` — trigger on `/orchestrate` or an unmistakable request to build the open issues with sub-agents, never on a vague "implement this".

## When to use

- After the issues are filed and ready — clear acceptance criteria, and `Blocked by` relationships recorded where dependencies exist. Invoke it once, at the end, and walk away.
- When the project carries the context a sub-agent needs to work to standard: a coding standard (`coder`'s scaffolded `docs/coding-standards.md`, or the orchestrator scaffolds it first), a definition of done and a test strategy if the project has them, and the ADRs or design docs the issues reference. The orchestrator reads these and passes the relevant ones to each sub-agent.
- When you genuinely want the work done away from the keyboard. The run is autonomous after a single confirmation; nothing waits on you mid-flight.

## Arguments

- `[scope]` — which issues to take on: a label (`--label=…`), a milestone (`--milestone=…`), an explicit list (`#42,#43,#48`), or nothing. With no scope, default to the open issues carrying the project's agreed away-from-keyboard label; if none is obvious, ask which issues are in scope.
- `--merge` — integrate finished issues into the default branch automatically. The default is conservative: open one pull request per issue (or one for the integrated whole) and leave the merge to you, unless the project's own policy already authorizes merging away from the keyboard.
- `--max-fix-rounds=N` — cap on the fix↔verify loop per issue (default 2). After the cap, the issue is parked in the final report rather than burning tokens on an endless loop.
- `--sequential` / `--parallel` — concurrency. The default is safe: sequential in dependency order, parallelizing only issues whose file sets are disjoint.
- `--plan` / `--dry-run` — produce the plan (scope, dependency graph, waves, model assignment, merge-or-PR decision) and stop, so you can review before the real run.
- `--yes` — skip the single pre-run confirmation gate.

## The operating contract

If the project's `AGENTS.md` defines an autonomous-agent and reporting model, follow it. Otherwise this contract binds the orchestrator and every sub-agent:

- **Never block on the maintainer.** No sub-agent stops to ask for input, to have a test run for it, or to wait on a decision. Genuine ambiguity is resolved by the most reasonable assumption, recorded and reported — never a silent guess that hides the choice, and never a pause.
- **The one exception is a true design blocker** — work that cannot proceed without contradicting a settled decision (an ADR, a design doc, a load-bearing invariant). There the sub-agent neither guesses past the decision nor waits: it stops that one unit, records the blocker, and continues with everything else it can do. The blocker surfaces in the final report for the maintainer to resolve.
- **Every sub-agent reports in three buckets** to its caller: *Automatically tested* (what, at which layer), *Remaining for a human* (the irreducibly subjective checks automation cannot meaningfully make), and *Assumptions & blockers*.

## Flow

### 1. Profile and gather

Read the project's `CLAUDE.md` / `AGENTS.md` and the `docs/` they point at — the coding standard, the definition of done, the test strategy, and the ADRs or design docs the issues reference. Then resolve the issue scope (from the argument, else the default) and read every in-scope issue with `gh issue view`, including its acceptance criteria and `Blocked by` section.

If the project has no `docs/coding-standards.md`, invoke the `coder` skill once to scaffold it before dispatching. Sub-agents cannot invoke skills, so the standard must reach them as a file they can read.

### 2. Plan

Build the dependency graph from each issue's `Blocked by`. Identify the **hot files** that several issues touch by scanning their likely targets — these, not the stated blockers alone, are the real serialization constraint. Decide concurrency: default to sequential in dependency order on one integration branch, parallelizing (one git worktree per sub-agent, isolated) only issues whose file sets are disjoint. Never run two issues that share a hot file at the same time. With `--plan`, present the graph, the waves, the model assignment, and the merge-or-PR decision, then stop.

### 3. Assign models

The orchestrator runs in the session you launched it in — use your strongest tier, since the verification quality rides on its judgement, and it stays cheap because it processes little volume (plans, verdicts, decisions). Every sub-agent runs at the project's agreed floor (default: the session model), never below it. The cheap deterministic checks — did the gates run green, is there a demonstrated failing-test commit before the green one, does every acceptance criterion map to a test — the orchestrator does itself, without spending a sub-agent.

### 4. Per-issue lifecycle

For each issue, in dependency order and respecting the concurrency policy:

1. **Implement.** Dispatch one implementer sub-agent on its own branch. It reads the standard and the cited ADR(s) / design docs, implements **test-first** (red/green/refactor) at the layer the project's test strategy prescribes, and **demonstrates the red** — a failing-test commit before the implementing commit, because a test never seen to fail is of unknown value. It automates everything meaningfully automatable, runs the project's gates, reports their real results, resolves ambiguity by recorded assumption, and returns the three-bucket report.

2. **Verify, independently.** Only after the implementer reports green, dispatch fresh verifier sub-agent(s) that did **not** write the code. Give each only the branch diff, the issue's acceptance criteria, and the cited standard / ADR. They check **only what the gates cannot**: correctness against the spec's intent; test quality (is the red demonstrated? are the tests load-bearing rather than tautological? does every criterion map to a test?); security and edge cases; and the standard's judgement calls. They do not re-check what static analysis, the linters, the test run, and the build already prove — that is wasted effort. Each returns a structured verdict.

   Scale the panel to the issue's risk: one reviewer for a pure-algorithm change; add a test-quality reviewer for ordinary logic; add an error-handling and security reviewer for anything touching a write path, a permission gate, a filesystem boundary, or an irreversible delete. Use the project's specialized review agents where they exist (for example a code reviewer, a silent-failure / error-handling hunter, a test-coverage analyzer, a type-design analyzer); otherwise spawn generic verifier sub-agents with the same adversarial brief. Diverse lenses catch what identical reviewers miss.

3. **Decide.** Read only the verdicts — never the diffs yourself. All clear → integrate. Any real finding → return it to the same implementer sub-agent to fix, then re-verify. Cap the loop at `--max-fix-rounds` (default 2); if it still fails, stop that issue only, record it under *Assumptions & blockers*, and continue with everything else.

4. **Integrate.** Merge finished issues in dependency order; rebase dependents after each merge so a serial chain through a hot file never conflicts. Under the conservative default, open a pull request instead and leave the merge to the maintainer.

### 5. Finalize

Re-run the full gate suite over the merged whole — green on each issue does not guarantee green on the union — and commission one light integration-smoke verifier over the combined diff. Then produce **one** consolidated report: each issue, done with its gate results and verify verdict; then the de-duplicated *Remaining for a human* list; then any *Assumptions & blockers*, including capped-out or blocked issues. Lead with what is done and green; end with what is left for the maintainer.

Do not bump the version, tag, or publish a release. When the merged work is ready to ship, that is the `release` skill.

## Confirmation gate

The run is autonomous once it starts, so confirm once before it begins: show the plan from step 2 — scope, dependency graph, waves, model assignment, and whether it will merge or open pull requests — and wait for a single confirmation. `--yes`, or a `--plan` you have already reviewed, skips it. Beyond that one gate the orchestrator does not stop, with a single exception: integrating into the default branch is the one irreversible, outward-facing step, so it happens only under `--merge` or an explicit project authorization to merge away from the keyboard; otherwise the work lands as pull requests for the maintainer to merge.

## What this skill does not do

- **No release.** No version bump, tag, or platform release — hand the merged work to `release`.
- **No design decisions.** It never resolves a true design blocker by overriding an ADR or design doc; it records the blocker and moves on.
- **No code by its own hand.** The orchestrator plans, dispatches, judges verdicts, and integrates; the sub-agents write and verify the code.

## Relationship to the other skills

- **`coder`** is the standard the sub-agents code to. Because sub-agents cannot invoke skills, they read the project's checked-in `docs/coding-standards.md` (coder's scaffold); when it is absent, the orchestrator runs `coder` once to produce it before dispatching.
- **`push` / `release`** take over at the end. `orchestrate` stops at integrated, verified, green code; `push` saves in-progress work, and `release` ships a version.
