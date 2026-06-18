# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Deterministic orchestration mechanics for the `orchestrate` skill.

The judgement-heavy part of an away-from-keyboard build — implementing each
issue, adversarially verifying it, and deciding what is good enough — stays
with the sub-agents the orchestrator dispatches. This script owns the
mechanical, error-prone bookkeeping that is identical for every project and
must be done the same way every time:

  * plan    Turn a set of in-scope issues into a dependency graph and the
            topologically ordered "waves" the orchestrator dispatches in,
            flagging cycles and dependencies that point outside the scope.
  * report  Fold the sub-agents' per-issue verdicts into one consolidated
            report: what shipped green first, then the de-duplicated work
            left for a human, then assumptions and blockers.

It never calls `claude`. Spawning sub-agents is the orchestrator's job and
runs inside the interactive session — so it counts against the subscription
pool, not the headless (`claude -p`) credit. This script only reads from stdin
and writes to stdout; it shells out to nothing — the caller runs `gh` and
`git` and pipes their output in:

  * `plan`     <- `gh issue list --json number,title,labels,body`
  * `redgreen` <- `git log --reverse --no-merges --format='commit %H' --name-only <base>..<head>`

Standard library only; the PEP 723 block pins only the Python version so
`uv run scripts/orchestrate.py ...` works from anywhere.

Subcommands:

    plan      Build the dependency graph and dispatch waves from issues JSON.
    redgreen  Check a branch demonstrates a failing test before the code.
    report    Render the consolidated final report from verdicts JSON.

Exit codes:

    0   Success.
    1   Bad arguments, malformed input, or a dependency cycle.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, NoReturn, cast

# The triage state that marks an issue as fully specified and safe to build
# without a human in the loop. The caller's `gh` query resolves the real
# scope; this constant only documents the default and labels the plan output.
DEFAULT_SCOPE_LABEL = "ready-for-agent"

