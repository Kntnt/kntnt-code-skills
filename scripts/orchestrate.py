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

  * `plan`     <- `gh issue list --json number,title,labels,body,comments`
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

# A triage-posted agent brief opens with a Markdown "Agent Brief" heading. An
# issue HAS a brief iff a comment body carries that heading; an issue without one
# is flagged so the run knows it is built from its body + acceptance criteria
# instead. The match is anchored to the heading form (`#{1,6}` at a line start),
# not a bare substring, so a prose mention ("no Agent Brief was posted") does not
# falsely clear the flag. Case-insensitive and multiline (each comment body may
# hold several lines); `\b` after "Brief" keeps "Agent Briefing" from matching.
AGENT_BRIEF_HEADING_RE = re.compile(
    r"^\s*#{1,6}\s*Agent Brief\b", re.IGNORECASE | re.MULTILINE
)

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

# A single bullet-list item carrying arbitrary content, used to peel the marker
# off a prose-title bullet (`- User schema migration`) before normalising it.
# `#N` bullets are still read by BULLET_REF_RE; this only reaches the prose ones.
BULLET_CONTENT_RE = re.compile(r"^\s*[-*]\s+(?P<content>.+?)\s*$")

# The shortest a normalised title may be and still be matched. A one- or
# two-character title ("A", "CI") would collide with stray prose, so anything
# below this length is dropped from the title index rather than risk a false
# edge — the "a very short or empty title should never match" guard.
MIN_TITLE_MATCH_LEN = 3

# An explicit "None ..." in a dependency region is a deliberate no-dependency
# statement, not unresolved content — so it must never raise the unresolved
# warning. Anchored at the start of a region line's stripped text.
NONE_SENTINEL_RE = re.compile(r"none\b", re.IGNORECASE)

# The shared tail of every unresolved-dependency warning — raised when a
# dependency region (the `## Blocked by` section or a genuine inline label)
# carries real content yet yields no resolvable reference, the silent-empty-graph
# failure this issue exists to make loud. `_unresolved_region_warning` prefixes
# the region that produced it; `build_plan` further prefixes the issue number.
UNRESOLVED_WARNING_TAIL = (
    "has content but resolved to zero issue references "
    "(a prerequisite named by prose may not match any known issue title)"
)

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

# The ambition levels and the default, mirroring the `--level` dial documented in
# skills/orchestrate/SKILL.md. The level sets the verification-rigor baseline
# below; the derivation of a per-role (model, effort) from it is the
# orchestrator's job, not this deterministic helper's.
LEVELS = ("XS", "S", "M", "L", "XL")
DEFAULT_LEVEL = "M"

# The fixed, model-agnostic rigor ladder (ADR-0001 §5). Each rank is one
# (lens count, fix-round cap) tier: rank 0 is the XS/S/M baseline, rank 1 the L
# tier, rank 2 the XL tier. Per-issue risk escalates a lower rank UP this same
# ladder (§6, escalate-only) and never below it — rank 0 is the inviolable floor
# (≥ 1 adversarial lens, 1 fix round). Only an explicit `--max-fix-rounds=0`
# reaches zero rounds; no level defaults to it.
RIGOR_TIERS = (
    {"lenses": 1, "fix_rounds": 1},
    {"lenses": 2, "fix_rounds": 2},
    {"lenses": 3, "fix_rounds": 2},
)

# Each ambition level's baseline rank on RIGOR_TIERS (ADR-0001 §5).
LEVEL_RANK = {"XS": 0, "S": 0, "M": 0, "L": 1, "XL": 2}

# An explicit risk signal's rank on the same ladder — the escalate-only mapping
# from a `Risk:` marker or a `risk:*` label to rigor (ADR-0001 §6). `low` adds no
# escalation (baseline); `medium` escalates to the L tier; `high` to the XL tier
# and, because rigor is the highest signal, is a floor the result never undercuts.
RISK_RANK = {"low": 0, "medium": 1, "high": 2}

