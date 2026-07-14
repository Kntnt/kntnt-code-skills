# 3. Decoupling per-issue rigor from the ambition dial (`--max-lenses`), and the `--pr` flag

- **Status:** Accepted
- **Date:** 2026-07-14
- **Deciders:** Thomas Barregren

## Context

ADR-0001 §1 collapsed all of `/orchestrate`'s ambition onto a single dial — `--level`, `XS…XL` — carrying *both* model/effort *and* the verification-rigor baseline as "one spectrum," with the explicit rule "no separate rigor knobs; they all fold into the level." The first large real run exposed the gap this leaves. A backlog of ~30 AFK issues, most individually trivial, was run before the level system existed; it ground through ~300 sub-agents over nearly a day, and the disproportion is what motivated the level dial in the first place. But even with the dial, one genuine, recurring workflow has no expression: a **large batch of individually-trivial, homogeneous issues driven by a strong implementer, where an independent per-issue second opinion is N× overhead for near-zero risk**. This is precisely the pattern the maintainer hand-wrote repeatedly before this skill existed — "one sub-agent per issue, implement and test, you re-test on return, one integration test at the end" — a flow with tests and an integration check but *no per-issue adversarial reviewer*.

The single dial cannot express it, because the dial *couples* capability and rigor along a diagonal: `XS` is cheap-and-lean, `XL` is strong-and-multi-lens. The wanted cell is *off* that diagonal — **high capability, zero per-issue rigor** (a strong model such as Opus·xhigh or Fable, with no independent lens). This ADR settles that decoupling and the small merge-surface fix that surfaced alongside it. It amends ADR-0001 §1 (the "one dial" principle), §5 (the inviolable per-issue-lens floor), and §7/§8 (the merge surface); it changes no other decision in ADR-0001 or ADR-0002.

## Decision

### 1. The dial sets the default coupling; rigor is separably overridable

ADR-0001 §1's "one dial, nothing else / no separate rigor knobs" was too strong, and was already breached in practice: `--max-fix-rounds` is a rigor knob that overrides the level-derived default. This ADR makes the principle honest rather than pretending otherwise. **The level remains the default and sets the capability↔rigor coupling (the diagonal); rigor is separably overridable from capability through explicit `--max-<thing>` overrides.** The dial is still the one thing a maintainer normally touches; the overrides are the sanctioned, explicit way to *leave* the diagonal when there is a reason. This is a deliberate, bounded amendment to §1, not its abandonment: there is still exactly one dial, plus a small, symmetric family of explicit per-run overrides (`--max-fix-rounds`, and now `--max-lenses`), each naming one rigor integer §5 already defines.

### 2. `--max-lenses=N` — the per-issue verifier override