# The `Blocked by` section of the to-issues template, and the issue-reference
# token (`#42`) used inside it. The section body runs to the next heading or
# end of file; an explicit "None - can start immediately" yields no matches.
BLOCKED_BY_SECTION_RE = re.compile(
    r"^#{1,6}\s+Blocked by\s*$(?P<body>.*?)(?=^#{1,6}\s|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
ISSUE_REF_RE = re.compile(r"#(\d+)")

# Directional blocking keywords that name a real hard edge wherever they
# appear in the body — not only under a `## Blocked by` heading. Triage writes
# dependencies into the agent brief as inline labels (`**Depends on:** #44`),
# so the planner must read those forms too or a coupled set collapses into one
# unsafe wave (issue #10). Longest forms come first so `Depends upon` wins over
# the `Depends on` prefix when both could match.
HARD_EDGE_KEYWORDS = ("Blocked by", "Depends upon", "Depends on", "Requires", "Needs")

# Match a hard-edge keyword anywhere in the text, tolerating an optional bold
# wrapper (`**Depends on:**`) and an optional colon. The keyword is captured so
# the derived edge can record which word produced it; the reference region that
# follows is scanned separately, because it may span a bullet list of `#N`. The
# `\b` anchors keep a keyword from matching inside a longer word (`prerequires`,
# `misrequires`); the trailing horizontal-only whitespace (`[^\S\n]*`) keeps the
# match from crossing a newline, so the reference scan's notion of "the keyword's
# own line" stays accurate even after a `## Blocked by` heading.
INLINE_EDGE_RE = re.compile(
    r"\*{0,2}\s*\b(?P<keyword>"
    + "|".join(HARD_EDGE_KEYWORDS)
    + r")\b[^\S\n]*\*{0,2}[^\S\n]*:?",
    re.IGNORECASE,
)

# A single bullet-list item that carries one issue reference — the continuation
# form of a label followed by a list (`**Depends on:**\n- #44\n- #45`).
BULLET_REF_RE = re.compile(r"^\s*[-*]\s*#(\d+)\b")

# Non-directional coupling phrases. These are NEVER edges — over-serialising on
# a vague "relates to" would hold issues back for no real dependency — but they
# are recorded as soft notes so a possible coupling stays visible after an
# unattended run.
SOFT_NOTE_PHRASE = r"relates to|related to|see also|touch(?:es|ing)? the same files? as"
SOFT_NOTE_RE = re.compile(
    rf"(?P<phrase>{SOFT_NOTE_PHRASE})"
    r"\s*:?\s*(?P<refs>(?:#\d+[\s,and&]*)+)",
    re.IGNORECASE,
)

# Where a hard keyword's same-line authority ends: a sentence terminator, or the
# start of the next hard keyword or soft phrase. A keyword governs only the `#N`
# in its own clause, so `Depends on #45. Relates to #44.` (or `Requires #1.
# Touches the same files as #2.`) does not absorb the trailing soft ref as a hard
# edge — exactly the AC's "NO edge for a soft phrase" criterion.
CLAUSE_BOUNDARY_RE = re.compile(
    r"[.!?]\s"
    r"|\b(?:" + "|".join(HARD_EDGE_KEYWORDS) + r")\b"
    rf"|\b(?:{SOFT_NOTE_PHRASE})\b",
    re.IGNORECASE,
)

# The set of statuses a verdict may carry, in the order the report presents
# them: shipped work leads, work parked or blocked for a human trails.
DONE = "done"
PARKED = "parked"
BLOCKED = "blocked"

# How a changed path is recognised as test code, across the languages the
# standard covers: a directory segment that conventionally holds tests, or a
# filename that conventionally names one. A project with an unusual layout can
# override the whole heuristic with --test-glob.
TEST_DIR_SEGMENTS = frozenset({"test", "tests", "spec", "specs", "__tests__"})
TEST_FILE_RE = re.compile(
    r"^(?:test_.*\.py"
    r"|.*_test\.(?:py|go|rb)"
    r"|.*\.(?:test|spec)\.[^.]+"
    r"|.*Test\.(?:php|java|kt)"
    r"|conftest\.py)$",
    re.IGNORECASE,
)


@dataclass
class DependencySignals:
    """The dependency signals extracted from one issue body.

    `edges` maps each blocking issue number to the keyword that produced it
    (the audit trail an unattended run is inspected by). `soft_notes` holds the
    non-directional coupling phrases that must stay visible but never block.
    """

    edges: dict[int, str] = field(default_factory=dict)
    soft_notes: list[str] = field(default_factory=list)


@dataclass
class Issue:
    """One in-scope issue, reduced to what dependency planning needs.

    `blocked_by` is the bare set of in/out-of-scope blockers used by the graph;
    `blocked_by_origin` records which keyword produced each edge for the plan's
    audit trail; `soft_notes` carries possible-coupling phrases for the report.
    """

    number: int
    title: str
    labels: list[str]
    blocked_by: set[int]
    blocked_by_origin: dict[int, str] = field(default_factory=dict)
    soft_notes: list[str] = field(default_factory=list)


@dataclass
class Verdict:
    """One sub-agent's outcome for one issue, as folded into the final report.

    `status` is one of DONE / PARKED / BLOCKED. The three list fields mirror
    the operating contract's report buckets and are de-duplicated across all
    issues when rendered.
    """

    number: int
    title: str
    status: str
    gates: str
    verify: str
    remaining_for_human: list[str]
    assumptions: list[str]
    blockers: list[str]


@dataclass
class Commit:
    """One commit on a branch, reduced to its SHA and the paths it touched."""

    sha: str
    files: list[str]


def fail(message: str) -> NoReturn:
    """Print an error to stderr and exit with code 1."""

    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def _scan_reference_region(body: str, start: int) -> list[int]:
    """Collect the issue numbers a hard-edge keyword governs, starting just past
    the keyword at `start`. References in the keyword's own clause are taken — the
    same-line remainder up to the next sentence terminator or the next hard/soft
    keyword (so a soft phrase sharing the line keeps its refs out). If the label
    stands alone, an immediately following bullet list of `#N` is consumed too
    (`**Depends on:**\\n- #44\\n- #45`). Scanning stops at the first line that is
    neither blank nor a bullet reference, so trailing prose and later unrelated
    lists are left out."""

    # Take the references in the keyword's own clause: the same-line remainder cut
    # at the first clause boundary, so a trailing soft phrase or a second keyword
    # on the line does not pull its refs into this edge.
    newline = body.find("\n", start)
    head = body[start:] if newline == -1 else body[start:newline]
    boundary = CLAUSE_BOUNDARY_RE.search(head)
    if boundary is not None:
        head = head[: boundary.start()]
    numbers = [int(number) for number in ISSUE_REF_RE.findall(head)]

    # Then walk the following lines: skip blanks, absorb bullet references, and
    # stop the moment a line is neither — that line begins unrelated content.
    rest = "" if newline == -1 else body[newline + 1 :]
    for line in rest.splitlines():
        if not line.strip():
            continue
        bullet = BULLET_REF_RE.match(line)
        if bullet is None:
            break
        numbers.append(int(bullet[1]))

    return numbers


def parse_dependencies(body: str, self_number: int | None = None) -> DependencySignals:
    """Derive the dependency signals from an issue body: hard blocking edges
    (with the keyword that produced each) and soft, non-directional coupling
    notes.

    Hard edges come from two sources treated identically: the heading-form
    `## Blocked by` section, and inline/labelled forms anywhere in the text
    (`Blocked by`, `Depends on`, `Depends upon`, `Requires`, `Needs`) followed
    by one or more `#N` — optionally bold-wrapped and optionally trailing into a
    bullet list. Vague phrases ("relates to", "touches the same files as") are
    recorded as soft notes only. A self-reference is never an edge.
    """

    text = body or ""
    edges: dict[int, str] = {}

    # Inline/labelled forms anywhere in the body. The keyword's canonical
    # spelling (not the author's casing) is recorded as the edge origin.
    for match in INLINE_EDGE_RE.finditer(text):
        keyword = next(
            canonical
            for canonical in HARD_EDGE_KEYWORDS
            if canonical.lower() == match["keyword"].lower()
        )
        for number in _scan_reference_region(text, match.end()):
            edges.setdefault(number, keyword)

    # The heading-form `## Blocked by` section: every reference under it is an
    # edge, attributed to "Blocked by" unless an inline keyword already claimed
    # it (so `- depends on #43` keeps its more specific origin).
    section = BLOCKED_BY_SECTION_RE.search(text)
    if section is not None:
        for number in ISSUE_REF_RE.findall(section["body"]):
            edges.setdefault(int(number), "Blocked by")

    # Non-directional coupling: visible as a soft note, never an edge. A ref
    # already claimed as a hard edge keeps its edge and is not down-graded.
    soft_notes: list[str] = []
    for match in SOFT_NOTE_RE.finditer(text):
        note = f"{match['phrase'].strip()} {match['refs'].strip()}".strip()
        soft_notes.append(re.sub(r"\s+", " ", note))

    # A self-reference cannot block its own issue; drop it from the edge set.
    if self_number is not None:
        edges.pop(self_number, None)

    return DependencySignals(edges=edges, soft_notes=soft_notes)


def parse_blocked_by(body: str, self_number: int | None = None) -> set[int]:
    """Extract the issue numbers that block an issue — from the `## Blocked by`
    heading section and from inline/labelled blocking forms anywhere in the
    body. Returns an empty set when none are present. A self-reference, when the
    issue's own number is supplied, is excluded."""

    return set(parse_dependencies(body, self_number).edges)


def load_issues(raw: str) -> list[Issue]:
    """Parse a `gh issue list --json number,title,labels,body` payload into
    Issue records. Raises ValueError on malformed JSON or a missing number."""

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"input is not valid JSON: {exc}") from exc

    if not isinstance(data, list):
        raise ValueError("expected a JSON array of issues")

    issues: list[Issue] = []
    for entry in data:
        # An issue with no number cannot be placed in the graph at all.
        if not isinstance(entry, dict) or "number" not in entry:
            raise ValueError("an issue entry is missing its 'number'")

        # gh nests labels as {"name": ...} objects; tolerate bare strings too.
        labels = [
            label["name"] if isinstance(label, dict) else str(label)
            for label in entry.get("labels", [])
        ]

        # Derive the hard edges (with provenance) and soft notes once, passing
        # the issue's own number so a self-reference is dropped as a blocker.
        number = int(entry["number"])
        signals = parse_dependencies(entry.get("body", ""), self_number=number)

        issues.append(
            Issue(
                number=number,
                title=str(entry.get("title", "")).strip(),
                labels=labels,
                blocked_by=set(signals.edges),
                blocked_by_origin=signals.edges,
                soft_notes=signals.soft_notes,
            )
        )

    return issues