# The verifier focus each lens carries at a given tier, mirroring ADR-0001 §5's
# C(orrectness) / T(est-quality) / S(ecurity) grouping: one broad lens folds all
# three, two split [C+T] from [S], three separate them. These are the
# deterministic skeleton the engine's `lensesFor` consumes unchanged; the
# orchestrator tailors each brief's prose to the issue (the specific hazard to
# hunt, the L second lens's T-vs-S swap) — lens-content tailoring is its job, the
# lens COUNT is settled here.
LENS_BROAD = (
    "broad adversarial review: correctness against the issue intent and its "
    "acceptance criteria, test quality, and any security or data-safety hazard "
    "the issue touches"
)
LENS_CORRECTNESS_AND_TESTS = (
    "correctness against the issue intent and its acceptance criteria, and the "
    "quality of the tests"
)
LENS_SECURITY = "any security or data-safety hazard the issue touches"
LENS_CORRECTNESS = "correctness against the issue intent and its acceptance criteria"
LENS_TESTS = (
    "test quality: the red is demonstrated, the tests are load-bearing, and every "
    "acceptance criterion maps to a test"
)
LENSES_BY_RANK = (
    [LENS_BROAD],
    [LENS_CORRECTNESS_AND_TESTS, LENS_SECURITY],
    [LENS_CORRECTNESS, LENS_TESTS, LENS_SECURITY],
)

# A deliberate `Risk: high | medium | low` marker in an issue body or its Agent
# Brief. Matched anywhere, because the brief writes it inline (`Agent Brief
# (Risk: medium):`), tolerating a bold wrapper (`**Risk:** high`, `**Risk**:
# high`); the immediately following level word is required, so ordinary prose
# ("the risk: it might fail") is not a marker. Case-insensitive.
RISK_MARKER_RE = re.compile(
    r"\bRisk\b[^\S\n]*\*{0,2}[^\S\n]*:[^\S\n]*\*{0,2}[^\S\n]*(high|medium|low)\b",
    re.IGNORECASE,
)

# The optional `risk:high|medium|low` label — the board-visibility convenience
# channel (ADR-0001 §6), an explicit hazard signal that feeds the escalate-only
# max alongside the marker. Matched against the whole label name.
RISK_LABEL_RE = re.compile(r"^risk:(high|medium|low)$", re.IGNORECASE)


@dataclass
class DependencySignals:
    """The dependency signals extracted from one issue body.

    `edges` maps each blocking issue number to the keyword that produced it
    (the audit trail an unattended run is inspected by). `soft_notes` holds the
    non-directional coupling phrases that must stay visible but never block.
    `warnings` holds body-scoped alerts — a dependency region with real content
    that resolved to nothing — so a silently-empty graph is made loud.
    """

    edges: dict[int, str] = field(default_factory=dict)
    soft_notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Issue:
    """One in-scope issue, reduced to what dependency planning needs.

    `blocked_by` is the bare set of in/out-of-scope blockers used by the graph;
    `blocked_by_origin` records which keyword produced each edge for the plan's
    audit trail; `soft_notes` carries possible-coupling phrases for the report;
    `warnings` carries body-scoped unresolved-dependency alerts for the plan.
    `no_brief` flags an issue that carries no Agent Brief comment, so the plan
    surfaces which issues are built from their body + acceptance criteria rather
    than a posted brief. It defaults to True — an issue with no detectable brief
    — so a record built without comment data is flagged rather than silently
    assumed to have one; the engine's fallback still builds it either way.
    `risk_marker` is the explicit `Risk:` signal read from the body or the Agent
    Brief (`high`/`medium`/`low`, or None when absent), one input to the rigor
    derivation; the `risk:*` label is read from `labels` at plan time.
    """

    number: int
    title: str
    labels: list[str]
    blocked_by: set[int]
    blocked_by_origin: dict[int, str] = field(default_factory=dict)
    soft_notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    no_brief: bool = True
    risk_marker: str | None = None


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