A new per-run argument `--max-lenses=N`, mirroring `--max-fix-rounds` exactly, caps the per-issue verifier panel (the plan's `issues[].lenses` array).

- **`N ≥ 1` is a plain, floor-respecting override** (e.g. pulling an `XL` issue's panel from 3 lenses to 1). It needs no floor amendment — it is the same category of knob as `--max-fix-rounds`.
- **`N = 0` is the floor-breaching value.** It skips the per-issue independent adversarial review entirely. This is the amendment to ADR-0001 §5's "≥ 1 independent adversarial lens per issue": that floor is now breachable, but *only* by this explicit override, never by a level, a policy, or `--yes`.
- **`--max-lenses` is a per-run flag only**, never a project/global policy default — by the same design as `--max-fix-rounds`. Consequently the floor-breach always requires the in-the-moment flag; it can never arise from standing defaults alone.

**What `N = 0` removes, and what it keeps.** It removes the independent per-issue second opinion *in full* — including any independent re-check of the implementer's own red-before-green demonstration, which at `N ≥ 1` is one of the things an active lens's brief reviews. It keeps: **test-first** (the implementer still writes a failing test before the code and self-reports the `redCommit`/`greenCommit` pair) — self-attested, not independently re-checked, at `N = 0`; and the **mandatory integration review** (ADR-0001 §5's once-per-run adversarial pass, hotfix-capable in merge mode, which always runs). `orchestrate.py redgreen` exists as a deterministic git-log check available for ad hoc use (e.g. via `/code-review`, §7), but nothing in the per-issue lifecycle invokes it automatically at any panel size, so it is not — today — an independently enforced backstop at `N = 0`. The name scopes itself: the integration review is not a "lens," so `--max-lenses=0` cannot touch it.

### 3. The use case, and the non-use case

`--max-lenses=0` exists for the **large batch (≈ 10–30) of individually-trivial, homogeneous issues** — a bulk rename across many files, a batch of docstrings, a mechanical migration — where per-issue verification is N× overhead for near-zero risk and the integration review plus the maintainer's own review suffice. The saving **scales with N** (it roughly halves the per-issue agent and serial-step count), which is why it earns its place only at batch scale.

It is explicitly **not** for a small trivial task. Two dependent trivial functions — the original smoke test — should use a lighter tool (a single `tdd`/`coder` agent, or `--level=XS`), not orchestrate with verification off; reaching for `--max-lenses=0` there is using the wrong tool and turning off its net at the same time. The documentation says so.

### 4. Merge authority is unchanged; no PR-forcing

`--max-lenses=0` **respects merge authority exactly as any run does** (a per-run `--merge` or a declared merge policy). It does **not** force PR mode and does **not** strip policy-granted merge. A verification flag silently changing merge behavior would be a hidden coupling and violate least-astonishment: a maintainer who set `merge-policy: merge` and runs `--max-lenses=0` expects a merge.

The retained safety when a `--max-lenses=0` batch lands on the default branch is not zero: the **always-on integration review** (#2, hotfix-capable in merge mode), the implementer's own **self-attested test-first practice**, and the maintainer's **conscious, explicit act** (the per-run flag). Because `--max-lenses` is per-run only (§2), the dangerous cell — no per-issue lens *and* landing on `main` — is never reachable by standing defaults alone; it always takes the in-the-moment flag. When a maintainer *does* want a no-lens batch reviewed before landing, the clean, non-astonishing escape is the explicit `--max-lenses=0 --pr` (§6), not a tool-imposed downgrade.

### 5. Risk precedence under `--max-lenses=0` — the flag holds; two-channel escalation

Under `--max-lenses=0` the flag is the rule and yields only for genuinely compelling risk, and rarely. The risk signal splits by *when* it is discovered:

- **Plan-time hazard** (the planner infers a hazard while reading the brief, per ADR-0001 §6) is **surfaced at the single gate and in the report; the flag still holds by default.** The maintainer decides at the gate; `--yes` waives it. This is *not* an automatic override — plan-time risk informs, it does not escalate.
- **In-situ hazard** (the implementer, *during the work*, discovers a real, previously-unseen danger surface — a write path, a permission gate, an irreversible delete — and flags it in its three-bucket report) escalates **one** lens on that one issue, reported. This is the rare, sanctioned automatic override, and the only one.

Rationale: this honors "the flag holds unless there is exceptional reason," keeps overrides rare (only in-situ surprises trigger them), and preserves ADR-0001 §6's escalate-only, round-up-on-uncertainty spirit for the case that actually warrants it. The consciously accepted cost: a plan-time hazard the maintainer runs *past* the gate receives no automatic lens — gate visibility is its safeguard. Crucially, there is **no mid-run pause**: the "are you sure?" lives at the sanctioned gate (plan-time) or as an automatic one-lens escalation (in-situ), never as a blocking per-issue prompt. ADR-0001's hard "never block on the maintainer" rule and §7's precise definition of `--yes` (yes to the single gate, nothing more — *not* a blanket yes to every future question) are both preserved.

### 6. `--pr` — the explicit conservative merge partner

A new `--pr` argument, the symmetric partner of `--merge`, closes an existing asymmetry: today a maintainer can opt *into* merge (`--merge`) but cannot force PR for a single run on a repo whose declared policy is merge. Precedence: **explicit flag (`--pr` / `--merge`) > declared policy marker > conservative PR default.** `--pr` and `--merge` are mutually exclusive; supplying both is an error, because a contradiction should be loud, not silently resolved.

There is **no inferring `auto`.** Claude never *grants* merge authority from inference — that would reopen the silent-authority hole ADR-0001 §7 closes. The default already follows the *declared* policy and falls back to PR (the safe "auto"), and inference may only *recommend* `--merge` at the gate, never grant it. The maintainer's global `~/.claude/CLAUDE.md` marker already serves "declare once for all repos" without any inference.

### 7. Retroactive verification is `/code-review`, not a new flag

No dedicated "pickup" flag is added. After-the-fact verification of a `--max-lenses=0` run is served by `/code-review <base>`, which reviews the changes since a fixed point along both Standards and the originating issue's Spec — exactly the per-issue-contract dimension the skipped lens would have covered. Verify-after is deliberately weaker than verify-before-integrate (the implementer's context is gone, the fix is a costlier hotfix, and in merge mode the defect already merged), so it is an active choice a maintainer reaches for, not a safety net to lean on; a dedicated flag would add persistent run-state for marginal benefit over a base ref. It is documented as a README idiom.

## Consequences

**Positive.** The off-diagonal cell — a strong implementer with no per-issue lens — becomes reachable, honestly, through one explicit override rather than a seductive `--quick` noun that would bundle a floor-breach with a merge behind a single word. The maintainer's original hand-written workflow is codified. The saving scales with batch size, so the mechanism is cost-effective exactly where it is meant to be used. `--pr` makes the merge surface symmetric. Orchestrate stays lean: no new mode, no pickup machinery, no second dial.

**Consciously accepted costs.**

- **ADR-0001 §1 is amended** — rigor is now separably overridable from capability. Mitigated by keeping the dial the default and every override explicit and per-run; the surface is one dial plus a small symmetric override family, not a second posture dial.
- **The inviolable per-issue-lens floor (§5) is now breachable** by `--max-lenses=0`. Mitigated by what survives the breach: the integration review always runs, the implementer still works test-first and self-attests red-before-green (independent re-checking of it, by a lens or otherwise, is exactly what the breach drops), the flag is per-run only, in-situ risk still escalates a lens, plan-time risk is shown at the gate, and `--max-lenses=0 --pr` is the easy human-gated escape.
- **A plan-time hazard run past the gate gets no automatic lens** (§5) — a deliberate trade for keeping overrides rare and the flag authoritative.
- **`--max-lenses=0 --merge` can land an un-independently-verified (but integration-reviewed) defect on `main`** — the maintainer's conscious, bounded risk, never reachable without the in-the-moment flag.

**How we will know we were wrong, and what we will do.** The instrument is the idiom this ADR adopts: on a sample of `--max-lenses=0` runs, run `/code-review <base>` afterwards and count findings that (a) map to an acceptance criterion and (b) would have blocked integration — the rate of catchable defects that reached a branch or `main`.

- *Regret adding it* (the floor should have held): if that rate is non-trivial — starting threshold ≈ 1 in 10 batches, maintainer-adjustable — the decoupling ships too many catchable defects. Response: restore the per-issue floor for `--max-lenses=0`, or constrain it (force PR, or permit it only on planner-low-risk issues).
- *Regret the caution* (the safeguards are over-insurance): if across many runs the in-situ auto-lens never fires, the gate hazard notice is never acted on, and `/code-review` finds ≈ nothing, the safeguards are dead machinery. Response: prune them (drop the in-situ override, quiet the gate notice) and reconsider whether even the integration review is warranted for trusted batches.

**Invariants preserved.** The mandatory integration review always runs whenever ≥ 1 issue integrated. The implementer always works test-first, demonstrating red before green on its own — independent re-checking of that demonstration is exactly what `--max-lenses=0` drops, same as the rest of the per-issue panel. `--yes` keeps its precise meaning — the single pre-run gate only, never merge authority, never a blanket yes. Merge authority stays an explicit grant (flag or declared policy), never inferred. The orchestrator still never writes production code or reads diffs. No bump, tag, or release.

**Out of scope / unchanged.** Everything else in ADR-0001 and ADR-0002 is untouched — the sliding implementer, the implementation-planning pass, the deterministic graph planner, the level→(model, effort) derivation. No `--quick` noun. No `auto` merge inference. No retroactive-pickup flag.

**Follow-up (implementation handoff).** This ADR changes the control surface and requires reconciliation, to be cut into red-green build issues:

- **`skills/orchestrate/SKILL.md`** — document `--max-lenses` and `--pr` in §Arguments; add the risk precedence (plan-time→gate, in-situ→one-lens) to §"Rigor baseline"; add both flags and the "no inferred merge authority" note to the decision-boundary map; state the `--max-lenses=0` use-case/non-use-case; fold the §5-floor amendment (0 lenses reachable only via `--max-lenses=0`) into the rigor-floor prose.
- **`scripts/orchestrate.py`** — add `--max-lenses` to `plan` (capping `issues[].lenses`, `0` permitted), and surface the merge-vs-PR intent so `--pr`/`--merge`/policy precedence and the `merge_required` parking interact correctly; keep both per-run (no policy path).
- **`skills/orchestrate/orchestrate.workflow.js`** — honor a `lenses: 0` panel (skip the per-issue verify stage, keep integrate and the mandatory integration review); implement the in-situ hazard → one-lens escalation from the implementer's report; mirror any extracted helper in `lib/orchestrate/engine-helpers.mjs`, drift-guarded and structurally tested.
- **`README.md`** — the two-modi-operandi table (merge-policy vs PR default, with `--pr`/`--merge` as the per-run exceptions), the "quick orchestrating" idiom (`--level=XL --max-lenses=0 --merge`), and the `/code-review <base>` retroactive idiom.
- **`docs/adr/0001-orchestrate-control-model.md`** — note the §1/§5/§7 amendment (a back-reference to this ADR), as ADR-0002 was cross-referenced.