def exclude_by_label(
    issues: list[Issue], exclude_labels: Iterable[str]
) -> tuple[list[Issue], list[Issue]]:
    """Partition issues into (kept, excluded) by label — a defensive second
    line behind the caller's `gh` query, so a `ready-for-human` issue that
    slips into scope is dropped rather than built autonomously."""

    excluded = {label.lower() for label in exclude_labels}
    kept: list[Issue] = []
    dropped: list[Issue] = []
    for issue in issues:
        present = {label.lower() for label in issue.labels}
        (dropped if excluded & present else kept).append(issue)
    return kept, dropped


def build_waves(issues: list[Issue]) -> list[list[int]]:
    """Topologically sort the issues into dispatch waves: wave 0 has no
    in-scope blocker, and each later wave depends only on earlier ones. Issues
    within a wave are independent and may run concurrently.

    Blockers pointing outside the scope are ignored here — an issue is not held
    back by a dependency that is not part of this run (those are surfaced
    separately by `external_dependencies`). Raises ValueError naming the
    offending issues when the in-scope graph contains a cycle.
    """

    in_scope = {issue.number for issue in issues}
    remaining = {
        issue.number: {blocker for blocker in issue.blocked_by if blocker in in_scope}
        for issue in issues
    }

    waves: list[list[int]] = []
    resolved: set[int] = set()
    while remaining:
        # A wave is every remaining issue whose in-scope blockers are all done.
        ready = sorted(
            number for number, blockers in remaining.items() if blockers <= resolved
        )
        if not ready:
            raise ValueError(f"dependency cycle among issues {sorted(remaining)}")

        # Commit the wave and drop its issues from the remaining graph.
        waves.append(ready)
        resolved.update(ready)
        for number in ready:
            del remaining[number]

    return waves


