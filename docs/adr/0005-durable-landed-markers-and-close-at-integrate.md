# 5. Durable landed-markers and per-issue close-at-integrate (interrupt-safe restart)

- **Status:** Accepted
- **Date:** 2026-07-22
- **Deciders:** Thomas Barregren

> **Amends [ADR-0001](0001-orchestrate-control-model.md) §5 and §7 by reference.** §7's inviolable floor — "close an issue only after independent verification *and* integration" — is unchanged in substance; this ADR pins *when* and *by whom* that close happens (at integrate time, by the integrate step) and carves a single narrow exception to §7's "no sub-agent closes/pushes/merges" rule. §5's mandatory integration review is unchanged; this ADR records that it now operates at run level over already-closed issues and never reopens one. The escalate-only risk model (§6), the `--yes`/merge-authority separation (§7/§8), the rigor ladder (ADR-0004), and the `--max-lenses`/`--pr` decoupling (ADR-0003) are all untouched.

## Context

`/orchestrate` integrates each green issue the moment it is verified (ADR-0001 §7; the serial integrate-immediately design), which makes partial progress durable on the default branch. But the engine's notion of *which issues have landed* lived only in the running orchestrator session — an in-memory `landed` set consulted by the prerequisite-cascade helper — and issues were closed only at the Finalize step, after the whole run.

Field experience (kntnt-extractor, 2026-07-22, and earlier larger runs) exposed the failure this creates. A run was killed mid-flight by a session restart. The completion notification suggested relaunching with the Workflow tool's `resumeFromRunId`. That was done, byte-identically — but **Workflow resume is same-session-only**: a cross-session relaunch gets **zero cache hits** and silently **re-runs the entire plan from scratch**. Nothing detected the mismatch. The engine re-implemented an issue *already independently verified and landed on the default branch* from zero on a fresh branch; the verifier flagged the duplication, a fix round made the branch tree-identical to `main`, integrate hit a conflict, reconcile rebased, and redundant commits landed anyway. In an earlier run the same failure mode compounded across restarts into 50+ agents and 50+ branches, all wasted.

Three root causes:

1. **A dead resume degrades silently to a full re-run.** `resumeFromRunId` is same-session-only, but neither the skill nor the engine detects a cross-session resume; the launch proceeds with an empty cache and no warning.
2. **The engine had no idempotence guard.** It never checked whether an issue's work had already landed before dispatching an implementer. "Landed" existed only in the orchestrator's session memory — lost with the session — and in git history no agent was told to consult.
3. **GitHub state could not disambiguate.** Issues were closed only at Finalize, so after a mid-run crash a fully-landed issue was indistinguishable from an untouched one by its open/closed state.

## Decision

### 1. A durable, machine-readable landed-marker

At **integrate time**, the integrate step records the landing durably as a structured comment on the issue, in one canonical form with a single source of truth (`format_landed_marker` / `parse_landed_marker` in `scripts/orchestrate.py`), designed to extend cleanly to #48's richer milestone vocabulary:

- **Merge mode** (the change lands on the default branch): `orchestrate: landed <sha> on <branch>, run <runId>` — fixed-prefix, positional, no embedded timestamp (the comment's own metadata carries it).
- **PR mode** (nothing lands on the default branch): a symmetric lighter marker `orchestrate: opened PR #<pr>, run <runId>`; the issue stays open.

The `<sha>` is what makes the marker *verifiable* rather than merely *present*: a later run checks whether that commit is still an ancestor of the default-branch tip, distinguishing durably-landed work from a marker whose commit was reverted or rebased away.

### 2. Close the issue at integrate time (Decision D1)

In merge mode the issue is **closed by the integrate step at integrate time**, not by the orchestrator at Finalize. The §7 inviolable floor — "close only after independent verification *and* integration" — is satisfied at exactly that moment, per issue: the branch cleared the adversarial verifier panel *and* has now fast-forward-landed on the default branch. Closing there makes GitHub's open/closed state reflect durable progress (a fully-landed issue drops out of an `--state open` re-plan), at the cost of losing the single close-them-all-together Finalize moment. PR mode closes nothing — each issue stays open behind its pull request.

### 3. Writer authority — a single narrow exception to §7

§7 forbids every sub-agent to close the issue, push, or merge. The **integrate step alone** now gets a tightly-scoped exception: it MAY post the exact marker comment and (merge mode) close the issue — **and nothing else**. Every other sub-agent (implement, fix, verify, reconcile, **preflight**, teardown) remains forbidden.

The exception is forced by the run's shape, not a loosening of the posture: the orchestrator is **blocked on the single Workflow call for the whole run** and cannot post per-issue markers mid-run, and the deterministic engine has **no shell/filesystem I/O of its own** — so the per-issue marker+close can only be posted by a sub-agent, and the integrate step is the one already authorized to mutate shared state (land the change). The verify-then-integrate floor is preserved: integrate runs only after the verifier cleared, so "close only after independent verification AND integration" still holds.

### 4. A preflight idempotence guard

Before an implementer is dispatched for an issue, a **dedicated mechanical-tier preflight sub-agent** gathers state read-only (`gh issue view --comments`, `git merge-base --is-ancestor`, and any orchestrate PR's state) and returns structured facts. A **pure, unit-testable decision function** (`preflightDecision` in the engine-helpers module, mirrored inline in the workflow engine per the one-top-level-export constraint) maps those facts to one verdict:

- Marker present **and** its SHA is an ancestor of the current default tip → **skip** (`already-landed`); dispatch no implementer, and mark it landed so its dependents proceed.
- Marker present but SHA **not** an ancestor of default (reverted / rebased away / foreign history) → **park loudly** (`landed-marker-stale`) for a human to reconcile. **Never rebuild from zero.**
- PR mode, an open orchestrate-opened PR already exists → **benign skip** (`already-open`); the expected completed PR-mode state, not a loud park.
- No marker → **dispatch** normally.

This bounds the damage of **any** blind restart, whatever caused it. A dead preflight decodes to `dispatch`, so its failure only ever falls back to the pre-guard behaviour (a re-implement the verifier catches), never a wrongful skip.

### 5. No engine-side resume detection; the skill prescribes the restart

No engine-side detection of a dead resume is attempted: the script receives no resume signal from the harness, so the **preflight guard is the safety net, not detection.** `skills/orchestrate/SKILL.md` documents loudly that Workflow resume is same-session-only, corrects the completion-notification advice, and prescribes the cross-session restart — re-run `orchestrate.py plan` over the open-issues-minus-landed remainder, launch a **fresh** run over it (the guard makes even a naive relaunch idempotent), never blind-resume. The rule: *detect that the preconditions to continue are gone, then re-plan and hand over; never start over from zero.*

## Consequences

**Positive.** A stopped run is now safe to continue: a fresh run over the remaining scope re-implements nothing that landed, opens no duplicate branch, and lands no redundant commit. GitHub state reflects durable progress. The marker format is a single source of truth shared with #48's milestone reporting.

**Consciously accepted costs.**

- **One extra cheap mechanical agent per issue** — the preflight guard runs before every dispatch, even on a fresh run where every verdict is `dispatch`. It is the cheapest tier and is folded into the mechanical overhead, not the judgment cost factor; the always-on guard is the price of idempotence against *any* blind restart.
- **The single close-them-together Finalize moment is lost** — issues now close one at a time at integrate time (merge mode). Accepted: closed-at-integrate is what makes GitHub state a durable signal a re-plan can read.
- **A narrow §7 exception exists** — the integrate step may close/comment. Kept as tight as possible (that one step, that one marker, that one close) and justified by the orchestrator-blocked-mid-run constraint.

**Invariants preserved.** The §7 inviolable floor holds — close only after independent verification *and* integration, now enforced per issue at integrate time. The mandatory integration review (§5) still always runs; a cross-issue finding is handled at **run level** (a hotfix branch off the default) and **never reopens an already-closed issue**. The escalate-only risk model, the rigor ladder (ADR-0004), the `--max-lenses`/`--pr` semantics (ADR-0003), and the sliding implementer (ADR-0002) are untouched. The orchestrator still never writes production code or reads diffs; no bump, tag, or release.

**Follow-up (implementation handoff).** Implemented in the same change that records this ADR: `scripts/orchestrate.py` (`format_landed_marker` / `parse_landed_marker`, the `Marker` dataclass, the `already-landed` / `already-open` / `landed-marker-stale` report statuses); `lib/orchestrate/engine-helpers.mjs` and `skills/orchestrate/orchestrate.workflow.js` (`preflightDecision`, the `preflight` agent and `PREFLIGHT_SCHEMA`, the wave-loop guard, the integrate marker+close step gated to a real issue); `skills/orchestrate/SKILL.md` (the preflight lifecycle step, the durable-marker + close-at-integrate prose, the narrow-exception operating-contract bullet, the *Restarting a stopped run* section, the corrected resume advice); and the `tests/test_orchestrate*.py` suites (the marker round-trip and rejection, the four preflight verdicts, the integrate marker+close structure, the restart protocol, and the SKILL↔parser consistency test).
