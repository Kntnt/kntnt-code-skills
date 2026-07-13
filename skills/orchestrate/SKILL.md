---
name: orchestrate
description: >
  Run an away-from-keyboard, multi-agent build that turns a project's
  ready-for-agent issues into implemented, independently verified,
  integrated code. The orchestrator plans the issues' dependency graph
  with a deterministic helper, then drives sub-agents through implement
  (test-first) → independently verify (adversarial, only what the gates
  cannot) → integrate, and ends with one consolidated report. It owns the
  quality bar but never writes code or reads diffs itself, and it does not
  bump, tag, or release — that is the release skill. Trigger only on the
  explicit invocations `/orchestrate`, `/kntnt-code-skills:orchestrate`,
  or an unmistakable request to build the open issues with sub-agents (in
  any language — the examples here are English only). Because it spawns
  many sub-agents and can integrate code, it never auto-triggers on a
  vague "implement this": when in doubt, ask first.
---

# orchestrate

Turn a project's ready-for-agent issues into finished code without supervision: the orchestrator reads the issues and their agent briefs, plans from their dependency graph, and drives a fleet of sub-agents through implement → independently verify → integrate, then hands you one consolidated report of what shipped and what still needs a human. It owns the quality bar and the decisions; it never writes production code or reads diffs itself. It stops short of releasing — bump, tag, and platform release stay with the `release` skill.

This is an outward-facing, autonomous run: it spawns many sub-agents and, when authorized, integrates code. It shares the *when in doubt, ask* posture of `release` and `push` — trigger on `/orchestrate` or an unmistakable request to build the issues with sub-agents, never on a vague "implement this". A single confirmation gate stands before the run begins; beyond it, nothing waits on you.

The plugin root holds the pieces this skill uses. This skill lives at `skills/orchestrate/`; the plugin root is two levels up (also `${CLAUDE_PLUGIN_ROOT}`). Reach them there: the deterministic helper `scripts/orchestrate.py` (run with `uv run`) and the engine `skills/orchestrate/orchestrate.workflow.js` (run through the Workflow tool).

## Cost model — read this first

The work must land in the **interactive subscription pool**, not the headless credit pool. So:

- **Every sub-agent runs inside the interactive session**, through the **Workflow tool** (preferred) or the **Agent tool** (fallback). Both count against the Max subscription, the same as this session.
- **Never wrap the run in `claude -p`.** Headless invocation draws from the separate, API-priced monthly credit that does not roll over. If you want it unattended, use the Workflow tool's own loop or `/goal` *inside* the interactive session (see *Running it unattended*).
- **`scripts/orchestrate.py` never calls `claude`.** It is pure deterministic bookkeeping (parse issues → dependency graph → waves; fold verdicts → report). Code computes; sub-agents judge; nothing shells out to Claude.

## What it consumes — the contract

`orchestrate` is the last stage of a pipeline, not a standalone. Upstream, `grill-with-docs` sharpens the plan, `to-issues` cuts it into vertical-slice issues (each marked HITL or AFK, with checkbox acceptance criteria and a `Blocked by` section), and `triage` moves each issue to a terminal state and writes its brief. This skill reads that output:

- **Scope defaults to the `ready-for-agent` issues** — triage's "fully specified, ready for an AFK agent" state (the real label string may be mapped per project). It **excludes `ready-for-human`**: those need human implementation by definition and are never built autonomously.
- **The agent brief is the per-issue contract when one exists.** When an issue reaches `ready-for-agent`, triage posts a durable agent brief (behavioral, no file paths, with testable acceptance criteria and explicit out-of-scope). If an Agent Brief comment exists it is authoritative and the issue body is context; **otherwise the issue body and its acceptance criteria are the contract**, so an issue whose brief was never posted is still built without error. The plan flags each in-scope issue that has no brief.
- **The acceptance criteria and `Blocked by` are machine-read** by `orchestrate.py plan` to build the graph — so the serialization constraint is computed, not guessed.

When the project carries no such pipeline, fall back to whatever `CLAUDE.md` / `AGENTS.md` defines as its autonomous-agent contract, and resolve scope from the argument.

## Arguments