@dataclass
class _RegionScan:
    """The outcome of scanning a hard-edge keyword's governed region: the issue
    `numbers` it resolved (by `#N` or title), and whether the region carried any
    real content at all. `had_content` distinguishes an unresolved dependency
    (content present, nothing resolved — worth a warning) from an empty label
    (nothing to resolve, no warning)."""

    numbers: list[int]
    had_content: bool


def _is_meaningful(text: str) -> bool:
    """Whether a region line carries a real dependency claim — non-blank and not
    an explicit "None ..." statement — used to decide whether an unresolved
    region should warn and whether a region has content at all."""

    stripped = text.strip()
    return bool(stripped) and not NONE_SENTINEL_RE.match(stripped)


def _scan_reference_region(
    body: str, start: int, title_index: dict[str, int] | None = None
) -> _RegionScan:
    """Collect the issue numbers a hard-edge keyword governs, starting just past
    the keyword at `start`. References in the keyword's own clause are taken — the
    same-line remainder up to the next sentence terminator or the next hard/soft
    keyword (so a soft phrase sharing the line keeps its refs out). If the label
    stands alone, an immediately following bullet list of `#N` is consumed too
    (`**Depends on:**\\n- #44\\n- #45`), and if the next non-blank line is plain
    prose it is read as the keyword's continuation — its first clause supplies the
    refs (`Depends on\\nthe #44 schema.`), the conservative reach issue #10 asks
    for. Scanning stops at the first line that is neither blank nor a bullet (and,
    once any ref is in hand, the prose-continuation reach is not taken), so
    trailing prose and later unrelated lists are left out.

    When `title_index` is supplied (the caller passes it only for a genuine label
    form), a governed piece with no `#N` is also resolved by exact title match,
    so `**Depends on:** User schema migration` and a bullet list of prose titles
    become edges. Passing None keeps the pure-`#N` behaviour byte-for-byte. The
    returned `had_content` reports whether the region held any real text, so the
    caller can warn on a label that carried a claim yet resolved to nothing."""

    # Take the references in the keyword's own clause: the same-line remainder cut
    # at the first clause boundary, so a trailing soft phrase or a second keyword
    # on the line does not pull its refs into this edge. With no `#N`, a label's
    # own line may name its prerequisite by title instead.
    newline = body.find("\n", start)
    head = body[start:] if newline == -1 else body[start:newline]
    numbers = _refs_in_first_clause(head)
    if not numbers and title_index:
        head_title = _title_number(_first_clause(head), title_index)
        if head_title is not None:
            numbers.append(head_title)
    had_content = _is_meaningful(head)

    # Then walk the following lines: skip blanks, absorb bullet references, and
    # stop the moment a line is neither. A `#N` bullet is consumed as before; a
    # prose-title bullet resolves by title and the list continues; when nothing
    # has matched yet, the first non-bullet prose line is the keyword's
    # continuation — its clause supplies the ref (by `#N` or, failing that, by
    # title) before scanning stops. Any non-blank piece seen marks the region as
    # having content, so an unresolved-but-non-empty label can be warned about.
    rest = "" if newline == -1 else body[newline + 1 :]
    for line in rest.splitlines():
        if not line.strip():
            continue
        bullet_content = BULLET_CONTENT_RE.match(line)
        piece = bullet_content["content"] if bullet_content is not None else line
        if _is_meaningful(piece):
            had_content = True
        bullet = BULLET_REF_RE.match(line)
        if bullet is not None:
            numbers.append(int(bullet[1]))
            continue
        if title_index and bullet_content is not None:
            bullet_title = _title_number(
                _first_clause(bullet_content["content"]), title_index
            )
            if bullet_title is not None:
                numbers.append(bullet_title)
                continue
        if not numbers:
            refs = _refs_in_first_clause(line)
            if not refs and title_index:
                line_title = _title_number(_first_clause(line), title_index)
                if line_title is not None:
                    refs = [line_title]
            numbers.extend(refs)
        break

    return _RegionScan(numbers=numbers, had_content=had_content)


