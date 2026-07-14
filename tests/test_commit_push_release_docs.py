"""Consistency guards for the commit / push / release skill family.

The three skills share one commit spine — `reconcile the changelog` then
`stage and commit` — with `push` adding `git push` and `release` wrapping the
whole thing in a version bump, tag and platform release. The spine is factored
into `lib/commit.md` (the commit mechanic) beside the older `lib/changelog.md`
(the reconcile procedure), so the mechanic has one authoritative home rather
than three drifting prose copies.

These tests read the SKILL.md and README text and assert the invariants that
would otherwise rot silently:

1. `lib/commit.md` exists and every one of the three skills references it — so
   the shared spine is never re-inlined into a single skill's prose.
2. `commit` never pushes: its SKILL.md carries no `git push`. Pushing to origin
   is `push`'s job; `commit` stops at the local commit.
3. The README's spelled-out skill counts track reality — the total number of
   `skills/` directories, and the size of the release-workflow trio — so adding
   a skill without updating the prose is caught here rather than in review.

Run with: `uv run --with pytest pytest -q`
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
LIB_COMMIT = REPO_ROOT / "lib" / "commit.md"
README = REPO_ROOT / "README.md"

# The three skills that share the commit spine. `commit` is the innermost
# (reconcile + commit), `push` adds the push, `release` wraps bump/tag/publish
# around it. All three must reference the shared `lib/commit.md`.
RELEASE_WORKFLOW_SKILLS = ("commit", "push", "release")

# Enough of the English cardinals to cover any realistic skill count; a count
# outside this range is itself a signal that something is off.
_CARDINALS = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _cardinal(n: int) -> str:
    word = _CARDINALS.get(n)
    if word is None:
        raise AssertionError(f"skill count {n} is outside the tested cardinal range")
    return word


def _skill_dirs() -> list[str]:
    return sorted(d.name for d in SKILLS_DIR.iterdir() if d.is_dir())


def test_lib_commit_md_exists() -> None:
    assert LIB_COMMIT.is_file(), "lib/commit.md (the shared commit mechanic) is missing"


def test_all_three_skills_reference_lib_commit_md() -> None:
    for skill in RELEASE_WORKFLOW_SKILLS:
        skill_md = SKILLS_DIR / skill / "SKILL.md"
        assert skill_md.is_file(), f"skills/{skill}/SKILL.md is missing"
        assert "commit.md" in _text(skill_md), (
            f"skills/{skill}/SKILL.md does not reference the shared lib/commit.md"
        )


def test_commit_skill_never_pushes() -> None:
    commit_md = SKILLS_DIR / "commit" / "SKILL.md"
    assert commit_md.is_file(), "skills/commit/SKILL.md is missing"
    assert "git push" not in _text(commit_md), (
        "commit must not push to origin — 'git push' belongs to the push skill"
    )


def test_readme_total_skill_count_is_accurate() -> None:
    count = len(_skill_dirs())
    phrase = f"{_cardinal(count)} skills"
    assert phrase in _text(README).lower(), (
        f"README does not state '{phrase}' for the {count} skills/ directories"
    )


def test_readme_release_workflow_count_is_accurate() -> None:
    for skill in RELEASE_WORKFLOW_SKILLS:
        assert (SKILLS_DIR / skill).is_dir(), f"skills/{skill}/ is missing"
    phrase = f"{_cardinal(len(RELEASE_WORKFLOW_SKILLS))} release-workflow skills"
    assert phrase in _text(README).lower(), (
        f"README does not state '{phrase}' for the {RELEASE_WORKFLOW_SKILLS} trio"
    )