def external_dependencies(issues: list[Issue]) -> dict[int, list[int]]:
    """Map each issue to the blockers it references that are NOT in scope —
    work this run cannot complete on its own. The orchestrator surfaces these
    so a dependent is never merged ahead of a blocker the run never built."""

    in_scope = {issue.number for issue in issues}
    result: dict[int, list[int]] = {}
    for issue in issues:
        external = sorted(
            blocker for blocker in issue.blocked_by if blocker not in in_scope
        )
        if external:
            result[issue.number] = external
    return result


def dependency_edges(issues: list[Issue]) -> list[dict[str, Any]]:
    """List every in-scope blocking edge with its origin keyword, so an
    unattended run can be audited afterwards (`#45 -> #44 (from "Depends on")`).
    Edges to issues outside this run are surfaced by `external_dependencies`
    instead and are not repeated here."""

    in_scope = {issue.number for issue in issues}
    edges: list[dict[str, Any]] = []
    for issue in issues:
        for blocker in sorted(issue.blocked_by):
            if blocker in in_scope:
                edges.append(
                    {
                        "from": issue.number,
                        "to": blocker,
                        "origin": issue.blocked_by_origin.get(blocker, "Blocked by"),
                    }
                )
    return edges


def build_plan(
    kept: list[Issue], excluded: list[Issue], scope_label: str
) -> dict[str, Any]:
    """Assemble the plan the orchestrator dispatches from. The existing fields
    (`scope_label`, `issues`, `waves`, `external_dependencies`, `excluded`) are
    preserved verbatim for the Workflow engine that consumes this as its args;
    the dependency provenance, soft notes, and merge signal are added alongside.

    Raises ValueError (via `build_waves`) when the in-scope graph has a cycle.
    """

    waves = build_waves(kept)
    edges = dependency_edges(kept)

    # When any cross-issue edge exists, dependents must build on a base that
    # already contains their prerequisites — flag merge mode so the engine does
    # not branch them off bare `main` and N PRs over one file do not conflict.
    merge_required = bool(edges)
    soft_notes = [
        {"number": issue.number, "note": note}
        for issue in kept
        for note in issue.soft_notes
    ]

    return {
        "scope_label": scope_label,
        "issues": [
            {"number": i.number, "title": i.title, "blocked_by": sorted(i.blocked_by)}
            for i in kept
        ],
        "waves": waves,
        "dependency_edges": edges,
        "merge_required": merge_required,
        "merge_note": (
            "Intra-set dependencies detected; integrate with merge mode so "
            "dependents build on a base that includes their prerequisites."
            if merge_required
            else "No intra-set dependencies; one-PR-per-issue integration is safe."
        ),
        "soft_notes": soft_notes,
        "external_dependencies": external_dependencies(kept),
        "excluded": [
            {"number": i.number, "title": i.title, "labels": i.labels} for i in excluded
        ],
    }