def _first_clause(line: str) -> str:
    """Return the first clause of `line` — the run up to the first clause
    boundary (a sentence terminator, or the start of the next hard keyword or
    soft phrase). Cutting here keeps a soft phrase or a second keyword sharing
    the line from being read as part of the current clause."""

    boundary = CLAUSE_BOUNDARY_RE.search(line)
    return line if boundary is None else line[: boundary.start()]


def _refs_in_first_clause(line: str) -> list[int]:
    """Return the `#N` references in the first clause of `line`, so a soft phrase
    or a second keyword sharing the line does not pull its refs into this edge."""

    return [int(number) for number in ISSUE_REF_RE.findall(_first_clause(line))]


def normalize_title(title: str) -> str:
    """Reduce a title to its matching key: internal whitespace collapsed,
    lowercased, surrounding emphasis markers removed, and trailing punctuation
    stripped — so `**User schema migration.**`, `- User schema migration`, and
    `User schema migration` all compare equal. The key is compared for exact
    equality against the title index; it is never matched as a substring."""

    collapsed = re.sub(r"\s+", " ", title).strip().lower()
    return collapsed.strip("*_ ").rstrip(".,;:!?-–— ")


def _title_number(text: str, title_index: dict[str, int]) -> int | None:
    """Resolve `text` to an issue number when it is an exact normalised-title
    match, else None. Titles shorter than MIN_TITLE_MATCH_LEN never match, so a
    stray one- or two-character clause cannot mint an edge."""

    key = normalize_title(text)
    if len(key) < MIN_TITLE_MATCH_LEN:
        return None
    return title_index.get(key)


def _unresolved_region_warning(region: str) -> str:
    """Warning text for a dependency region that carries real content yet
    resolves to zero references. `region` names what produced it (e.g. `Blocked
    by section`, `'Depends on' label`); `build_plan` prefixes the issue number."""

    return f"{region} {UNRESOLVED_WARNING_TAIL}"


def _region_has_content(region: str) -> bool:
    """Whether a dependency region carries real bullet or prose content — a line
    that is neither blank nor an explicit "None ..." statement. This gates the
    unresolved-dependency warning so an empty or deliberately-none section stays
    quiet."""

    for line in region.splitlines():
        bullet = BULLET_CONTENT_RE.match(line)
        content = bullet["content"] if bullet is not None else line
        if _is_meaningful(content):
            return True
    return False


def _section_has_any_reference(region: str, title_index: dict[str, int] | None) -> bool:
    """Whether a dependency region resolves to at least one reference — a `#N`
    anywhere, or (when a title index is given) a line that exactly matches a
    known title. Used only to decide whether to warn, so it is deliberately
    permissive about `#N`: an out-of-scope or self number still counts as the
    author having named a real reference."""

    if ISSUE_REF_RE.search(region):
        return True
    if title_index:
        for line in region.splitlines():
            bullet = BULLET_CONTENT_RE.match(line)
            piece = bullet["content"] if bullet is not None else line.strip()
            if _title_number(piece, title_index) is not None:
                return True
    return False


