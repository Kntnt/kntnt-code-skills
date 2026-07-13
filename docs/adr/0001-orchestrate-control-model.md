# 1. Control model for `/orchestrate`

- **Status:** Accepted
- **Date:** 2026-07-13
- **Deciders:** Thomas Barregren

## Context

`/orchestrate` shipped working in v0.10.0, but the first real runs were slow and expensive for three reasons: (a) the engine set no model or effort per agent — everything inherited the session model, so even purely mechanical agents ran on the strongest tier; (b) rigor was uniform regardless of a change's size or risk — a one-line change got the same heavy pipeline (test-first + independent reviewer + fix round + integration review) as a complex logic change; (c) it ran mostly sequentially.

This ADR settles the **control model**: who decides what, at which level, and how the maintainer influences it from outside — i.e. the autonomy boundaries and the external control surface. It does not prescribe code structure.

The bearing principle: **defaults are automatic (role → model/effort; risk → rigor); human input is the exception (a policy once per project + a single decision at the run gate + an optional per-issue signal), never a per-issue checklist.** The more the maintainer must specify per issue, the more the away-from-keyboard promise leaks.

## Decision

### 1. One ambition dial, nothing else

Control collapses to a **single semantic ambition dial** with a fixed, model-agnostic vocabulary — t-shirt sizes `XS | S | M | L | XL`, default **M**. There are **no** model-floor/ceiling, effort-floor/ceiling, or separate rigor knobs; they all fold into the level. The only orthogonal knob is the **budget cap**, because it is a resource bound, not a quality posture.

The dial carries **both** model/effort **and** the rigor baseline — one spectrum from "quick and dirty" to "extremely well thought out."

### 2. The level is derived, not hardcoded

What is **fixed** is the set of levels and their **semantic intent** per role. What is **derived at runtime** is the concrete `(model, effort)` per role: the engine resolves the intent against the harness's live model list, so the mapping self-updates as models change (new Opus, Fable's successor). No literal model names are stored as the contract. This accepts a degree of run-to-run non-determinism as the price of never hardcoding; two guardrails contain it — the engine may only pick models the harness can actually dispatch, and judgment roles never drop below the session model tier unless the maintainer explicitly dialed down.

The **rigor baselines** below are model-agnostic integers and therefore *are* fixed.

### 3. Roles and the sliding implementer

Three token-consuming role classes, plus deterministic scaffolding:

- **Judgment** — one-time planning judgment *and* the adversarial reviewer. Strongest tier.
- **Implementer** — its **mode slides** with the level: a mechanical executor of a plan at the low end, an autonomous problem-solver at the high end.
- **Mechanical leaves** — formatting, integrate, teardown. Cheapest; capped (gains nothing from a stronger model).

The load-bearing insight: **the irreducible thinking migrates from the plan to the implementer as the level climbs.** At the low end the planning phase pre-settles the "how" (a detailed decomposition ≈ recipe) so a cheap implementer can execute it mechanically — cheap because execution is the token volume and a good plan makes it mechanical. At the high end the planner sets goals + constraints only and a strong implementer reasons out the "how" in situ, with tests as the guide. `M` is the balanced middle that solves most tasks fast and well. This is why the same task is *not* served by pairing a detailed recipe with a strong autonomous implementer — that wastes the model and invites spec-drift.

Consequently the implementer's **model** slides down at the low end (it is mechanical, so Haiku executing a plan is viable where Haiku reasoning from a goal is not) and rises to meet the reviewer at the top (it is the primary thinker, so it earns the top tier). The **hierarchy** is therefore `reviewer ≥ implementer ≥ mechanical`, with the gap widest at the bottom and closing to equality at `L`/`XL`.

Two things stay distinct from the judgment role: the **orchestration planner** (dependency graph, waves, risk — deterministic **code**, no model tier) and the **per-issue implementation-planning** pass (an LLM judgment pass whose weight scales *inversely* with the level — heavy at `XS`, ≈ nothing at `XL`).

### 4. Model/effort ladder (illustrative instantiation as of 2026-07)

This concrete table is **not** part of the durable contract — it is what the derivation (§2) produces today and is refreshed as models change. Effort maps to the harness ladder `low < medium < high < xhigh < max`; here **High** = `high`, **Extra** = `xhigh`, **Thinking** = Haiku with light extended thinking.

