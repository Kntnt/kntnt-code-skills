# 6. Mid-run milestone heartbeat and the reporter writer role

- **Status:** Accepted
- **Date:** 2026-07-22
- **Deciders:** Thomas Barregren

> **Amends [ADR-0005](0005-durable-landed-markers-and-close-at-integrate.md) §3 and [ADR-0001](0001-orchestrate-control-model.md) §7 by reference.** ADR-0005 §3 carved a *single* narrow exception to §7's "no sub-agent closes/pushes/merges" rule — the integrate step, the sole outward *mutator*. This ADR widens that exception to admit a **second, strictly weaker** outward writer: a comment-only, mechanical-tier *reporter* that posts mid-run milestone comments and mutates no shared state. Everything else in ADR-0001/0002/0003/0004/0005 is untouched — the §7 inviolable floor (close only after independent verification *and* integration) holds, integrate remains the sole mutating writer and the sole closer, and the #49 terminal `landed` / `opened-PR` markers, the close-at-integrate behaviour, and the preflight guard are unchanged.

## Context

`/orchestrate` integrates each green issue the moment it is verified and, since ADR-0005 (#49), records that landing durably: the integrate step posts `orchestrate: landed <sha> on <branch>, run <runId>` (merge mode) or `orchestrate: opened PR #<pr>, run <runId>` (PR mode). So *which issues finished* is already visible out of band, on the issue timeline, without touching the Claude Code TUI.

What is **not** visible is the *within-ticket heartbeat*: which issue is in flight right now, and where inside its lifecycle it stands. During a 6–12 hour run the only per-issue signal that reached the maintainer out of band was that terminal marker + close, posted once, at the very end of each issue. Between landings there was nothing: an issue churning in fix round 3 for two hours was indistinguishable from steady progress until it finally landed, and a **parked/failed** issue left no durable marker at all. The engine `log()`s wave and fix-round events, but those render only in the in-session progress tree — the exact place peeking has repeatedly killed the background run.

The same run-shape constraint ADR-0005 §3 identified still binds: the orchestrator is **blocked on the single Workflow call for the whole run**, so it cannot post per-issue comments mid-run, and the deterministic engine has **no shell/filesystem I/O of its own**. So a mid-run comment can only be posted by a sub-agent dispatched at the boundary.

## Decision

### 1. A milestone vocabulary — extend #49's grammar

Extend #49's single-source-of-truth marker grammar (`format_*` / `parse_landed_marker` in `scripts/orchestrate.py`) with five mid-run **milestone verbs**, keeping the exact fixed-prefix positional discipline `orchestrate: <verb> …, run <runId>`:

- `orchestrate: started #<n>, run <runId>` — the issue's build began.
- `orchestrate: implementation green #<n>, run <runId>` — the implementer's gates passed.
- `orchestrate: verification cleared #<n>, run <runId>` — the adversarial verifier panel cleared.
- `orchestrate: fix round <k> #<n>, run <runId>` — a fix round began (only when one runs).
- `orchestrate: parked #<n> (<reason>), run <runId>` — the issue died (failed to integrate, was blocked, or exhausted its fix rounds).

They share the same `format_*`/`parse` source of truth and extend the `Marker` dataclass's `verb` domain (carrying `number`, `fix_round` for a fix round, and a `reason` for a park; unused fields stay `None`). They are machine-readable so the deferred `status` command (#50) can read them back.

**The hard correctness constraint.** A milestone verb carries an issue **number**, never a landing **SHA**, and a **different** verb from `landed`. #49's preflight idempotence decision keys specifically on a `landed` marker whose SHA is an ancestor of the default tip; because no milestone verb ever parses as `landed` or populates `sha`, no milestone comment can trigger a false `already-landed` skip. #49's four preflight verdicts are unchanged in the presence of the new comments. A malformed milestone comment parses to `None`.

### 2. The reporter role — a second, strictly weaker writer

A dedicated **mechanical-tier** *reporter* sub-agent is dispatched at each phase boundary the engine reaches, whose **sole** authorized outward write is to post **one** milestone comment — **never** close, push, or merge. It is to *milestones* what #49's preflight is to *idempotence*: a mechanical-tier sub-agent with one narrow job. Its prompt carries the same shared `AGENT_CONSTRAINTS` the workers do (forbidding close/push/merge), and it needs no worktree because it touches no code.

It is forced by the same run-shape constraint as ADR-0005 §3, but its write is **strictly weaker** than integrate's: a **comment mutates no shared state** — no branch moves, no issue closes, no PR opens — so the posture widens *less* than ADR-0005 already did. This is the **second** authorized outward writer, and it is comment-only.

Reporting is **auxiliary and best-effort**: a failed or absent reporter dispatch must **never** block, park, or fail an issue's progress, mirroring ADR-0005's "a dead preflight decodes to `dispatch`" philosophy — visibility is never a correctness gate. The engine swallows a reporter error and continues. But each reporter dispatch is **awaited** so an issue's milestone comments post in **lifecycle order** (which #50 reads back as the issue's current state); reporters for *different* issues may still run concurrently. Awaiting governs *ordering*, not success — an errored reporter is still swallowed.