def parse_dependencies(
    body: str,
    self_number: int | None = None,
    title_index: dict[str, int] | None = None,
) -> DependencySignals:
    """Derive the dependency signals from an issue body: hard blocking edges
    (with the keyword that produced each), soft non-directional coupling notes,
    and warnings for a dependency region that has content but resolves to
    nothing.

    Hard edges come from two sources treated identically: the heading-form
    `## Blocked by` section, and inline/labelled forms anywhere in the text
    (`Blocked by`, `Depends on`, `Depends upon`, `Requires`, `Needs`) followed
    by one or more `#N` — optionally bold-wrapped and optionally trailing into a
    bullet list. Vague phrases ("relates to", "touches the same files as") are
    recorded as soft notes only. A self-reference is never an edge.

    When `title_index` (a normalised title -> number map of the in-scope issues)
    is supplied, a prerequisite named by its exact prose title — with no `#N` —
    also becomes an edge, but ONLY inside these same dependency regions: the
    heading section, and inline forms that read as a genuine label — bold-wrapped
    (`**Depends on:**`, `**Depends on**`) or colon-bearing (`Depends on:`). A
    bare keyword used as an ordinary verb ("this work needs review") is not a
    label and resolves no title. A title mentioned anywhere else in the body
    produces no edge. When a dependency region — the `## Blocked by` section or a
    genuine inline label — has real content yet resolves to zero references, a
    warning is raised so the otherwise-silent empty graph is made loud.
    """

    text = body or ""
    edges: dict[int, str] = {}
    warnings: list[str] = []

    # Inline/labelled forms anywhere in the body. The keyword's canonical spelling
    # (not the author's casing) is recorded as the edge origin. A match counts as
    # a genuine label only when bold-wrapped or colon-bearing — an ordinary prose
    # verb ("this work needs review") is not. Bare `#N` extraction runs for every
    # match regardless; only title resolution and the unresolved-region warning
    # are gated on the label test, so a stray title-shaped clause after a prose
    # verb cannot mint a false edge and prose keywords never warn.
    for match in INLINE_EDGE_RE.finditer(text):
        keyword = next(
            canonical
            for canonical in HARD_EDGE_KEYWORDS
            if canonical.lower() == match["keyword"].lower()
        )
        is_label = "*" in match.group() or ":" in match.group()
        region_titles = title_index if is_label else None
        scan = _scan_reference_region(text, match.end(), region_titles)
        for number in scan.numbers:
            edges.setdefault(number, keyword)
        if is_label and not scan.numbers and scan.had_content:
            warnings.append(_unresolved_region_warning(f"'{keyword}' label"))

    # The heading-form `## Blocked by` section: every `#N` under it is an edge,
    # attributed to "Blocked by" unless an inline keyword already claimed it (so
    # `- depends on #43` keeps its more specific origin). A prerequisite named
    # only by its prose title is recovered by exact match against the title
    # index, per line so a whole normalised bullet or paragraph must equal a
    # known title. A section with content that resolves to nothing warns.
    section = BLOCKED_BY_SECTION_RE.search(text)
    if section is not None:
        section_body = section["body"]
        for number in ISSUE_REF_RE.findall(section_body):
            edges.setdefault(int(number), "Blocked by")
        if title_index:
            for line in section_body.splitlines():
                bullet = BULLET_CONTENT_RE.match(line)
                piece = bullet["content"] if bullet is not None else line.strip()
                title_number = _title_number(piece, title_index)
                if title_number is not None:
                    edges.setdefault(title_number, "Blocked by")
        if _region_has_content(section_body) and not _section_has_any_reference(
            section_body, title_index
        ):
            warnings.append(_unresolved_region_warning("Blocked by section"))

    # Non-directional coupling: visible as a soft note, never an edge. A ref
    # already claimed as a hard edge keeps its edge and is not down-graded.
    soft_notes: list[str] = []
    for match in SOFT_NOTE_RE.finditer(text):
        note = f"{match['phrase'].strip()} {match['refs'].strip()}".strip()
        soft_notes.append(re.sub(r"\s+", " ", note))

    # A self-reference cannot block its own issue; drop it from the edge set.
    if self_number is not None:
        edges.pop(self_number, None)

    return DependencySignals(edges=edges, soft_notes=soft_notes, warnings=warnings)


def parse_blocked_by(body: str, self_number: int | None = None) -> set[int]:
    """Extract the issue numbers that block an issue — from the `## Blocked by`
    heading section and from inline/labelled blocking forms anywhere in the
    body. Returns an empty set when none are present. A self-reference, when the
    issue's own number is supplied, is excluded."""

    return set(parse_dependencies(body, self_number).edges)