def parse_git_log(text: str) -> list[Commit]:
    """Parse `git log --format='commit %H' --name-only` output (oldest first)
    into Commit records. A `commit <sha>` line opens a commit; every later
    non-blank line is a path it touched until the next `commit` line."""

    commits: list[Commit] = []
    for line in text.splitlines():
        # A marker line opens a new commit; anything else is one of its paths.
        if line.startswith("commit "):
            commits.append(Commit(sha=line[len("commit ") :].strip(), files=[]))
        elif line.strip() and commits:
            commits[-1].files.append(line.strip())
    return commits


def default_is_test(path: str) -> bool:
    """Recognise a path as test code by a conventional directory segment or
    filename. Used by `redgreen` when no --test-glob override is given."""

    parts = path.replace("\\", "/").split("/")
    if any(part.lower() in TEST_DIR_SEGMENTS for part in parts[:-1]):
        return True
    return bool(TEST_FILE_RE.match(parts[-1]))


def make_test_classifier(globs: list[str] | None) -> Callable[[str], bool]:
    """Build the predicate that decides whether a path is test code. With
    explicit globs it matches any of them; otherwise it falls back to the
    convention-based default."""

    if globs:
        return lambda path: any(fnmatch.fnmatch(path, glob) for glob in globs)
    return default_is_test


