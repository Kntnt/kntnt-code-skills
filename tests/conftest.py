"""Session-wide pytest configuration for the kntnt-code-skills test suite.

The single job here is to isolate every git subprocess the suite spawns — the
fixtures' own `git init`/`add`/`commit` and the git commands `scripts/doctor.py`
and `scripts/init.py` run when driven against temp fixtures — from the git
environment the pytest process was launched with.

Why this matters: git hooks export `GIT_DIR` (and, for index-touching hooks,
`GIT_INDEX_FILE`) into the environment of everything they run. The pre-commit
`tests` hook launches pytest, so those variables leak in. An exported `GIT_DIR`
takes precedence over `-C <dir>` discovery and `GIT_INDEX_FILE` overrides which
index is written, so without scrubbing them a fixture's `git -C <tmpdir> add`
writes the *real* repository's index and a fixture `git init` can rewrite the
real repo's config (flipping it to `core.bare=true`) — corrupting the
developer's checkout from a test run that should never touch it. Scrubbing the
variables from the process environment once means every git subprocess beneath
pytest — current and future, fixture-direct or script-spawned — inherits a
clean environment.

Pinning `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM` to isolate config is a possible
future hardening, deliberately left out here: it would force every fixture
commit to set `user.email`/`user.name` explicitly, and this suite has no
evidence of a config-leak hazard.
"""

from __future__ import annotations

import pytest

# Location variables git honours ahead of `-C <dir>` discovery; any one of them
# leaking in redirects a fixture's git command at the real repository. The
# pre-commit `tests` hook (.pre-commit-config.yaml) mirrors this list in its
# `env -u …` entry as a second layer of defence — keep the two in sync.
GIT_LOCATION_VARS = (
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_WORK_TREE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_COMMON_DIR",
)


@pytest.fixture(autouse=True)
def _isolate_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove the leaked git location variables for the duration of every test.

    Autouse so no test can forget it; function-scoped so `monkeypatch` restores
    the original environment once the test finishes.
    """

    for name in GIT_LOCATION_VARS:
        monkeypatch.delenv(name, raising=False)