def _build_title_index(entries: list[Any]) -> dict[str, int]:
    """Build the normalised title -> number map that lets one issue's body
    resolve a prerequisite named by another's prose title. Titles too short to
    match safely are dropped; a title that two issues share is dropped entirely,
    because an ambiguous match would attach the edge to the wrong prerequisite.
    Malformed entries are skipped here — `load_issues` raises on them."""

    index: dict[str, int] = {}
    ambiguous: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or "number" not in entry:
            continue
        key = normalize_title(str(entry.get("title", "")))
        if len(key) < MIN_TITLE_MATCH_LEN:
            continue
        number = int(entry["number"])
        existing = index.get(key)
        if existing is not None and existing != number:
            ambiguous.add(key)
        index[key] = number

    for key in ambiguous:
        index.pop(key, None)
    return index


def _has_agent_brief(comments: Any) -> bool:
    """Whether any comment carries a Markdown "Agent Brief" heading. `gh` returns
    `comments` as a list of {"body": ...} objects; bare strings are tolerated,
    and a missing or non-list value is treated as no brief — the safe default,
    since the engine's fallback builds the issue from its body either way. The
    heading anchor (not a bare substring) keeps a prose mention of the phrase from
    falsely marking the issue as briefed."""

    if not isinstance(comments, list):
        return False
    for comment in comments:
        body = comment.get("body", "") if isinstance(comment, dict) else comment
        if AGENT_BRIEF_HEADING_RE.search(str(body)):
            return True
    return False


def _comment_texts(comments: Any) -> list[str]:
    """The text of every comment body, tolerating bare-string comments; a missing
    or non-list `comments` yields nothing. Lets the risk-marker scan reach the
    Agent Brief comment, where the `Risk:` marker usually lives, alongside the
    issue body."""

    if not isinstance(comments, list):
        return []
    return [
        str(comment.get("body", "")) if isinstance(comment, dict) else str(comment)
        for comment in comments
    ]


