# 2. Implementation-planning pass and the sliding implementer for `/orchestrate`

- **Status:** Accepted
- **Date:** 2026-07-13
- **Deciders:** Thomas Barregren

> **Refreshed by [ADR-0004](0004-rework-the-level-ladder.md).** The illustrative per-level model tiers this ADR cites in passing (e.g. §3's "`XS` → Haiku, `S` → Sonnet") are superseded by ADR-0004's re-pitched ladder; the *mechanism* this ADR decides — the `implementerMode` framing, the inversely-scaled per-issue implementation-plan overlay, and their `args` surface — is unchanged.

## Context

ADR-0001 settled the control model for `/orchestrate` and fixed, in §3, the *intent* of two coupled ideas but not their mechanism: the **sliding implementer** (its mode slides from a mechanical executor of a pre-settled plan at the low end of the `--level` dial to an autonomous problem-solver at the high end) and a **per-issue implementation-planning pass** (an LLM judgment pass whose weight scales inversely with the level — heavy at `XS`, ≈ nothing at `XL`), kept distinct from the deterministic graph planner. The engine has no such pass today: its `implement` sub-agent fetches the issue's contract itself and goes straight to code. This ADR settles the mechanism so the build work can proceed test-first.

It rests on a boundary ADR-0001 already established and which this ADR names explicitly: **the orchestrator's one-time planning judgment produces per-issue and per-run signals and hands them to the deterministic engine through `args`; the engine applies them mechanically.** Model/effort per role (issue #25) and verification rigor — the verifier lenses and the fix-round cap (issue #26) — already cross this boundary. The implementation plan is the newest passenger on it. The model-derivation-location decision recorded in #25 — that the orchestrator, not the engine, resolves each role's `(model, effort)` because the engine cannot enumerate the live model list — is one instance of this same pattern; it is cross-referenced here, not re-decided.

The bearing principle from ADR-0001 is unchanged and constrains every decision below: **the spine is code, the judgment is the LLM.** The deterministic graph planner (`orchestrate.py plan`) stays code with no model tier; the orchestrator never writes production code or reads diffs; the engine stays a deterministic Workflow script whose only runtime globals are `agent`/`parallel`/`log`/`budget`/`args`.

## Decision

### 1. The pass runs in the orchestrator's planning judgment — not the engine, not `orchestrate.py`

The per-issue implementation-planning pass is **an extension of the one-time planning judgment the orchestrator already runs** on the session model — the same pass that reads each brief to set the issue's risk and verifier panel. It is **not** a new engine sub-agent (which would add one agent and its tokens per issue and move judgment into the deterministic spine) and **not** an `orchestrate.py` step (implementation planning is judgment, not deterministic bookkeeping). For each in-scope issue the orchestrator produces the plan once, up front, and passes it to the engine as a per-issue `args` field; the engine interpolates it into the `implement` prompt.

The cost this accepts: an up-front plan for a *dependent* issue is written before its prerequisite integrates, so it can be mildly stale against the base the dependent finally builds on. This is accepted because the plan is **behavioral** ("what to build, and — at the low end — how"), the `implement` agent still reads the live code, and the alternative (a just-in-time engine planning agent on the live base) costs an extra agent per issue and pushes judgment into the spine.

### 2. The plan is an additive "how" overlay; the brief stays the authoritative "what"

The plan **never replaces** the issue's contract. The Agent Brief — or, when none was posted, the issue body and its acceptance criteria — remains the single authoritative source of *what* to build, exactly as ADR-0001 and the engine's `no_brief` fallback already define. The plan is level-scaled guidance on *how*, layered on top. The `implement` agent reads **both**: it fetches the contract as it does today (unchanged `gh issue view --comments` plus the `no_brief` fallback) and receives the plan as additional guidance in its prompt.

The invariant this locks: **the tests bind to the acceptance criteria, never to the plan.** The plan cannot silently drift the work away from the criteria, and a run that carries no plan (see §3's `XL`, a hand-launched engine run, or any absent plan field) degrades to exactly today's behavior — no regression.

### 3. Plan detail is three level-banded templates, skipped at `XL`

The plan's *shape* is a function of the run-wide `--level` alone, uniform across the run's issues. Per-issue **risk does not affect it** — risk escalates verification rigor (issue #26), never plan detail; the separation is deliberate.

| Level | Plan the orchestrator produces |
| ----- | ------------------------------ |
| **XS / S** | **Recipe / decomposition** — ordered steps, which tests to write first, the tricky parts spelled out, so a cheap implementer executes it mechanically. |
| **M** | **Balanced spec** — what to build, how the acceptance criteria map to tests, and the non-obvious decisions called out; the routine "how" is left to a capable implementer. |
| **L** | **Goals + constraints + risks** — the objective, the invariants to respect, the known hazards; minimal "how." |
| **XL** | **No plan** — the field is omitted; the implementer reasons autonomously from the brief and its tests. |

The `XS`-vs-`S` difference within the first band is carried by the implementer's **model** (issue #25: `XS` → Haiku, `S` → Sonnet) and by the framing (§4), not by a distinct template — matching ADR-0001 §4's three planning-output forms. "Weight scales inversely with the level" is realized as the orchestrator emitting progressively less prescriptive plan text as the level climbs, to nothing at `XL`.

### 4. The mode framing lives in the engine, keyed by a run-level `implementerMode` marker

How the `implement` agent is told to *treat* the plan — mechanical execution vs autonomous reasoning — is fixed prompt scaffolding, so it lives **in the engine**, the way `DEFAULT_LENSES` and `AGENT_CONSTRAINTS` already do: three templates keyed by a run-level marker `implementerMode ∈ { execute, balanced, autonomous }`. The orchestrator passes the marker and the plan *content*; the engine selects the framing and interpolates the plan. Band mapping: `XS, S → execute` · `M → balanced` · `L, XL → autonomous` (`L` carries a goals+constraints plan to respect, `XL` carries none, but both take the autonomous stance).

- **execute** — "This plan is the settled *how*. Follow it test-first. Deviate only if it is demonstrably wrong, and record why. Do not re-derive the approach."
- **balanced** — "Follow the spec's shape, fill in the routine *how* yourself, and respect the decisions it calls out."
- **autonomous** — "Here are the goals and constraints (or, at `XL`, the brief). Reason out the *how* yourself, test-first; the tests are your guide. You own the approach."

The marker is **explicit**, not inferred from whether a plan string is present: a thin `M` plan and an `L` plan are not distinguishable by presence alone, and an explicit marker is unambiguous and structurally testable. Because the framing is fixed engine text, the build can assert — via the existing `_agent_block` structural pattern — that each mode selects its own framing.

The plan and the framing apply to `implement` **only**. `fix` and `integrationHotfix` keep their current finding-driven prompts unchanged: the mode's whole effect (execute-a-recipe vs reason-from-goals) is spent during the initial implementation, `fix` is targeted at specific findings regardless of mode, and `integrationHotfix` is cross-issue so no single issue's plan applies.

### 5. The `args` surface

Two additions, both consistent with how issue #25's `roles` and issue #26's `lenses`/`maxFixRounds` already flow across the planning→engine boundary:

- **`issues[].plan`** — a per-issue plan string (the §3 content). Absent at `XL`, and absent from any plan produced before this change or by a hand-launched run — in which case `implement` behaves as today.
- **`implementerMode`** — a run-level marker (§4). Absent → the engine adds no mode framing (today's behavior).

## Consequences

**Positive.** The sliding implementer becomes real: at `XS` a cheap model executes a detailed recipe (cheap because execution is the token volume and the recipe makes it mechanical); at `XL` a strong model reasons autonomously from the brief; `M` is the balanced middle. The mechanism costs **zero extra sub-agents per issue** — the plan is produced inside the planning judgment that already runs, and consumed by the `implement` agent that already runs. The engine's control flow is unchanged in shape; it gains only a plan interpolation and a framing selection, both structurally testable.

**Consciously accepted costs.**

- **Up-front plan staleness** for dependents (§1) — bounded by the plan being behavioral and the implementer reading the live code.
- **A new judgment output**, but folded into the existing one-time planning pass rather than a new engine role, so "the spine is code" holds and the per-issue agent count does not grow.
- **The plan is ephemeral** — it lives in `args` for the run, is not committed to the repository, and is not part of the durable contract (the brief and its acceptance criteria are).

**Invariants preserved.** The deterministic graph planner (`orchestrate.py plan`) is untouched in role and keeps no model tier. The orchestrator still never writes production code or reads diffs — it authors guidance, not code. The brief and its acceptance criteria remain the authoritative contract, and the `no_brief` fallback is intact. The engine stays a deterministic Workflow script.

**Out of scope / unchanged.** Model/effort per role (#25) and verification rigor (#26) are their own tickets; this ADR only names the boundary they share with the plan. The `--yes`/merge-authority separation (#28) and the SKILL.md reconciliation (#30) are unaffected.

**Follow-up (implementation handoff).** Build issue #29 implements this: the engine interpolates `issues[].plan` into the `implement` prompt and selects the `implementerMode` framing from three fixed templates, leaves `fix` and `integrationHotfix` unchanged, and degrades cleanly when either field is absent; SKILL.md documents the orchestrator's per-level plan-authoring instruction and the two new `args` fields. It is verified structurally (`tests/test_orchestrate_workflow.py`, via `_agent_block`: the three framings exist and are mode-selected, `implement` interpolates the plan, `fix`/`integrationHotfix` are untouched, and the no-plan path adds no framing), with any extracted pure helper mirrored in `lib/orchestrate/engine-helpers.mjs` and drift-guarded. The SKILL.md control-surface reconciliation (#30) then folds the plan and mode into §Model-and-effort and the decision-boundary map.
