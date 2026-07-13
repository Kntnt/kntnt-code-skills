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
- `--level=XS|S|M|L|XL` — the single **ambition dial**, default `M`. It sets how much model and reasoning effort every sub-agent gets: the orchestrator derives a per-role `(model, effort)` from the level (see *Model and effort*), sliding from a quick, cheap posture at `XS` to a strongest-tier, most-thorough posture at `XL`. This is the one knob for "how hard to try" — you set the ambition, and the model and effort of the judgment, implementer, and mechanical roles all follow from it, rather than every agent inheriting the session tier. Omit it (or omit the resolution entirely, as an older plan does) and every agent simply inherits the session model.
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

The plan also carries a `merge_required` flag (with a human-readable `merge_note`): it is `true` whenever the in-scope graph has any cross-issue edge. Treat it as the cue for the merge-vs-PR decision below — when it is `true`, set the engine's `merge` arg (step 4) so dependents build on a base that already contains their prerequisites, rather than branching off bare `main`. The conservative one-PR-per-issue default is safe only when `merge_required` is `false`. This is now **enforced**, not merely advised: in PR mode the engine merges nothing, so a prerequisite that only opened a pull request is not on any dependent's base — the engine therefore **parks** each dependent that has an in-scope prerequisite (with a reason that names it and points at `--merge`) instead of building it on an incomplete base, and the skip cascades transitively. So a dependency chain launched in PR mode parks its dependents by design; run it under `--merge` (or after the prerequisites' PRs merge) to build the whole chain.

### 3. Confirm (single gate)

Show the plan from step 2 — scope, graph, waves, and whether the run will merge or open pull requests — and wait for one confirmation. `--yes`, or a `--plan` you have already reviewed, skips it. Beyond this gate the run does not stop, with one exception: integrating into the default branch happens only under `--merge` or an explicit project authorization; otherwise the work lands as pull requests.

#### Cost and chunking

Size the run before you confirm it — present an **agent and token estimate** at the gate, not just a list of issues. Under the lean defaults — a **single** broad adversarial reviewer and one fix round — an issue that needs no fix costs `1 implement + 1 verify (one broad lens) + 1 integrate` = **3 sub-agents**; an issue that takes its one fix round costs `1 implement + 1 verify + 1 fix + 1 targeted re-verify + 1 integrate` = **5 sub-agents** — the targeted re-verify is a real agent the engine always dispatches after a fix, so the honest worst case is **5, not 4**. That is **3–5 sub-agents per issue**, ≈ 4 on average. Add a once-per-run overhead: **≈ 2** in the default PR mode (the mandatory integration review + the worktree teardown), rising to **≈ 5** in merge mode when a finding drives a hotfix (integration review + hotfix + its land + re-review + teardown). A **typical** closed form to compute at the gate — `N` is the issue count, and `4` is the average per-issue cost, folding the default panel size 1 × fix rounds 1 over implement / verify / (fix + re-verify) / integrate:

```text
agents ≈ N × 4 + 3        (typical; per issue 3–5, per-run overhead ≈2 in PR mode, up to ≈5 in merge mode)
```

That matches the engine's lean defaults — one broad reviewer, one fix round — not the heavier multi-lens, multi-round panel it replaced. The `× 4` per issue holds only while every issue keeps the default one-lens panel; where planning raised a genuinely high-risk issue above one lens, add that issue's extra `lenses` (each extra lens is one more verify sub-agent) on top of its 4. Translate to tokens so the reader sees the real cost, not just an agent count: each implement, verify, fix, or re-verify sub-agent runs at the strong tier and spends on the **order of tens of thousands to low hundreds of thousands of tokens**, so a 30-issue run — `30 × 4 + 3 ≈ 123` sub-agents — is on the order of millions of tokens, easily enough to hit a monthly cap mid-run.

Because each green issue integrates the moment it is verified (step 4), a stopped run keeps every issue already landed — on the default branch under `--merge`, or as an already-opened per-issue **PR** in the conservative default mode. Exploit that: run a large backlog in **slices of 8–10 issues at a time**, not one unbounded run, so a spend cut-off loses at most the current slice rather than the whole batch — this pairs with the per-issue incremental landing that already makes each green issue durable.

For any run above **~10 issues**, do not pass this gate unbounded: **require an explicit cap** before proceeding. The real levers are `budgetFloor` — an engine `args` knob (default 60000 tokens; see step 4) that stops opening new work once the run's remaining token budget falls below it — the run's own token budget (`budget.total`, set by the session's token target, which `budgetFloor` is measured against), a lower `maxFixRounds`, and **slicing** the batch into fewer issues per run. Set at least one of these and state it in the confirmation. A large run without a cap must not be confirmed; that bound is what the confirm gate exists to enforce for a big batch.

### 4. Build (engine)

**Preferred — the Workflow tool.** Launch `skills/orchestrate/orchestrate.workflow.js` with the plan JSON (plus `merge`, `maxFixRounds`, `maxIntegrationRounds`, `budgetFloor`, the per-role `(model, effort)` resolution `roles` the `--level` dial produced during planning — see *Model and effort* — and each issue's risk-scaled verifier panel `lenses`, set during planning) as `args`. `maxIntegrationRounds` is the cap on the mandatory integration review's hotfix loop (step 5), an `args` knob that defaults to `maxFixRounds` (itself 1) so the integration stage is bounded exactly as a per-issue fix loop is. `roles` carries the `{ judgment, implementer, mechanical }` tuning the engine spreads into every sub-agent's dispatch (see *Model and effort*); omit it — as an older plan does — and every agent inherits the session model, so a launch that drops it silently reverts the whole run to the session tier. The control flow — wave order, the capped fix↔verify loop, and per-issue serial dispatch that integrates each green issue the moment it is verified (so a mid-run stop leaves every prior issue durably on the default branch) — is code there, so it cannot drift over a long unattended run. It honours wave **outcome**, not just wave order: before building an issue the engine checks that every in-scope prerequisite actually **landed** on the base the dependent builds from, and if one did not it **skips (parks) the dependent with a reason naming the unlanded prerequisite** rather than build it on a base missing that work — and because a skipped issue never lands, the skip **cascades** to its own dependents transitively. A prerequisite counts as landed only when the run put it on that base: in **merge** mode when it integrated, but in the conservative **PR** mode NOTHING merges, so an in-scope prerequisite is only an open pull request and its dependent is parked (the reason points at `--merge`) — the same enforcement `merge_required` warns about, now applied by the engine rather than left to advice. Beyond that, agents run in the subscription pool; worktree isolation keeps concurrent agents apart; the run is budget-bounded — `budgetFloor` (an `args` knob, default 60000 tokens) stops the engine opening new work once the remaining token budget drops below it, the settable cap the confirm gate requires for a large run — and resumable via its `runId`.

**Fallback — the Agent tool.** Where the Workflow tool is unavailable (some Cowork / portable contexts), drive the same lifecycle from this session with the Agent tool, still calling `orchestrate.py` for the plan and the report. Use `/goal` for the outer loop (see below).

Either way the per-issue lifecycle is the same:

1. **Implement.** One implementer sub-agent on its own branch reads the **agent brief** (the contract, or — when no brief was posted — the issue body and its acceptance criteria) and the standard, implements **test-first** (red/green/refactor) at the layer the test strategy prescribes, **demonstrates the red** (a failing-test commit before the green one), runs the project's gates, reports their real results, and returns the three-bucket report.
2. **Verify, independently.** Only after green, a fresh verifier that did **not** write the code reviews **only what the gates cannot**. By default this is a **single broad adversarial reviewer** whose one lens folds every concern together — correctness against the brief's intent and acceptance criteria, test quality (is the red demonstrated? do the tests bind? does every criterion map to a test?), and any security or data-safety hazard the issue touches. Raise the panel to **2–3 focused lenses only for a genuinely high-risk issue** — a write path, a permission gate, a filesystem boundary, an irreversible delete — via the per-issue `lenses` set during planning. Use the project's specialized review agents where they exist; diverse lenses catch what identical reviewers miss, but only pay for them where the risk earns them.
3. **Decide.** Read only the verdicts — never the diffs yourself. All clear → integrate. Any real finding → return it to the same implementer to fix, then **re-verify only the fixed findings** with a single targeted reviewer — not the whole panel again — capped at `--max-fix-rounds` (default 1); if it still fails, park that issue and continue.
4. **Integrate, immediately.** Land each green issue the moment it is verified, before the next issue's work begins, in dependency order. Keep history linear: fast-forward the *default* branch to the feature branch's tip (`git merge --ff-only <feature>` from the default branch) — never merge the default branch into the feature branch, never create a merge commit there. Crucially, the feature branch is still checked out in its implementer's (or fix round's) persisted worktree, and git refuses one branch in two worktrees at once, so integrate advances the default *without ever checking out the feature branch*; with the serial integrate-immediately design the feature branch is already a fast-forward ahead of the default, so no rebase replay is needed. Landing per-issue makes partial progress durable: a stop between issues leaves every already-integrated issue on the default branch. Under the conservative default, open a pull request instead and leave the merge to the maintainer.

### 5. Finalize

Re-run the full gate suite over the merged whole — green on each issue does not guarantee green on the union. Then the engine runs a **mandatory** adversarial integration review over the real combined change set of the run: one reviewer given a per-issue verifier's full rigor (never a token smoke test), hunting the cross-issue defects no per-issue lens can see — one issue's change silently weakening another's guarantee, a contradiction between two changes, a broken invariant across their union. It **always runs** whenever the run integrated at least one issue, and it is **mode-aware**: in merge mode it reviews the combined diff now on the default branch; in the conservative PR mode nothing landed on the default branch, so it reviews the **union of the run's feature branches** against the default branch (reviewing the default branch there would see nothing and falsely clear). Its clear decision goes through the same block-unless-explicitly-cleared rule a per-issue verdict does. In **merge mode** it can **fix, not merely report**: a real finding drives a **bounded hotfix + re-review** — a code-touching agent on its own worktree creates a fresh hotfix branch off the up-to-date default branch, addresses only those findings, lands through the same linear fast-forward step, and the combined diff is re-reviewed — capped by `maxIntegrationRounds` (an engine `args` knob defaulting to `maxFixRounds`, i.e. 1), like a per-issue fix loop. In **PR mode** the review still always runs, but a finding is **reported (parked with its specifics) for the human** rather than auto-hotfixed, matching the leave-the-merge-to-you posture. A finding is never silently cleared or dropped in either mode. Then fold the run's records into one report. The engine returns `{ verdicts, parked, integration }`, but `report` consumes a **single flat JSON array** that it partitions by each record's `status`, so its input is the **concatenation of `verdicts` and `parked`**, not `verdicts` alone — piping only the field literally named `verdicts` would silently drop every parked or blocked issue, and the parked integration-review finding, from the final report:

```bash
uv run "${CLAUDE_PLUGIN_ROOT}/scripts/orchestrate.py" report < verdicts.json
```

Here `verdicts.json` is that concatenated `verdicts` + `parked` array. Surface the `integration` review outcome too: when it **cleared**, that positive fact lives only in the returned `integration` field and the engine log, so state it explicitly in what you report; when it did not clear, its finding is already parked (and thus already in the concatenated array), so it renders under the parked issues — do not drop it either way. It leads with what is done and green, then the de-duplicated *Remaining for a human* list, then *Assumptions* and the parked or blocked issues. Do not bump the version, tag, or publish — when the merged work is ready to ship, that is the `release` skill.

#### Confirming closures

The orchestrator closes each verified-and-integrated issue itself (never a sub-agent), and confirms each close **individually**: verify a closure by querying that issue's own state with `gh issue view <n>` (read its `state` / `closed` field), and count the issue as closed only when its own record says so.

Do not confirm closures by re-running `gh issue list` — GitHub's issue-list endpoint is eventually consistent and reads **stale** immediately after a close, so a just-closed issue can still show as open in the list even though its own `gh issue view` already reports it closed; the report/closing step counts a close only against that individual `gh issue view <n>` state, never against the list re-query.

#### Pruning the run's scaffolding branches

Leave the repository state-neutral: prune this run's own leftover worktree scaffolding branches as the last finalize act. The Workflow harness names each per-worktree scaffolding branch `worktree-<runId>-<n>`, and once an agent checks out its own feature branch that ref is orphaned — #14's teardown removes the worktrees and preserves every feature-branch ref, but leaves these now-orphaned scaffolding branches behind to accumulate across runs. Because they are order-independent of the report and the closures (nothing there reads a branch ref), pruning them fits equally before or after those steps; do it once the engine has returned and the worktrees are already torn down. You know the run's `runId` from the Workflow launch, so delete **only** the branches matching this run's own `worktree-<runId>-*` prefix — `git branch --list "worktree-<runId>-*"` to list them, then `git branch -D` each. Belt-and-braces before you build that glob: verify the `runId` you captured from the launch is non-empty and substitutes into the pattern verbatim — an empty or partial value degenerates `worktree-<runId>-*` into `worktree--*` or a bare `worktree-*` that matches **every** run's scaffolding, including a concurrent same-repo run's, so if the `runId` is missing or unresolved, **skip the prune entirely** rather than run a delete on a loose glob (this force-delete's confinement holds only while the substituted prefix is genuinely run-scoped). Confine the match to the exact `runId`: **never** delete a feature branch, an integration-hotfix branch, or any branch outside that run-scoped prefix, and never touch another run's scaffolding. This is the one authorised branch delete the orchestrator makes — the sub-agents and the worktree teardown are forbidden any — and it changes nothing about #14's worktree teardown or its preservation of every feature-branch ref.

## Model and effort

Model and reasoning effort are not set per agent by hand — they are **derived from the `--level` dial**. The **orchestrator** (the session-model planning pass) turns the level into a **per-role `(model, effort)`** and hands it to the engine as `args.roles`; the engine stores no model-name table and only applies what it is given (spreading it into each sub-agent's dispatch), so a role that carries no resolution — or an older plan with no `roles` at all — simply inherits the session model. Put the strong model and the high effort where the judgement is, not where the routing is — and let the level decide how strong.

**Three role classes carry the tuning**, with the hierarchy `reviewer ≥ implementer ≥ mechanical`:

- **Judgment** — the one-time planning judgement and the **adversarial verifier**: the single broad reviewer that runs by default, the extra lenses a high-risk issue adds, and the mandatory integration review. The strongest tier the level allows — this is where real bugs are caught.
- **Implementer** — the code-writing agents (implement, its fix round, the integration hotfix). Its model **slides with the level**: a cheaper executor of a detailed plan at the low end, rising to meet the reviewer at `L`/`XL`, where it is the primary thinker.
- **Mechanical leaves** — integrate and the worktree teardown. The cheapest tier; they gain nothing from a stronger model.

**The mapping is derived at runtime, not hardcoded.** What is fixed is the set of levels and their semantic intent per role; the concrete `(model, effort)` is resolved by the orchestrator **against the harness's live model list** at plan time, so it self-updates as models change (a new Opus, Fable's successor) with no literal model-name table stored as the durable contract. The ladder below is what that derivation produces *today* — an **illustrative, non-durable** instantiation (as of 2026-07), refreshed as models change, never a promise:

| Level | Judgment (planning + review) | Implementer | Mechanical |
| ----- | ---------------------------- | ----------- | ---------- |
| **XS** | Sonnet · high | Haiku · thinking | Haiku · thinking |
| **S** | Sonnet · xhigh | Sonnet · high | Haiku · thinking |
| **M** | Opus · high | Sonnet · xhigh | Sonnet · high |
| **L** | Opus · xhigh | Opus · xhigh | Sonnet · high |
| **XL** | Fable · xhigh | Fable · xhigh | Sonnet · high |

Effort maps to the harness ladder `low < medium < high < xhigh < max`; the ladder's `thinking` (the XS/S mechanical and low-end implementer tiers) is **not** a rung on that scale but shorthand for **Haiku with light extended thinking** (ADR-0001 §4), so it does not contradict the effort scale above. Two **guardrails** bound this runtime derivation:

- **Only dispatchable models.** The resolution may pick only a model the harness can actually **dispatch**; an intent that would land on an unavailable model falls back to the nearest available tier rather than failing the run.
- **Judgment never below the session tier.** The judgment roles (planning + the adversarial reviewer) never resolve *below* the session model's tier — the reviewer is the last line of defence and is not silently cheapened — **unless** the maintainer explicitly dialed down with a low `--level`.

The spine itself stays **code, not an LLM**, so there is no expensive "orchestrator LLM" doing routing: the deterministic work — is the graph acyclic (`orchestrate.py plan`), did the gates exit green, is there a red-before-green commit (`orchestrate.py redgreen`), does each criterion map to a test — belongs to the helper and the gate run (CPU, not tokens), never to a sub-agent reading text by eye. The orchestrator only reads verdicts and routes; the judgement lives in the verifier and implementer sub-agents, and that — scaled by the level — is where the tier and the effort go.

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