| Level | Judgment (planning + review) | Implementer — *mode* | Mechanical |
| ----- | ---------------------------- | -------------------- | ---------- |
| **XS** | Sonnet · High | Haiku · Thinking — *executes plan* | Haiku · Thinking |
| **S** | Sonnet · Extra | Sonnet · High — *mostly executes* | Haiku · Thinking |
| **M** | Opus · High | Sonnet · Extra — *capable, balanced* | Sonnet · High |
| **L** | Opus · Extra | Opus · Extra — *reasons* | Sonnet · High |
| **XL** | Fable · Extra | Fable · Extra — *reasons autonomously* | Sonnet · High |

The judgment column's **planning output** slides inversely: recipe/decomposition at `XS`/`S` → balanced spec at `M` → goals + constraints at `L`/`XL`.

### 5. Rigor baseline (fixed, model-agnostic) — coupled to the dial, risk escalates per issue

The ambition dial sets the rigor baseline; per-issue **risk** escalates it on top; an **inviolable floor** always holds.

| Level | Lenses (verify) | Fix rounds | Integration review (always runs) |
| ----- | --------------- | ---------- | -------------------------------- |
| **XS** | 1 broad: C+T+S | 1 | PR: report-only · merge: 1 hotfix |
| **S** | 1 broad: C+T+S | 1 | PR: report-only · merge: 1 hotfix |
| **M** | 1 broad: C+T+S | 1 | PR: report-only · merge: 1 hotfix |
| **L** | 2: [C+T] + [S]\* | 2 | PR: report-only · merge: 2 hotfix |
| **XL** | 3: C · T · S | 2 | PR: report-only · merge: 2 hotfix |

A **lens** is one independent verifier sub-agent with a review focus (one sub-agent per lens). `C` = correctness/spec, `T` = test-quality, `S` = security/data-safety. \*`L`'s second lens is planner-tailored — `T` when the issue has no security surface.

- **Inviolable floor** (holds even at `XS`, even under `--yes`): ≥ 1 independent adversarial lens per issue, red-before-green required, the mandatory integration review runs whenever ≥ 1 issue integrated. Rigor can never reach zero.
- **Fix-round floor is 1**, not 0: the fix loop is the cheapest, highest-leverage step (the implementer holds the context, the reviewer specified the defect), so an issue is always repaired at least once rather than parked for a human. `0` fix rounds is reachable only via an explicit `--max-fix-rounds=0` for a scan/triage run; no level defaults to it.
- **Report-only vs hotfix** is determined by **mode**: PR mode is always report-only (nothing landed on the default branch → no integrated artifact to fix; a cross-issue defect between two separate PRs cannot be fixed on either branch alone), merge mode is hotfix-capable. The **level** sets how many hotfix rounds in merge mode.

### 6. Risk determination

Hybrid: **LLM inference is the default** (the planner reads the brief at plan time); an explicit human signal overrides.

- **Channel:** the issue body is the **primary** channel — a light `Risk: high | medium | low` marker in the Agent Brief (read deterministically when present), with free prose still feeding inference. This needs no repository setup and works even in the no-pipeline fallback. A `risk:*` **label** is an optional convenience (board visibility / filtering), never required.
- **Precedence — escalate-only:** risk = the **highest** signal across channels. An explicit **high** signal is a floor the planner may exceed but never undercut. An explicit **low** signal is advisory: it may pull an inference-driven escalation back to the baseline, but never below the inviolable floor, and never silently if the planner still sees a hazard (the disagreement is reported).
- **Round up on uncertainty.** In AFK the cost of over-rigor is money; the cost of under-rigor is a bug merged unwatched. Asymmetric costs → asymmetric default.

### 7. Full-auto contract (`--yes`)

`--yes` means **"yes to the single pre-run confirmation gate," and nothing more.** It does **not** grant authority to write to the default branch. Merge-vs-PR is a **policy** decided before the gate, not something `--yes` toggles.

- **Plugin default = PR** (conservative, matches common practice for others).
- **Merge authority** is an explicit grant: per-run `--merge`, **or** a once-per-project (or global) policy. On a repo whose policy makes merge the default, `--yes` alone is full walk-away straight to `main` — no PRs, and the feature branches are ephemeral internal isolation scaffolding that fast-forward-land and self-prune.

