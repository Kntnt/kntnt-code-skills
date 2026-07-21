# 4. Rework the `--level` ladder (rigor saturates at M) and add verifier fix-direction suggestions

- **Status:** Accepted
- **Date:** 2026-07-21
- **Deciders:** Thomas Barregren

> **Amends [ADR-0001](0001-orchestrate-control-model.md) §4 and §5, and refreshes [ADR-0002](0002-implementation-planning-and-sliding-implementer.md) §4's illustrative model tiers.** The rigor floor (ADR-0001 §5), the escalate-only risk model (§6), the `--yes`/merge-authority separation (§7/§8), the `--max-lenses`/`--pr` decoupling (ADR-0003), and the sliding-implementer *mechanism* (ADR-0002 — `implementerMode`, the per-issue plan overlay) are all unchanged in substance.

## Context

`/orchestrate` shipped its control model in ADR-0001 (the `--level` dial carrying both model/effort and a rigor baseline) and refined it in ADR-0002 (the sliding implementer) and ADR-0003 (`--max-lenses`/`--pr`). Real-world use since then exposed a mismatch between the ladder's *shape* and the maintainer's actual priority.

The observed pattern running `/orchestrate`: verifiers find many defects → many fix iterations → long wall-clock, and the default `M` level was rarely enough — practically every run had to be dialed up to `L`. The maintainer's priority for an away-from-keyboard build is **minimizing wall-clock time and human round-trips, not token cost**: an unattended run that parks work for a human to pick up later is the worst outcome, and paying more tokens up front to avoid that is a good trade.

The mechanism analysis (verified against the engine source) is what makes the fix nearly free:

- Issues run **serially** (the integrate-immediately design), so total wall-clock ≈ the sum of each issue's serial chain: implement → panel → (fix → targeted re-verify)× → integrate.
- The verifier panel runs **in parallel** (`verify()` is `parallel(lenses.map(...))`), so 3 lenses cost ≈ the same wall-clock as 1 — only more tokens.
- Fix rounds are serial (each is a fix agent plus a targeted re-verify agent). The fix-round cap is a **ceiling, not a schedule**: a clean issue runs 0 rounds regardless, so raising the cap costs nothing on the green path and converts a "parked" outcome (human re-entry) into "fixed one more round."

So the wall-clock-cheapest way to catch more defects and park fewer issues is: catch everything in the one parallel panel pass (3 lenses), prevent defects with stronger implementer/planner models, and allow a second fix round instead of parking. This ADR re-pitches the ladder to that end, and adds a small verifier change that shortens each serial fix round.

## Decision

### 1. Rigor saturates at `M`

The fixed, model-agnostic rigor baseline (ADR-0001 §5) is re-mapped so `M`, `L`, and `XL` all sit at the top tier:

| Level | Verifier lenses (per issue) | Fix rounds |
| ----- | --------------------------- | ---------- |
| **XS** | 1 broad (correctness + tests + security, folded) | 1 |
| **S** | 1 broad | 1 |
| **M** | 3 focused (correctness · tests · security) | 2 |
| **L** | 3 focused | 2 |
| **XL** | 3 focused | 2 |

Concretely, `LEVEL_RANK` in `scripts/orchestrate.py` changes from `{XS:0, S:0, M:0, L:1, XL:2}` to `{XS:0, S:0, M:2, L:2, XL:2}`. `RIGOR_TIERS` (the `(lenses, fix_rounds)` per rank) and `LENSES_BY_RANK` are unchanged; rank 1 (2 lenses, 2 rounds) is no longer any level's baseline and is reached only by a `Risk: medium` escalation on an `XS`/`S` issue.

Consequences of the re-map:

- **`M` (the default) becomes 3 lenses, 2 fix rounds.** This is the deliberate cost increase — an informed trade of tokens for fewer defects escaping the one parallel panel and fewer issues parked at the fix-round cap. Documented honestly, not softened.
- **`XS`/`S` stay the cheap fast lane** (1 broad lens, 1 fix round) — the lane for a large homogeneous-trivial batch (pairs naturally with `--max-lenses=0` per ADR-0003 §3).
- **Risk escalation is only observable at `XS`/`S`.** Since `M`+ already tops out, a `Risk:` marker at `M` or above adds nothing; at `XS`/`S` it still pulls the issue up (medium → rank 1 / 2 lenses; high → rank 2 / 3 lenses), escalate-only, exactly as ADR-0001 §6 and ADR-0003 §5 define.
- **The inviolable floor is untouched** (ADR-0001 §5, §7): ≥ 1 adversarial lens per issue, a fix-round floor of 1, and the mandatory integration review whenever ≥ 1 issue integrated. `0` fix rounds and the per-issue-lens breach remain reachable only by the explicit `--max-fix-rounds=0` / `--max-lenses=0` overrides.

### 2. The model/effort ladder is re-pitched (illustrative, non-durable)

Per ADR-0001 §2/§4 the concrete `(model, effort)` per role is derived at runtime against the harness's live model list and is **not** part of the durable contract; the table below is what the derivation produces today (as of 2026-07), refreshed as models change.

