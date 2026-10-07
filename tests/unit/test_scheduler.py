import threading
from pathlib import Path

import pytest

from repotray.core.config import ConfigWatcher
from repotray.core.gitrun import CallKind, GitResult
from repotray.core.scheduler import Scheduler
from repotray.core.types import ActionKind, FetchMode

OID = "1" * 40


class Clock:
    def __init__(self):
        self.wall = 1_800_000_000.0
        self.mono = 1000.0

    def advance(self, s, sleep=False):
        self.wall += s
        if not sleep:
            self.mono += s


class FakeGit:
    """Answers rev-parse/status/config/fetch; fetch outcome configurable per repo."""

    def __init__(self):
        self.fetch_ok: dict[str, bool] = {}
        self.calls: list[tuple[str, str]] = []
        self.ahead: dict[str, int] = {}
        self.killed = False
        self.block_fetch: threading.Event | None = None
        self._lock = threading.Lock()

    def __call__(self, args, cwd, timeout, *, kind):
        name = Path(cwd).name
        with self._lock:
            self.calls.append((args[0], name))
        if args[0] == "rev-parse":
            return GitResult(0, f"{cwd}/.git\n".encode(), b"", False, ())
        if args[0] == "status":
            a = self.ahead.get(name, 0)
            out = (
                f"# branch.oid {OID}\0# branch.head main\0# branch.upstream origin/main\0"
                f"# branch.ab +{a} -0\0"
            )
            return GitResult(0, out.encode(), b"", False, ())
        if args[0] == "config":
            return GitResult(0, b"branch.main.remote origin\n", b"", False, ())
        if args[0] == "fetch":
            if self.block_fetch:
                self.block_fetch.wait(5)
            if self.fetch_ok.get(name, True):
                return GitResult(0, b"", b"", False, ())
            return GitResult(128, b"", b"fatal: Could not resolve host: example", False, ())
        if args[0] == "push":
            self.ahead[name] = 0
            return GitResult(0, b"", b"", False, ())
        return GitResult(1, b"", b"unexpected", False, ())

    def kill_all(self):
        self.killed = True

    def count(self, verb):
        return sum(1 for v, _ in self.calls if v == verb)


@pytest.fixture
def setup(tmp_path):
    root = tmp_path / "root"
    for n in ("alpha", "beta"):
        (root / n / ".git").mkdir(parents=True)
    cfgfile = tmp_path / "config.toml"
    # TOML literal strings: Windows paths contain backslashes.
    cfgfile.write_text(f"roots = ['{root}']\nfetch_interval = 600\nstatus_interval = 60\n")
    clock = Clock()
    git = FakeGit()
    sched = Scheduler(
        ConfigWatcher(cfgfile),
        git,
        clock=lambda: clock.wall,
        monotonic=lambda: clock.mono,
        git_check=lambda: True,
    )
    snaps = []
    sched.on_snapshot(snaps.append)
    yield sched, clock, git, snaps, root
    sched.stop()


def run(sched, clock, seconds=0.0):
    clock.advance(seconds)
    sched.step()
    assert sched.wait_idle()


def test_startup_scan_status_snapshot(setup):
    sched, clock, git, snaps, _ = setup
    sched.startup()
    assert [s.name for s in snaps[-1].repos] == ["alpha", "beta"]
    assert git.count("status") == 2 and git.count("fetch") == 0
    run(sched, clock, 9)
    assert git.count("fetch") == 0
    run(sched, clock, 1.5)
    assert git.count("fetch") == 2
    snap = sched.snapshot()
    assert snap.last_fetch_pass_at is not None and snap.fetch_mode is FetchMode.IDLE
    assert all(r.fetched_at for r in snap.repos)


def test_status_pass_timing(setup):
    sched, clock, git, _, _ = setup
    sched.startup()
    sched.pause_fetching(True)
    n = git.count("status")
    run(sched, clock, 30)
    assert git.count("status") == n
    run(sched, clock, 31)
    assert git.count("status") == n + 2


def test_fetch_skips_locked_repo(setup):
    sched, clock, git, _, root = setup
    sched.startup()
    lock = sched.locks.get((root / "alpha").resolve())
    lock.acquire()
    try:
        run(sched, clock, 11)
    finally:
        lock.release()
    assert [n for v, n in git.calls if v == "fetch"] == ["beta"]