The boundaries and their milestones: after a **dispatched** preflight → `started` (never for a preflight-skipped `already-landed` / `already-open` / stale issue); after implement goes green → `implementation green`; after the verifier panel clears → `verification cleared`; entering each fix round → `fix round <k>`; on fail / blocked / exhausted-fix-rounds → `parked` with a short reason. The heartbeat applies in **both merge and PR modes** — the mid-run boundaries are mode-agnostic; only the terminal marker differs, and that stays #49's.

### 3. The boundary of the exception

The reporter posts **status comments only**. Integrate remains the **sole mutating writer**: it still owns the terminal `landed` / `opened-PR` marker **and** the close, at integrate time (ADR-0005 §3 unchanged). The reporter owns `started` / `implementation green` / `verification cleared` / `fix round k` / `parked` — and nothing else. No other sub-agent (implement, fix, verify, reconcile, preflight, teardown) gains any write. The §7 inviolable floor is untouched: the **reporter never closes**, so "close only after independent verification *and* integration" still holds exactly as before.

## Consequences

**Positive.** A multi-hour run now emits a phone-visible per-issue narrative on each issue's own timeline — which issue is in flight and where it stands — plus a durable marker when an issue *parks* (dies) rather than lands, the one thing #49 left invisible. The maintainer watches the issue comments / GitHub notifications, never the TUI. The milestone grammar is the same single source of truth #49 established, ready for #50's `status` renderer.

**Consciously accepted costs.**

- **~4–5 extra cheap mechanical reporter dispatches per issue** — mechanical tier, folded into the mechanical overhead, not the `P`/`F` judgment cost factor.
- **A chattier issue timeline** — more comments per issue.
- **The outward-write surface widens from one writer to two** — kept as tight as possible: mechanical tier, comment-only, never mutating, so the posture widens *less* than ADR-0005's mutating exception already did.

**Invariants preserved.** The §7 floor holds — close only after independent verification *and* integration, and the **reporter never closes**. Integrate stays the **sole mutating writer** and the sole closer. #49's terminal markers, close-at-integrate, and the four preflight verdicts are unchanged — no milestone verb parses as `landed`. The escalate-only risk model, the rigor ladder (ADR-0004), the `--max-lenses`/`--pr` semantics (ADR-0003), and the sliding implementer (ADR-0002) are untouched. The orchestrator still never writes production code or reads diffs; no bump, tag, or release.

**Follow-up (implementation handoff).** Implemented in the same change that records this ADR: `scripts/orchestrate.py` (the `format_started_marker` / `format_implementation_green_marker` / `format_verification_cleared_marker` / `format_fix_round_marker` / `format_parked_marker` helpers, the extended `Marker` verb domain and `parse_landed_marker`); `skills/orchestrate/orchestrate.workflow.js` (the `reporter` agent and `REPORTER_SCHEMA`, the best-effort `report` wrapper, the milestone templates, and the wave-loop / `buildAndVerify` boundary dispatches); `skills/orchestrate/SKILL.md` (the reporter lifecycle step, the milestone vocabulary, the two-authorized-writers operating-contract bullet, and the out-of-band progress-watching prose); and the `tests/test_orchestrate*.py` suites (the milestone round-trip and rejection, the no-milestone-parses-as-landed non-regression, the extended SKILL↔parser consistency test, and the reporter engine structure). Out of scope and deferred to #50: the `orchestrate.py status` renderer and R1c push notifications.