| Level | Judgment (planning + review) | Implementer | Mechanical |
| ----- | ---------------------------- | ----------- | ---------- |
| **XS** | Opus · low | Sonnet · medium | Haiku · thinking |
| **S** | Opus · medium | Sonnet · high | Haiku · thinking |
| **M** | Fable · medium | Opus · medium | Sonnet · low |
| **L** | Fable · high | Opus · xhigh | Sonnet · low |
| **XL** | Fable · high | Fable · high | Sonnet · low |

The narrative: **`M` gives you Fable as the judge; `L` adds a deep-reasoning Opus implementer; `XL` is Fable all the way.** The judgement ladder climbs Opus · low → Opus · medium → Fable · medium → Fable · high → Fable · high.

The judge tops out at Fable · **high**, not `xhigh`, deliberately. Anthropic's own Fable 5 guidance (the migration reference in the `claude-api` skill) makes `high` the recommended default and reserves `xhigh` for the most capability-sensitive work, noting that lower effort settings — even `low` — on Fable 5 often exceed the `xhigh` or `max` performance of previous models, and that `max` is diminishing-returns / overthinking-prone. External measurements put `xhigh` at ≈ 2× the token spend of `high` on agentic runs. So the marginal reasoning `xhigh` would buy a review pass is not worth ≈ 2× its cost. Fable · medium at `M` judgment is justified on the same grounds: it pairs a stronger base model with much shorter thinking, at a per-token cost offset by that brevity.

The guardrail **"judgment never resolves below the session tier"** (ADR-0001 §2) is unchanged; in a Fable session it already pulls judgment up, and this table simply makes the official ladder match. The `implementerMode` mapping (`XS`/`S` → `execute`, `M` → `balanced`, `L`/`XL` → `autonomous`) and the inversely-scaled implementation-plan granularity (ADR-0002 §3–§4) are unchanged.

### 3. A verifier lens proposes a fix direction

When a verifier lens confirms a real finding, it also proposes a remedy **direction**, so the fix agent starts from a diagnosis *and* a direction rather than re-deriving one — shortening each serial fix round (the wall-clock cost, §Context). The suggestion rides an optional `suggestedFix` field on `VERDICT_SCHEMA`'s finding object; it flows to the fix agent rendered separately and marked advisory, alongside the finding's own `title`/`detail` that already reach it.

Three guardrails bind the mechanism:

1. **Judge first, then suggest.** The lens brief establishes whether the defect is real *before* considering a fix. Otherwise a reviewer who cannot see an easy fix might soften the finding — eroding adversarial neutrality. The `verify` prompt states this explicitly.
2. **Finding authoritative, suggestion advisory.** The fix prompt says: verify the suggestion before following it (the reviewer read the code but never ran it); pick a better fix if one is clear; and bind the tests to the acceptance criteria, never to the suggestion.
3. **Re-verify stays keyed to the finding, not the solution.** The targeted re-verify (`reverifyFindings`) is unchanged — it checks whether the finding is resolved, never whether the suggestion was followed — so a fixer who chose a better solution than suggested is not penalized. `suggestedFix` is deliberately *not* rendered into the re-verify prompt.

## Consequences

**Positive.** The default `M` run now catches more in its single parallel panel pass and repairs one more round before parking — directly serving the wall-clock / fewer-round-trips priority. The re-pitched models put the strongest reasoning where defects are caught (the judge) and prevented (the implementer). Verifier fix-direction suggestions cut the re-derivation cost of each serial fix round. `XS`/`S` remain a genuinely cheap fast lane.

**Consciously accepted costs.**

- **`M` costs more tokens** — per issue ≈ 5–9 sub-agents (from ≈ 3–5), so a 30-issue `M` run is ≈ `30 × 7 + 3` sub-agents rather than `30 × 4 + 3`. This is the informed trade; token cost is explicitly not the optimization target.
- **`L` and `XL` no longer buy more rigor than `M`** — they buy deeper models/effort only. This is intended: rigor saturates at `M`, and process past 3 lenses / 2 rounds is not where the marginal defect is caught.
- **A `Risk:` marker at `M`+ is inert.** Accepted, because the baseline already sits at the ceiling the marker would escalate to.

**Invariants preserved.** The inviolable rigor floor and the budget bound stay on. The escalate-only, round-up-on-uncertainty risk model (ADR-0001 §6) is unchanged. `--max-lenses`/`--max-fix-rounds`/`--pr` semantics (ADR-0003), the `--yes`/merge-authority separation (§7), the sliding-implementer mechanism (ADR-0002), and the deterministic graph planner are all untouched. The orchestrator still never writes production code or reads diffs; no bump, tag, or release.

**Follow-up (implementation handoff).** Implemented in the same change that records this ADR: `scripts/orchestrate.py` (`LEVEL_RANK` re-map + comments); `skills/orchestrate/SKILL.md` (the two ladder tables, the cost model, and every per-level rigor mention); `docs/man/orchestrate.md` (the ambition-dial prose); `skills/orchestrate/orchestrate.workflow.js` (the `suggestedFix` schema field, the judge-first `verify` prompt, the advisory `fix` rendering); and the `tests/test_orchestrate*.py` suites (level→rigor derivation, the cost-model prose, and the verifier-suggestion structure).