- `[scope]` — which issues to take on: a label (`--label=…`), a milestone (`--milestone=…`), an explicit list (`#42,#43,#48`), or nothing. With no scope, default to the open `ready-for-agent` issues. Resolve scope **without asking** (see the operating contract); if it genuinely cannot be resolved, stop with a one-line report rather than pausing mid-run.
- `--merge` — integrate finished issues into the default branch automatically. The default is conservative: open one pull request per issue and leave the merge to you, unless the project's own policy already authorizes merging away from the keyboard.
- `--max-fix-rounds=N` — cap on the fix↔verify loop per issue (default 1). After the cap, the issue is parked in the report rather than looping.
- `--plan` / `--dry-run` — produce the plan (scope, dependency graph, waves, merge-or-PR decision) and stop, so you can review before the real run.
- `--yes` — skip the single pre-run confirmation gate.

## The operating contract

If the project defines its own autonomous-agent and reporting model, follow it. Otherwise this contract binds the orchestrator and every sub-agent:

- **Never block on the maintainer.** No sub-agent stops to ask for input, to have a test run for it, or to wait on a decision — and neither does the orchestrator. This is a hard rule: the run was started so the maintainer could walk away. Genuine ambiguity is resolved by the most reasonable assumption, recorded and reported — never a silent guess, never a pause.
- **The one exception is a true design blocker** — work that cannot proceed without contradicting a settled decision (an ADR, a design doc, a load-bearing invariant). Triage should already have routed most of these to `ready-for-human`; this is the safety net for what it missed. The sub-agent neither guesses past the decision nor waits: it parks that one unit, records the blocker, and continues with everything else.
- **Every sub-agent reports in three buckets** to its caller: *Automatically tested* (what, at which layer), *Remaining for a human* (the irreducibly subjective checks automation cannot meaningfully make), and *Assumptions & blockers*.
- **No sub-agent closes the issue, pushes, or merges.** Those are the orchestrator's and the integrate step's actions alone; the issue is closed only after independent verification, never by a sub-agent — a prohibition the engine hard-codes into every implement, fix, and verify prompt.

## Flow

### 1. Profile and gather

Read the project's `CLAUDE.md` / `AGENTS.md` and the `docs/` they point at — the coding standard, the definition of done, the test strategy, and the ADRs or design docs the issues reference. Resolve the scope (default: `ready-for-agent`, excluding `ready-for-human`), then read every in-scope issue **and its agent brief** with `gh issue view <n> --comments`.

Sub-agents cannot invoke skills, so the standard and the test discipline must reach them **as files they can read** (the `skill-by-reference` pattern). If the project has no `agents.d/coding-standard/` directory, run `/coding-standard` once to scaffold it before dispatching; the sub-agents then read `general.md` plus the module(s) for the language or framework they touch.

### 2. Plan (deterministic)

Hand the issues to the helper rather than reasoning out the graph by hand:

```bash
gh issue list --label ready-for-agent --state open \
    --json number,title,labels,body,comments --limit 200 \
  | uv run "${CLAUDE_PLUGIN_ROOT}/scripts/orchestrate.py" plan \
        --exclude-label ready-for-human
```

It returns the dependency graph, the topologically ordered **waves** (issues in one wave are independent and may run concurrently), any dependency that points outside the scope, and the issues it excluded. A dependency cycle is a hard error it reports rather than guessing past. With `--plan`, present this and stop.

Fetch `comments` (as above) so brief detection is real: the plan flags each in-scope issue that carries no Agent Brief comment — a per-issue `no_brief` boolean and a convenience top-level `issues_without_brief` list. Those issues are **still built**, from their body and acceptance criteria; the flag is visibility, not exclusion, and the engine falls back cleanly when no brief was posted.

The plan also carries a `merge_required` flag (with a human-readable `merge_note`): it is `true` whenever the in-scope graph has any cross-issue edge. Treat it as the cue for the merge-vs-PR decision below — when it is `true`, set the engine's `merge` arg (step 4) so dependents build on a base that already contains their prerequisites, rather than branching off bare `main`. The conservative one-PR-per-issue default is safe only when `merge_required` is `false`.

### 3. Confirm (single gate)