**Decided autonomously** (with or without `--yes`): scope resolution; model/effort per role; rigor baseline + per-issue risk escalation; which lenses to spend; assumptions on genuine ambiguity (recorded and reported, never a silent guess, never a pause); the fix loop up to the level's cap; opening PRs; the integration review + (merge) bounded hotfix; the run-scoped scaffolding-branch prune; per-issue implementation-planning granularity.

**Inviolable safety floor** (holds even under `--yes --merge`):

- Never force-push; a push that would require force is refused and reported.
- Never merge to the default branch without `--merge` / policy (PR mode merges nothing).
- Close an issue only after independent verification **and** integration, confirmed individually via `gh issue view`; PR mode leaves issues open.
- The rigor floor (§5) is always on.
- The budget bound is always on (`budgetFloor` + the session token target): a large batch does as much as the budget allows and reports the remainder — full-auto is never truly unbounded.
- Never override an ADR / design blocker — park and report.
- Never bump, tag, or release.
- The branch prune is confined to `worktree-<runId>-*`; skip it entirely if `runId` is unresolved.

### 8. The decision-boundary map

Almost every decision is **silent** (autonomous). Only three surface at the single gate: **merge authority, the cost cap, and the go/no-go**. Per-issue human input (the `Risk:` marker) is **optional**, never required.

| Decision | Who decides | External lever |
| -------- | ----------- | -------------- |
| Scope | Silent (default `ready-for-agent`, excl. `ready-for-human`) | scope argument |
| Model/effort per role | Silent (derived from `--level`) | `--level` |
| Rigor baseline | Silent (from `--level`) | `--level` |
| Per-issue risk → escalation | Silent (inferred, escalate-only) | `Risk:` marker / label |
| Which lenses | Silent (level + risk, planner-tailored) | indirect |
| Fix / hotfix rounds | Silent (from level) | `--max-fix-rounds` |
| Merge vs PR | **Confirmed at gate** (shown in plan) | `--merge` / project policy |
| Cost cap (required > ~10 issues) | **Confirmed at gate** | budget target / `budgetFloor` |
| Whether to run | **Confirmed at gate** | `--yes` waives it |
| Push feature branch / default | Silent (default only under merge authority) | merge authority |
| Close issue | Silent (only after verify + integrate) | floor, not overridable |
| Escalate risky issue | Silent (never silently downgrade) | `Risk:` raises the floor |
| Design blocker | Silent — park + report, never override ADR | floor |
| Scaffolding-branch prune | Silent (run-scoped) | floor |
| Bump / tag / release | **Never** — out of scope | `release` skill |

## Consequences

**Positive.** A single dial (`--level`, default `M`) expresses ambition; everything else is automatic. Cheap tiers and lean rigor at the low end, strong reasoning and multi-lens rigor at the high end, without per-issue fiddling. The maintainer can `--yes --merge` (or set merge as a project default and just `--yes`) and walk away, with a well-defined safety floor. The solo-on-`main` workflow is served exactly — merge default gives no PRs and no lingering branches.

**Consciously accepted costs.**

- **Runtime non-determinism** in model selection (§2) — the price of never hardcoding model names; bounded by the two guardrails.
- **A new per-issue implementation-planning role** (§3) — a real added judgment pass, but one whose weight scales inversely with the level; kept distinct from the deterministic graph planner so "the spine is code" still holds.
- **The hierarchy was relaxed** so the implementer meets the reviewer at `L`/`XL` (rather than always sitting one notch below), reflecting that the implementer is the primary thinker there.
- **`0` fix rounds is no longer a level default** — the fix-round floor is 1.

**Out of scope / unchanged.** Release (bump/tag/platform) stays with the `release` skill. Design decisions are parked, never overridden. The orchestrator still never writes code or reads diffs itself.

**Follow-up (implementation handoff).** This ADR changes the control surface described in `skills/orchestrate/SKILL.md` (§Arguments, §Model and effort): it adds the `--level` dial; makes model/effort and the rigor baseline derived from the level; turns per-issue lenses and fix rounds into functions of level + risk rather than a manually set per-issue arg; adds the `Risk:` brief marker and the escalate-only precedence; and pins the `--yes` / merge-authority separation. The SKILL.md and the engine defaults should be reconciled with this ADR when it is implemented.