def assess_red_before_green(
    commits: list[Commit], is_test: Callable[[str], bool]
) -> dict[str, Any]:
    """Decide whether a branch demonstrates a failing test before the code: the
    first commit touching a test must come strictly before the first commit
    touching non-test (source) code.

    This is a structural guard, not proof the test failed — that stays with the
    verifier sub-agent. It cheaply catches the common anti-patterns: no test
    commit at all, or test and implementation landing in one commit so the red
    was never demonstrated on its own.
    """

    # Locate the first test-touching and first source-touching commit.
    red = next(
        (commit for commit in commits if any(is_test(path) for path in commit.files)),
        None,
    )
    green = next(
        (
            commit
            for commit in commits
            if any(not is_test(path) for path in commit.files)
        ),
        None,
    )

    # No test commit at all means the discipline cannot have been followed.
    if red is None:
        return {
            "demonstrated": False,
            "redCommit": None,
            "greenCommit": green.sha if green else None,
            "reason": "no commit touches a test file",
        }

    # A demonstrated red requires the test commit strictly before the source.
    red_index = commits.index(red)
    green_index = commits.index(green) if green else None
    demonstrated = green_index is not None and red_index < green_index
    if green_index is None:
        reason = "test committed, but no implementing commit found"
    elif red_index == green_index:
        reason = (
            "test and implementation landed in one commit; red not demonstrated alone"
        )
    elif demonstrated:
        reason = "test committed before the implementing commit"
    else:
        reason = "implementing commit precedes the test commit"

    return {
        "demonstrated": demonstrated,
        "redCommit": red.sha,
        "greenCommit": green.sha if green else None,
        "reason": reason,
    }


def load_verdicts(raw: str) -> list[Verdict]:
    """Parse the orchestrator's per-issue verdicts JSON into Verdict records.
    Missing list fields default to empty; an unknown status is kept verbatim so
    the report surfaces it rather than silently reclassifying it."""

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"input is not valid JSON: {exc}") from exc

    if not isinstance(data, list):
        raise ValueError("expected a JSON array of verdicts")

    def strings(entry: dict[str, Any], key: str) -> list[str]:
        value = entry.get(key, [])
        return [str(item) for item in value] if isinstance(value, list) else []

    verdicts: list[Verdict] = []
    for entry in data:
        # A verdict without a number cannot be attributed to an issue.
        if not isinstance(entry, dict) or "number" not in entry:
            raise ValueError("a verdict entry is missing its 'number'")

        verdicts.append(
            Verdict(
                number=int(entry["number"]),
                title=str(entry.get("title", "")).strip(),
                status=str(entry.get("status", DONE)).strip().lower(),
                gates=str(entry.get("gates", "")).strip(),
                verify=str(entry.get("verify", "")).strip(),
                remaining_for_human=strings(entry, "remaining_for_human"),
                assumptions=strings(entry, "assumptions"),
                blockers=strings(entry, "blockers"),
            )
        )

    return verdicts


def dedupe(items: Iterable[str]) -> list[str]:
    """De-duplicate strings case-insensitively while preserving first-seen
    order, dropping blanks. Used to collapse the same human follow-up reported
    by several issues into one line."""

    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.strip()
        if key and key.lower() not in seen:
            seen.add(key.lower())
            result.append(key)
    return result


def render_report(verdicts: list[Verdict]) -> str:
    """Render the consolidated Markdown report: shipped-and-green issues first,
    then the de-duplicated work left for a human, then assumptions and the
    parked or blocked issues — the order the operating contract prescribes."""

    done = [v for v in verdicts if v.status == DONE]
    parked = [v for v in verdicts if v.status == PARKED]
    blocked = [v for v in verdicts if v.status == BLOCKED]
    other = [v for v in verdicts if v.status not in (DONE, PARKED, BLOCKED)]

    lines: list[str] = ["# Orchestration report", ""]

    # Lead with the headline counts so the outcome is legible at a glance.
    lines.append(
        f"{len(done)} done and green · {len(parked)} parked · "
        f"{len(blocked)} blocked · {len(verdicts)} total"
    )
    lines.append("")

    # The shipped work: one line per issue with its gate and verify result.
    lines.append("## Done and green")
    lines.append("")
    if done:
        for verdict in done:
            gates = f" — gates: {verdict.gates}" if verdict.gates else ""
            verify = f" — {verdict.verify}" if verdict.verify else ""
            lines.append(f"- #{verdict.number} {verdict.title}{gates}{verify}")
    else:
        lines.append("- Nothing shipped.")
    lines.append("")

    # The irreducibly human follow-ups, collapsed across every issue.
    remaining = dedupe(
        item for verdict in verdicts for item in verdict.remaining_for_human
    )
    lines.append("## Remaining for a human")
    lines.append("")
    lines.extend([f"- {item}" for item in remaining] if remaining else ["- None."])
    lines.append("")

    # Assumptions made under the no-blocking contract, attributed to their issue.
    assumptions = [
        f"#{verdict.number}: {item}"
        for verdict in verdicts
        for item in verdict.assumptions
    ]
    lines.append("## Assumptions")
    lines.append("")
    lines.extend([f"- {item}" for item in assumptions] if assumptions else ["- None."])
    lines.append("")

    # The issues that did not finish, each with why, so the maintainer can act.
    lines.append("## Blockers and parked issues")
    lines.append("")
    stuck = parked + blocked + other
    if stuck:
        for verdict in stuck:
            reasons = "; ".join(verdict.blockers) or "no reason recorded"
            lines.append(
                f"- #{verdict.number} {verdict.title} ({verdict.status}) — {reasons}"
            )
    else:
        lines.append("- None.")

    return "\n".join(lines)