def test_backoff_doubles_and_resets(setup):
    sched, clock, git, snaps, _ = setup
    git.fetch_ok = {"alpha": False, "beta": False}
    sched.startup()
    run(sched, clock, 11)
    snap = sched.snapshot()
    assert snap.all_fetches_failed and snap.fetch_mode is FetchMode.BACKOFF
    assert sched.fetch_delay == 1200
    assert all(r.fetch_error == "Could not resolve host: example" for r in snap.repos)
    run(sched, clock, 1201)
    assert sched.fetch_delay == 2400
    run(sched, clock, 2401)
    assert sched.fetch_delay == 3600
    run(sched, clock, 3601)
    assert sched.fetch_delay == 3600
    git.fetch_ok = {"alpha": True, "beta": False}
    run(sched, clock, 3601)
    assert sched.fetch_delay == 600 and not sched.snapshot().all_fetches_failed


def test_manual_fetch_resets_backoff(setup):
    sched, clock, git, _, _ = setup
    git.fetch_ok = {"alpha": False, "beta": False}
    sched.startup()
    run(sched, clock, 11)
    assert sched.fetch_delay == 1200
    git.fetch_ok = {}
    sched.fetch_now()
    run(sched, clock)
    assert sched.fetch_delay == 600 and not sched.all_fetches_failed


def test_pause(setup):
    sched, clock, git, _, _ = setup
    sched.startup()
    sched.pause_fetching(True)
    run(sched, clock, 700)
    assert git.count("fetch") == 0
    assert sched.snapshot().fetch_mode is FetchMode.PAUSED
    assert git.count("status") > 2  # status continues
    sched.pause_fetching(False)
    run(sched, clock)
    run(sched, clock)
    assert git.count("fetch") == 2


def test_resume_detection(setup):
    sched, clock, git, _, _ = setup
    sched.startup()
    run(sched, clock, 11)
    assert git.count("fetch") == 2
    clock.advance(3600, sleep=True)  # wall jumps, monotonic doesn't
    run(sched, clock)
    assert git.count("fetch") == 2
    run(sched, clock, 10.5)
    assert git.count("fetch") == 4


def test_action_then_status(setup):
    sched, clock, git, snaps, root = setup
    git.ahead["alpha"] = 2
    sched.startup()
    alpha = (root / "alpha").resolve()
    assert sched.snapshot().repos[0].ahead == 2
    sched.run_action(ActionKind.PUSH, alpha)
    sched.step()
    assert any(alpha in s.running for s in snaps)
    assert sched.wait_idle()
    snap = sched.snapshot()
    assert snap.repos[0].ahead == 0 and not snap.running
    assert snap.recent_results[0].ok and snap.recent_results[0].action is ActionKind.PUSH


def test_sync_all(setup):
    sched, clock, git, snaps, _ = setup
    git.ahead.update(alpha=1, beta=3)
    sched.startup()
    sched.sync_all()
    assert sched.wait_idle()
    assert any(s.sync_all == (0, 2) for s in snaps)
    snap = sched.snapshot()
    assert snap.sync_all is None
    assert snap.recent_results[0].name == "Sync all"
    assert snap.recent_results[0].message == "Synced 2 of 2"
    assert any(s.sync_all == (1, 2) for s in snaps)


def test_config_reload_triggers_rescan(setup, tmp_path):
    sched, clock, git, _, root = setup
    sched.startup()
    (root / "gamma" / ".git").mkdir(parents=True)
    cfgfile = sched.watcher.path
    cfgfile.write_text(f"roots = ['{root}']\nmax_depth = 3\n")
    import os

    os.utime(cfgfile, (clock.wall + 100, clock.wall + 100))
    run(sched, clock, 61)
    assert [r.name for r in sched.snapshot().repos] == ["alpha", "beta", "gamma"]


def test_config_error_kept_previous(setup):
    sched, clock, git, _, _ = setup
    sched.startup()
    sched.watcher.path.write_text("roots = [\n")
    import os

    os.utime(sched.watcher.path, (clock.wall + 100, clock.wall + 100))
    run(sched, clock, 61)
    snap = sched.snapshot()
    assert snap.config_warning.startswith("Config error")
    assert len(snap.repos) == 2


def test_stop_kills_and_returns(setup):
    sched, clock, git, _, _ = setup
    sched.start()
    import time

    t = time.monotonic()
    sched.stop()
    assert time.monotonic() - t < 3.5
    assert git.killed


def test_git_missing(tmp_path):
    cfgfile = tmp_path / "c.toml"
    sched = Scheduler(ConfigWatcher(cfgfile), FakeGit(), git_check=lambda: False)
    sched.startup()
    assert sched.snapshot().git_missing
    sched.stop()


def test_runner_kind_for_status(setup):
    sched, clock, git, _, _ = setup
    seen = []
    orig = git.__call__

    def spy(args, cwd, timeout, *, kind):
        seen.append((args[0], kind))
        return orig(args, cwd, timeout, kind=kind)

    sched.runner = spy
    sched.startup()
    assert ("status", CallKind.STATUS) in seen
