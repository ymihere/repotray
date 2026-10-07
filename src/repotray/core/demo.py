"""Fabricated repositories and simulated actions, for screenshots, UI tests and porting.

``DemoScheduler`` has the same public API as ``Scheduler`` but never runs git.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from repotray.core.actions import block_reason, plan_sync_all, summarize_sync_all
from repotray.core.config import Config, ConfigWatcher
from repotray.core.types import (
    ActionKind,
    ActionResult,
    FetchMode,
    RepoInfo,
    RepoState,
    Snapshot,
)

ACTION_SECONDS = 1.5
FETCH_SECONDS = 2.0
DEMO_ROOT = Path.home() / "code"

PULL_FAILURE = (
    "hint: Diverging branches can't be fast-forwarded, you need to either:\n"
    "hint:\n"
    "hint: \tgit merge --no-ff\n"
    "hint:\n"
    "hint: or:\n"
    "hint:\n"
    "hint: \tgit rebase\n"
    "hint:\n"
    'hint: Disable this message with "git config advice.diverging false"\n'
    "fatal: Not possible to fast-forward, aborting.\n"
)


def _state(name: str, **kw) -> RepoState:
    path = DEMO_ROOT / name
    info = RepoInfo(path=path, git_dir=path / ".git", name=name)
    base = {
        "branch": "main",
        "oid": "0" * 40,
        "upstream": "origin/main",
        "upstream_remote": "origin",
        "upstream_merge": "refs/heads/main",
    }
    base.update(kw)
    return RepoState(info=info, **base)


def demo_states(now: float) -> list[RepoState]:
    fetched = now - 180
    no_up = {"upstream": None, "upstream_remote": None, "upstream_merge": None}
    states = [
        _state("api-gateway", ahead=3, unstaged=2),
        _state("infra", ahead=1),
        _state("website", behind=4),
        _state("design-system", ahead=2, behind=2),
        _state("mobile-app", behind=2),
        _state("notes", unstaged=1, untracked=2),
        _state("scratch", untracked=3, branch="wip", **no_up),
        _state("experiments", branch="spike", **no_up),
        _state("docs"),
        _state("dotfiles"),
        _state(
            "legacy-tools",
            fetch_error="unable to access 'https://git.example.com/legacy-tools.git/': "
            "Could not resolve host: git.example.com",
        ),
    ]
    return [
        replace(s, fetched_at=None if s.fetch_error else fetched, checked_at=now) for s in states
    ]


def demo_snapshot(now: float | None = None) -> Snapshot:
    now = time.time() if now is None else now
    states = sorted(demo_states(now), key=lambda s: s.name.casefold())
    return Snapshot(
        repos=tuple(states),
        generated_at=now,
        fetch_mode=FetchMode.IDLE,
        last_fetch_pass_at=now - 180,
        next_fetch_at=now + 420,
    )


class DemoScheduler:
    """Scheduler look-alike over fabricated state."""

    def __init__(self, watcher: ConfigWatcher, clock: Callable[[], float] = time.time) -> None:
        self.watcher = watcher
        self.clock = clock
        now = clock()
        self.states = {s.path: s for s in demo_states(now)}
        self.running: dict[Path, ActionKind] = {}
        self.results: deque[ActionResult] = deque(maxlen=20)
        self.paused = False
        self.fetching = False
        self.last_fetch = now - 180
        self.sync_all_progress: tuple[int, int] | None = None
        self._listeners: list[Callable[[Snapshot], None]] = []
        self._result_listeners: list[Callable[[ActionResult], None]] = []
        self._lock = threading.RLock()
        self._timers: list[threading.Timer] = []
        self._stopped = False

    @property
    def config(self) -> Config:
        return self.watcher.config

    def on_snapshot(self, cb: Callable[[Snapshot], None]) -> None:
        self._listeners.append(cb)

    def on_result(self, cb: Callable[[ActionResult], None]) -> None:
        self._result_listeners.append(cb)

    def start(self) -> None:
        self._emit()

    def stop(self, timeout: float = 3.0) -> None:
        self._stopped = True
        for t in self._timers:
            t.cancel()

    def _later(self, delay: float, fn: Callable[[], None]) -> None:
        if self._stopped:
            return
        t = threading.Timer(delay, fn)
        t.daemon = True
        self._timers.append(t)
        t.start()

    def snapshot(self) -> Snapshot:
        with self._lock:
            if self.paused:
                mode = FetchMode.PAUSED
            elif self.fetching:
                mode = FetchMode.FETCHING
            else:
                mode = FetchMode.IDLE
            now = self.clock()
            return Snapshot(
                repos=tuple(sorted(self.states.values(), key=lambda s: s.name.casefold())),
                generated_at=now,
                fetch_mode=mode,
                last_fetch_pass_at=self.last_fetch,
                next_fetch_at=None if self.paused else self.last_fetch + 600,
                running=dict(self.running),
                sync_all=self.sync_all_progress,
                recent_results=tuple(self.results),
                config_warning=self.watcher.warning_text,
            )

    def _emit(self) -> None:
        self.watcher.poll()
        snap = self.snapshot()
        for cb in list(self._listeners):
            cb(snap)

    def refresh_now(self) -> None:
        self._emit()

    def rescan_now(self) -> None:
        self._emit()

    def pause_fetching(self, paused: bool) -> None:
        with self._lock:
            self.paused = paused
        self._emit()

    def fetch_now(self, path: Path | None = None) -> None:
        if path is not None:
            self.run_action(ActionKind.FETCH, path)
            return
        with self._lock:
            if self.fetching:
                return
            self.fetching = True
        self._emit()

        def done() -> None:
            with self._lock:
                self.fetching = False
                self.last_fetch = self.clock()
            self._emit()

        self._later(FETCH_SECONDS, done)

    def run_action(
        self, kind: ActionKind, path: Path, on_done=None, delay: float = ACTION_SECONDS
    ) -> None:
        with self._lock:
            st = self.states.get(path)
            if st is None or path in self.running:
                return
            self.running[path] = kind
            started = self.clock()
        self._emit()
        self._later(delay, lambda: self._finish(kind, path, started, on_done))

    def _finish(self, kind: ActionKind, path: Path, started: float, on_done) -> None:
        with self._lock:
            st = self.states[path]
            reason = block_reason(kind, st) if kind is not ActionKind.FETCH else None
            fail = kind is ActionKind.PULL and st.name == "mobile-app"
            if reason:
                res = self._result(st, kind, False, reason, started)
            elif fail:
                cmd = f"git -C {path} pull --ff-only --no-rebase --quiet"
                msg = "Not possible to fast-forward, aborting."
                res = self._result(st, kind, False, msg, started, PULL_FAILURE, (cmd,))
            else:
                new, msg = self._apply(kind, st)
                self.states[path] = new
                res = self._result(st, kind, True, msg, started)
            self.running.pop(path, None)
            self.results.appendleft(res)
        for cb in list(self._result_listeners):
            cb(res)
        if on_done:
            on_done(res)
        self._emit()

    def _apply(self, kind: ActionKind, st: RepoState) -> tuple[RepoState, str]:
        if kind is ActionKind.PUSH:
            return replace(st, ahead=0), f"Pushed {st.ahead} commits to {st.upstream}"
        if kind is ActionKind.PULL:
            return replace(st, behind=0), f"Pulled {st.behind} commits from {st.upstream}"
        if kind is ActionKind.SYNC:
            return replace(st, ahead=0, behind=0), f"Synced with {st.upstream}"
        if st.name == "legacy-tools":
            return st, "Fetched"
        return replace(st, fetched_at=self.clock()), "Fetched"

    def _result(self, st, kind, ok, msg, started, stderr="", command=()) -> ActionResult:
        now = self.clock()
        return ActionResult(
            repo=st.path,
            action=kind,
            ok=ok,
            message=msg,
            command=command or (f"git -C {st.path} {kind.value} (simulated)",),
            stderr=stderr,
            started_at=started,
            duration=now - started,
            name=st.name,
        )

    def sync_all(self) -> None:
        with self._lock:
            if self.sync_all_progress is not None:
                return
            plan = plan_sync_all(s for s in self.states.values() if s.path not in self.running)
            started = self.clock()
            if not plan.jobs:
                res = summarize_sync_all(plan, [], started, started)
                self.results.appendleft(res)
                self._emit()
                return
            total = len(plan.jobs)
            self.sync_all_progress = (0, total)
            collected: list[ActionResult] = []

        def one_done(res: ActionResult) -> None:
            with self._lock:
                collected.append(res)
                if len(collected) == total:
                    self.sync_all_progress = None
                    summary = summarize_sync_all(plan, collected, started, self.clock())
                    self.results.appendleft(summary)
                    for cb in list(self._result_listeners):
                        cb(summary)
                else:
                    self.sync_all_progress = (len(collected), total)

        for i, (kind, info) in enumerate(plan.jobs):
            self.run_action(kind, info.path, on_done=one_done, delay=ACTION_SECONDS + 0.7 * i)