def load_issues(raw: str) -> list[Issue]:
    """Parse a `gh issue list --json number,title,labels,body,comments` payload
    into Issue records. Raises ValueError on malformed JSON or a missing number.

    Runs in two passes: first the in-scope titles are indexed, then each body is
    parsed against that index so a prerequisite named by its prose title (not
    `#N`) still produces an edge. The optional `comments` field, when present, is
    scanned for an Agent Brief so `no_brief` flags an issue lacking one; an entry
    with no `comments` field is flagged as having no detectable brief."""

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"input is not valid JSON: {exc}") from exc

    if not isinstance(data, list):
        raise ValueError("expected a JSON array of issues")

    title_index = _build_title_index(data)

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

        # Derive the hard edges (with provenance), soft notes, and warnings once,
        # passing the issue's own number so a self-reference is dropped as a
        # blocker, and the shared title index so prose-named prerequisites edge.
        number = int(entry["number"])
        signals = parse_dependencies(
            entry.get("body", ""), self_number=number, title_index=title_index
        )

        # Read the explicit `Risk:` marker from the body and the Agent Brief
        # comment together — the deterministic risk input to the rigor derivation
        # at plan time (prose risk inference is the orchestrator's job, not ours).
        risk_source = "\n".join(
            [str(entry.get("body", "") or ""), *_comment_texts(entry.get("comments"))]
        )

        issues.append(
            Issue(
                number=number,
                title=str(entry.get("title", "")).strip(),
                labels=labels,
                blocked_by=set(signals.edges),
                blocked_by_origin=signals.edges,
                soft_notes=signals.soft_notes,
                warnings=signals.warnings,
                no_brief=not _has_agent_brief(entry.get("comments")),
                risk_marker=parse_risk_marker(risk_source),
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


def parse_risk_marker(text: str) -> str | None:
    """Return the risk level named by a `Risk:` marker in `text` — the highest if
    several appear (escalate-only) — or None when there is no deliberate marker.

    A `Risk:` word not followed by `high`/`medium`/`low` is not a signal; the
    caller then rounds up to the level baseline rather than below it (ADR-0001
    §6, "round up on uncertainty")."""

    found = [match.group(1).lower() for match in RISK_MARKER_RE.finditer(text or "")]
    if not found:
        return None
    return max(found, key=lambda level: RISK_RANK[level])


def risk_label(labels: Iterable[str]) -> str | None:
    """Return the risk level named by a `risk:*` label — the highest if several —
    or None. The label is the optional convenience hazard channel of ADR-0001
    §6, an explicit signal that feeds the escalate-only max alongside the marker."""

    found = [
        match.group(1).lower()
        for label in labels
        if (match := RISK_LABEL_RE.match(label.strip()))
    ]
    if not found:
        return None
    return max(found, key=lambda level: RISK_RANK[level])


@dataclass
class RigorResult:
    """The verification rigor derived for one issue: the `lenses` its verifier
    panel runs (the engine consumes this array unchanged), the `fix_rounds` cap
    its risk tier warrants, and any `warnings` — an explicit low marker
    contradicted by a hazard label, surfaced rather than silently applied."""

    lenses: list[str]
    fix_rounds: int
    warnings: list[str] = field(default_factory=list)


def derive_rigor(
    level: str, marker_risk: str | None, label_risk: str | None
) -> RigorResult:
    """Derive an issue's verification rigor from the run `level` and its explicit
    risk signals, per ADR-0001 §5–§6.

    Escalate-only: the rigor rank is the highest of the level baseline, the
    `Risk:` marker, and the `risk:*` label. An explicit `high` is therefore a
    floor the result never undercuts; an absent or ambiguous signal contributes
    nothing, so the result rounds up to the level baseline and never below the
    inviolable floor (rank 0 — one adversarial lens, one fix round). When an
    explicit `Risk: low` marker is contradicted by a hazard label (`risk:medium`
    or `risk:high`), the low is NOT silently applied: the hazard still escalates
    the rigor and the disagreement is reported for the maintainer (ADR-0001 §6,
    "never silently if the planner still sees a hazard")."""

    rank = max(
        LEVEL_RANK[level],
        RISK_RANK[marker_risk] if marker_risk else 0,
        RISK_RANK[label_risk] if label_risk else 0,
    )

    # An explicit low marker that clashes with a hazard label is a genuine
    # disagreement: the hazard wins (above), but the maintainer is told rather
    # than the low being silently honoured.
    warnings: list[str] = []
    if marker_risk == "low" and label_risk in ("medium", "high"):
        warnings.append(
            f"explicit 'Risk: low' marker disagrees with a 'risk:{label_risk}' "
            "hazard label; escalating to the hazard rather than silently applying "
            "the low marker"
        )

    return RigorResult(
        lenses=list(LENSES_BY_RANK[rank]),
        fix_rounds=RIGOR_TIERS[rank]["fix_rounds"],
        warnings=warnings,
    )


def build_plan(
    kept: list[Issue],
    excluded: list[Issue],
    scope_label: str,
    level: str = DEFAULT_LEVEL,
    max_fix_rounds: int | None = None,
) -> dict[str, Any]:
    """Assemble the plan the orchestrator dispatches from. The existing fields
    (`scope_label`, `issues`, `waves`, `external_dependencies`, `excluded`) are
    preserved verbatim for the Workflow engine that consumes this as its args;
    the dependency provenance, soft notes, merge signal, unresolved-dependency
    warnings, and the missing-brief flags are added alongside. Each `issues[]`
    entry carries a `no_brief` boolean, and `issues_without_brief` lists the
    numbers lacking a brief for convenience — those issues are still built, from
    their body + acceptance criteria.

    `level` (the `--level` ambition dial) and each issue's explicit risk drive
    the verification rigor per ADR-0001 §5–§6: every `issues[]` entry gains a
    `lenses` array (its verifier panel, consumed by the engine's `lensesFor`
    unchanged), and the plan carries the derived run-level `maxFixRounds` cap and
    the echoed `level`. `max_fix_rounds`, when given, overrides the derived cap —
    the only way to reach `0` rounds (a scan/triage run); otherwise the cap is
    the highest an in-scope issue's risk tier warrants, floored at 1. An explicit
    `Risk: low` marker contradicted by a `risk:*` hazard label is surfaced in
    `warnings` rather than silently applied.

    Raises ValueError (via `build_waves`) when the in-scope graph has a cycle.
    """

    waves = build_waves(kept)
    edges = dependency_edges(kept)

    # The in-scope issues that carry no Agent Brief comment. They are still built
    # — from their body + acceptance criteria — so this is a visibility flag, not
    # an exclusion.
    issues_without_brief = sorted(issue.number for issue in kept if issue.no_brief)

    # When any cross-issue edge exists, dependents must build on a base that
    # already contains their prerequisites — flag merge mode so the engine does
    # not branch them off bare `main` and N PRs over one file do not conflict.
    merge_required = bool(edges)
    soft_notes = [
        {"number": issue.number, "note": note}
        for issue in kept
        for note in issue.soft_notes
    ]

    # Derive each issue's verification rigor from the level baseline and its
    # explicit risk signals (marker + label), escalate-only per ADR-0001 §5–§6.
    # The lens panel is per-issue; the fix-round cap is one run-level number, so
    # it takes the highest cap any issue's tier warrants (a risk-escalated issue
    # gets its rounds; the loop still exits early for the calmer ones). The level
    # baseline seeds the max so an empty run still floors at the level's rounds.
    rigor = {
        issue.number: derive_rigor(level, issue.risk_marker, risk_label(issue.labels))
        for issue in kept
    }
    derived_fix_rounds = max(
        [RIGOR_TIERS[LEVEL_RANK[level]]["fix_rounds"]]
        + [result.fix_rounds for result in rigor.values()]
    )
    resolved_fix_rounds = (
        max_fix_rounds if max_fix_rounds is not None else derived_fix_rounds
    )

    # Surface every unresolved-dependency warning and every risk disagreement at
    # the top level, prefixed with the issue it came from, so a section whose
    # prose named a prerequisite that matched nothing — or an explicit low that
    # clashes with a hazard label — is loud rather than silently swallowed.
    warnings = [
        f"#{issue.number}: {warning}"
        for issue in kept
        for warning in (*issue.warnings, *rigor[issue.number].warnings)
    ]

    return {
        "scope_label": scope_label,
        "level": level,
        "maxFixRounds": resolved_fix_rounds,
        "issues": [
            {
                "number": i.number,
                "title": i.title,
                "blocked_by": sorted(i.blocked_by),
                "no_brief": i.no_brief,
                "lenses": rigor[i.number].lenses,
            }
            for i in kept
        ],
        "issues_without_brief": issues_without_brief,
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
        "warnings": warnings,
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

    # `0` fix rounds is a deliberate scan/triage choice; a negative cap is not a
    # meaningful rigor and would silently disable the fix loop, so reject it.
    if args.max_fix_rounds is not None and args.max_fix_rounds < 0:
        fail("--max-fix-rounds must be zero or greater")

    try:
        issues = load_issues(sys.stdin.read())
    except ValueError as exc:
        fail(str(exc))

    kept, excluded = exclude_by_label(issues, args.exclude_label or [])

    try:
        plan = build_plan(
            kept,
            excluded,
            args.scope_label,
            level=args.level,
            max_fix_rounds=args.max_fix_rounds,
        )
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
        "--level",
        type=str.upper,
        choices=LEVELS,
        default=DEFAULT_LEVEL,
        help=f"Ambition dial (default: {DEFAULT_LEVEL}); sets the verify-rigor "
        "baseline — the per-issue lens count and the run-level fix-round cap "
        "(ADR-0001 §5).",
    )
    plan_parser.add_argument(
        "--max-fix-rounds",
        type=int,
        default=None,
        metavar="N",
        help="Override the derived run-level fix-round cap. `0` (a scan/triage "
        "run) is reachable ONLY here — no level defaults to it.",
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
