import json
import os
import subprocess
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "state.sample.json"


@pytest.fixture
def state() -> dict:
    """The real-shaped, sanitised state.json fixture."""
    return json.loads(FIXTURE.read_text())


@pytest.fixture(autouse=True)
def _isolate_digest_state(tmp_path_factory, monkeypatch):
    """No test may write to the operator's real digest state.

    `DigestScheduler._fire()` records a durable "the digest fired" marker, and
    the endpoint tests call `_fire()` directly — so without this the suite wrote
    a FALSE fire record into ~/.local/state/command-center/, which the schedule
    producer publishes as a genuine digest fire. Autouse so a test that never
    heard of this file still cannot fabricate operator telemetry.
    """
    d = tmp_path_factory.mktemp("digest-state")
    monkeypatch.setenv("CC_DIGEST_STATE_PATH", str(d / "digest-state.json"))


@pytest.fixture(autouse=True)
def _isolate_brief_push_state(tmp_path_factory, monkeypatch):
    """Same rationale as _isolate_digest_state, for the per-event brief push:
    its state file says which briefs were DELIVERED, and a test writing the real
    one would silently suppress (or duplicate) a live operator notification.
    The escalations dir is redirected too — a test must never read the
    operator's real brief store and conclude something about it."""
    d = tmp_path_factory.mktemp("brief-push")
    monkeypatch.setenv("CC_BRIEF_PUSH_STATE_PATH", str(d / "state.json"))
    monkeypatch.setenv("CC_ESCALATIONS_DIR", str(d / "escalations"))


# ------------------------------------------------------------ synthetic git
# `buildinfo.commits_behind(sha)` answers "how many commits is `sha` missing
# relative to HEAD?". Three rounds of test repair failed because every one of
# them derived the sha to ask about from THIS repository's live history:
#
#   1. `HEAD~n` — walks the first-parent line, so it is n behind only while
#      history stays linear. A merge landed and the tests went red.
#   2. position in `git rev-list HEAD` — that list is ordered by commit DATE,
#      and a merge interleaves its two parents' histories, so position is not
#      distance.
#   3. the first commit whose single-ref reachable-set size is count(HEAD) - n
#      — sound arithmetic, but it assumes a commit EXISTS at every distance.
#      A merge commit's reachable set jumps, so for some n there is none, and
#      WHICH n falls in a gap rotates as HEAD advances. That is what made the
#      failure non-deterministic and made it wander between three modules.
#
# The cause is not any one formula: it is that the tests were coupled to the
# live repository's topology at all. These fixtures sever that coupling. A test
# builds its own repository, so distance is known BY CONSTRUCTION — it made the
# commits — and no future commit, merge, rebase or graft on the real repo can
# move the expected numbers. It is also not a tautology: nothing here runs the
# two-argument `rev-list --count <sha>..HEAD` form the implementation uses.
#
# `buildinfo._REPO` is read at call time inside the function, so
# `monkeypatch.setattr(buildinfo, "_REPO", repo.path)` points it at one of
# these. Nothing in a test using them reads the command-center repo.

_GIT_IDENTITY = {
    # Identity through the environment, never through config: the suite must
    # not depend on (or be changed by) whatever `git config --global` says on
    # the machine running it, and CI images frequently have no identity at all.
    "GIT_AUTHOR_NAME": "Synthetic Fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "Synthetic Fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    # Fixed dates: nothing here should depend on the wall clock, and it keeps
    # any date-ordered git output reproducible run to run.
    "GIT_AUTHOR_DATE": "2020-01-01T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2020-01-01T00:00:00+00:00",
    # Neutralise the machine's config entirely — including core.hooksPath,
    # commit.gpgsign and init.defaultBranch, each of which could otherwise
    # change what these commands do on someone else's box.
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_MERGE_AUTOEDIT": "no",
    "GIT_TERMINAL_PROMPT": "0",
}

# Inherited pointers at ANOTHER repository. pytest may well be launched from
# inside a git command (a hook, a rebase), and GIT_DIR would silently redirect
# every command below at the real repo — the exact coupling being removed.
_GIT_INHERITED = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
                  "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                  "GIT_COMMON_DIR", "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES")


def _git(repo, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if k not in _GIT_INHERITED}
    env.update(_GIT_IDENTITY)
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True,
                          env=env).stdout.strip()


class SyntheticRepo:
    """A git repository this test suite created, and therefore one whose
    distances are facts rather than measurements.

    `shas` is OLDEST-FIRST: `shas[0]` is the root commit and `shas[-1]` is
    HEAD, so `commits_behind(shas[k])` is `len(shas) - 1 - k` in a linear
    repo — the number of commits made after `shas[k]`.
    """

    def __init__(self, path):
        self.path = path
        self.shas: list[str] = []
        self.named: dict[str, str] = {}

    def commit(self, message: str, name: str | None = None) -> str:
        _git(self.path, "commit", "--allow-empty", "-q", "-m", message)
        sha = _git(self.path, "rev-parse", "HEAD")
        self.shas.append(sha)
        if name:
            self.named[name] = sha
        return sha

    def short(self, sha: str) -> str:
        """The abbreviated form a builder stamps — `rev-parse --short`."""
        return _git(self.path, "rev-parse", "--short", sha)

    def git(self, *args: str) -> str:
        return _git(self.path, *args)


def _new_repo(tmp_path, name: str) -> SyntheticRepo:
    path = tmp_path / name
    path.mkdir(parents=True)
    # --initial-branch AND init.defaultBranch: a differing global default must
    # not be able to change the branch these fixtures build on.
    _git(path, "-c", "init.defaultBranch=main", "init", "-q",
         "--initial-branch=main")
    return SyntheticRepo(path)


@pytest.fixture
def linear_repo(tmp_path):
    """Factory: `linear_repo(n)` -> SyntheticRepo with n linear commits.

    Returns them oldest-first in `.shas`, so the commit exactly k behind HEAD
    is `.shas[-1 - k]`.
    """
    made = []

    def make(n: int) -> SyntheticRepo:
        repo = _new_repo(tmp_path, f"linear{len(made)}")
        for i in range(n):
            repo.commit(f"commit {i}")
        made.append(repo)
        return repo

    return make


@pytest.fixture
def merged_repo(tmp_path):
    """A repository with a REAL merge, which is the shape that broke this
    suite three times.

        root ── base ── main1 ── main2 ──── merge   (main)
                   \\                        /
                    side1 ── side2 ── side3

    `.named` carries every commit by name. Counted from the merge commit:

      base   is missing main1, main2, side1, side2, side3, merge  -> 6
             (but is only THREE back along the first-parent line)
      side1  is missing side2, side3, main1, main2, merge         -> 5
      main2  is missing side1, side2, side3, merge                -> 4

    The `base` number is the load-bearing one: 6 and 3 differ, so a
    `commits_behind` that walked only first parents cannot produce it.
    """
    repo = _new_repo(tmp_path, "merged")
    repo.commit("root", "root")
    repo.commit("base", "base")
    repo.git("checkout", "-q", "-b", "side")
    repo.commit("side1", "side1")
    repo.commit("side2", "side2")
    repo.commit("side3", "side3")
    repo.git("checkout", "-q", "main")
    repo.commit("main1", "main1")
    repo.commit("main2", "main2")
    repo.git("merge", "--no-ff", "-q", "-m", "merge side into main", "side")
    repo.named["merge"] = repo.git("rev-parse", "HEAD")
    repo.shas.append(repo.named["merge"])
    assert repo.git("rev-parse", "HEAD^2") == repo.named["side3"], \
        "fixture did not build a real two-parent merge"
    return repo