Show the plan from step 2 — scope, graph, waves, and whether the run will merge or open pull requests — and wait for one confirmation. `--yes`, or a `--plan` you have already reviewed, skips it. Beyond this gate the run does not stop, with one exception: integrating into the default branch happens only under `--merge` or an explicit project authorization; otherwise the work lands as pull requests.

### 4. Build (engine)

**Preferred — the Workflow tool.** Launch `skills/orchestrate/orchestrate.workflow.js` with the plan JSON (plus `merge`, `maxFixRounds`, and each issue's risk-scaled verifier panel `lenses`, set during planning) as `args`. The control flow — wave order, the capped fix↔verify loop, and per-issue serial dispatch that integrates each green issue the moment it is verified (so a mid-run stop leaves every prior issue durably on the default branch) — is code there, so it cannot drift over a long unattended run; agents run in the subscription pool; worktree isolation keeps concurrent agents apart; the run is budget-bounded and resumable via its `runId`.

**Fallback — the Agent tool.** Where the Workflow tool is unavailable (some Cowork / portable contexts), drive the same lifecycle from this session with the Agent tool, still calling `orchestrate.py` for the plan and the report. Use `/goal` for the outer loop (see below).

Either way the per-issue lifecycle is the same:

1. **Implement.** One implementer sub-agent on its own branch reads the **agent brief** (the contract, or — when no brief was posted — the issue body and its acceptance criteria) and the standard, implements **test-first** (red/green/refactor) at the layer the test strategy prescribes, **demonstrates the red** (a failing-test commit before the green one), runs the project's gates, reports their real results, and returns the three-bucket report.
2. **Verify, independently.** Only after green, a fresh verifier that did **not** write the code reviews **only what the gates cannot**. By default this is a **single broad adversarial reviewer** whose one lens folds every concern together — correctness against the brief's intent and acceptance criteria, test quality (is the red demonstrated? do the tests bind? does every criterion map to a test?), and any security or data-safety hazard the issue touches. Raise the panel to **2–3 focused lenses only for a genuinely high-risk issue** — a write path, a permission gate, a filesystem boundary, an irreversible delete — via the per-issue `lenses` set during planning. Use the project's specialized review agents where they exist; diverse lenses catch what identical reviewers miss, but only pay for them where the risk earns them.
3. **Decide.** Read only the verdicts — never the diffs yourself. All clear → integrate. Any real finding → return it to the same implementer to fix, then **re-verify only the fixed findings** with a single targeted reviewer — not the whole panel again — capped at `--max-fix-rounds` (default 1); if it still fails, park that issue and continue.
4. **Integrate, immediately.** Land each green issue the moment it is verified, before the next issue's work begins, in dependency order. Keep history linear: rebase the feature branch onto the up-to-date default branch and fast-forward only — never merge the default branch into the feature branch, never create a merge commit there. Landing per-issue makes partial progress durable: a stop between issues leaves every already-integrated issue on the default branch. Under the conservative default, open a pull request instead and leave the merge to the maintainer.

### 5. Finalize

Re-run the full gate suite over the merged whole — green on each issue does not guarantee green on the union. Then the engine runs a **mandatory** adversarial integration review over the combined diff of everything the run landed: one reviewer given a per-issue verifier's full rigor (never a token smoke test), hunting the cross-issue defects no per-issue lens can see — one issue's change silently weakening another's guarantee, a contradiction between two landed issues, a broken invariant across their union. It **always runs** whenever the run integrated at least one issue, its clear decision goes through the same block-unless-explicitly-cleared rule a per-issue verdict does, and it can **fix, not merely report**: a real finding drives a **bounded hotfix + re-review** — a code-touching agent on its own worktree addresses only those findings, the fix lands through the same linear rebase-and-fast-forward step, and the combined diff is re-reviewed — capped like a per-issue fix loop; a finding still unresolved at the cap is parked for a human, never dropped. Then fold the per-issue verdicts into one report:

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/orchestrate.py" report < verdicts.json
```

It leads with what is done and green, then the de-duplicated *Remaining for a human* list, then *Assumptions* and the parked or blocked issues. Do not bump the version, tag, or publish — when the merged work is ready to ship, that is the `release` skill.

## Model and effort

Put the strong model and the high effort where the judgement is, not where the routing is:

- **Implementers and the adversarial verifier** — the single broad reviewer that runs by default, plus the extra lenses a high-risk issue adds — **strongest tier, high reasoning effort.** This is where clean, correct code is born and where real bugs are caught; it is worth the spend.
- **Mechanical leaves** — test-coverage mapping, an integration smoke pass — can run a cheaper tier or, better, be replaced by code.
- **The spine is code, so there is no expensive "orchestrator LLM" doing routing.** The genuinely cheap deterministic work — is the graph acyclic (`orchestrate.py plan`), did the gates exit green, is there a red-before-green commit (`orchestrate.py redgreen`), does each criterion map to a test — belongs to the helper and the gate run (CPU, not tokens), never to a sub-agent reading text by eye.
- The one-time planning judgement (reading the briefs to set each issue's risk and verifier panel) can run on the session model.

The earlier instinct — "put the orchestrator on the top tier because verification rides on its judgement" — is inverted: the orchestrator only reads verdicts and routes, which is the cheapest work or pure code. The judgement lives in the verifier and implementer sub-agents, and that is where the tier and the effort should go.

## Running it unattended (`/goal`)

In the fallback (no Workflow tool), the cleanest "keep going until done" driver is `/goal`, combined with auto mode — `/goal` removes the per-turn prompt, auto mode the per-tool prompt:

```text
/goal every open ready-for-agent issue is closed with its PR merged, and the
full test + lint + build suite exits 0 over the integrated default branch; or
stop after 30 turns. Resolve ambiguity by assumption and never ask me.
```

Two cautions. Run `/goal` **interactively** — `claude -p "/goal …"` is headless and burns the credit pool. And `/goal`'s evaluator is a small model reading the transcript; it does **not** run your gates, so trust the **deterministic gate re-run in step 5** as the real proof of done, not the evaluator's say-so. With the Workflow tool, you do not need `/goal` at all — the workflow loops internally and returns once.

## What this skill does not do

- **No release.** No version bump, tag, or platform release — hand the merged work to `release`.
- **No design decisions.** It never resolves a true design blocker by overriding an ADR or design doc; it records the blocker and moves on.
- **No code by its own hand.** The orchestrator plans, dispatches, judges verdicts, and integrates; the sub-agents write and verify the code.
- **No `claude -p`.** No script in this skill invokes Claude headlessly; all agent work runs in the interactive session (see *Cost model*).

## Relationship to the other skills

- **`coder`** is the standard the sub-agents code to. They cannot invoke it, so they read the project's checked-in `agents.d/coding-standard/` modules (scaffolded by `/coding-standard`); when that directory is absent, the orchestrator runs `/coding-standard` once to produce it before dispatching.
- **`tdd`** is the implementer's discipline — its test-first, vertical-slice, behavior-over-implementation rules. Reach it the same way: as a file the sub-agent reads, since it cannot invoke the skill. Its planning step is human-gated, so the **agent brief** stands in for the maintainer's approval.
- **`to-issues` / `triage`** are upstream: they produce the `ready-for-agent` issues, the `Blocked by` graph, and the agent briefs this skill consumes.
- **`push` / `release`** take over at the end. `orchestrate` stops at integrated, verified, green code; `push` saves in-progress work, and `release` ships a version.

## Files this skill uses

- `scripts/orchestrate.py` — deterministic helper: `plan` (issues JSON → dependency graph + waves), `redgreen` (git-log → red-before-green verdict), and `report` (verdicts JSON → consolidated report). Never calls `claude`; covered by `tests/test_orchestrate.py`.
- `skills/orchestrate/orchestrate.workflow.js` — the Workflow-tool engine: implement → verify → integrate over the planned waves, agents in the subscription pool. A workflow script must have **exactly one top-level `export` (`export const meta`) and no other top-level `export` or `import`** — the Workflow harness rejects any additional top-level `export`/`import` with a `SyntaxError` at launch, so any helper that needs its own unit test is kept inline here and mirrored in an importable module (`lib/orchestrate/engine-helpers.mjs`) that the tests exercise.
- Reads (per project): `agents.d/coding-standard/` (the scaffolded standard), the issues' agent briefs, the definition of done, the test strategy, and the cited ADRs / design docs.