def cmd_plan(args: argparse.Namespace) -> int:
    """Run the `plan` subcommand — read issues JSON from stdin, build the
    dependency graph and dispatch waves, and print the plan as JSON."""

    try:
        issues = load_issues(sys.stdin.read())
    except ValueError as exc:
        fail(str(exc))

    kept, excluded = exclude_by_label(issues, args.exclude_label or [])

    try:
        plan = build_plan(kept, excluded, args.scope_label)
    except ValueError as exc:
        fail(str(exc))

    print(json.dumps(plan, indent=2))
    return 0


def cmd_redgreen(args: argparse.Namespace) -> int:
    """Run the `redgreen` subcommand — read `git log` output from stdin and
    print a JSON verdict on whether the branch demonstrates red before green."""

    commits = parse_git_log(sys.stdin.read())
    is_test = make_test_classifier(args.test_glob)
    print(json.dumps(assess_red_before_green(commits, is_test), indent=2))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Run the `report` subcommand — read per-issue verdicts JSON from stdin
    and print the consolidated Markdown report."""

    try:
        verdicts = load_verdicts(sys.stdin.read())
    except ValueError as exc:
        fail(str(exc))

    print(render_report(verdicts))
    return 0


def main() -> int:
    """Parse arguments, dispatch to the chosen subcommand, return its code."""

    parser = argparse.ArgumentParser(
        description="Deterministic orchestration mechanics for the orchestrate skill.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser(
        "plan", help="Build the dependency graph and dispatch waves from issues JSON."
    )
    plan_parser.add_argument(
        "--scope-label",
        default=DEFAULT_SCOPE_LABEL,
        help=f"Label the scope was resolved from (default: {DEFAULT_SCOPE_LABEL}).",
    )
    plan_parser.add_argument(
        "--exclude-label",
        action="append",
        metavar="LABEL",
        help="Drop any issue carrying this label (repeatable); use for "
        "ready-for-human as a defensive second line.",
    )
    plan_parser.set_defaults(func=cmd_plan)

    redgreen_parser = subparsers.add_parser(
        "redgreen",
        help="Check a branch demonstrates a failing test before the code.",
    )
    redgreen_parser.add_argument(
        "--test-glob",
        action="append",
        metavar="GLOB",
        help="Treat paths matching this glob as test code (repeatable); "
        "overrides the built-in convention-based detection.",
    )
    redgreen_parser.set_defaults(func=cmd_redgreen)

    report_parser = subparsers.add_parser(
        "report", help="Render the consolidated final report from verdicts JSON."
    )
    report_parser.set_defaults(func=cmd_report)

    # argparse sets `func` dynamically, so its type is opaque; the cast
    # restores the int return contract every cmd_* function already honours.
    args = parser.parse_args()
    return cast(int, args.func(args))


if __name__ == "__main__":
    sys.exit(main())
