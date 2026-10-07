"""Status, fetch and rescan passes; actions; backoff; pause; resume detection.

One scheduler thread owns all mutable state. Git work runs on two thread pools (status, and
fetch + actions); their completions are posted back to the scheduler thread as commands, so state
is only ever written from one thread. Clocks and the git runner are injectable for tests.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from repotray.core.actions import (
    ActionContext,
    RepoLocks,
    plan_sync_all,
    run_action,
    summarize_sync_all,
)
from repotray.core.config import Config, ConfigWatcher
from repotray.core.gitrun import Runner, git_available
from repotray.core.gitstatus import apply_fetch_result, check_status, fetch_repo
from repotray.core.scanner import scan
from repotray.core.types import (
    ActionKind,
    ActionResult,
    FetchMode,
    RepoInfo,
    RepoState,
    Snapshot,
)

log = logging.getLogger(__name__)

FIRST_FETCH_DELAY = 10.0
RESUME_FETCH_DELAY = 10.0
SLEEP_GAP = 60.0
MAX_BACKOFF = 3600.0
MAX_RESULTS = 20


class Scheduler:
    def __init__(
        self,
        watcher: ConfigWatcher,
        runner: Runner,
        *,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        git_check: Callable[[], bool] = git_available,
        first_fetch_delay: float = FIRST_FETCH_DELAY,
    ) -> None:
        self.watcher = watcher
        self.runner = runner
        self.clock = clock
        self.mono = monotonic
        self.git_check = git_check
        self.first_fetch_delay = first_fetch_delay
        self.locks = RepoLocks()

        cfg = watcher.config
        self._status_pool = ThreadPoolExecutor(cfg.workers, thread_name_prefix="repotray-status")
        self._fetch_pool = ThreadPoolExecutor(
            cfg.fetch_workers, thread_name_prefix="repotray-fetch"
        )
        self._q: queue.Queue[Callable[[], None]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._outstanding = 0
        self._out_lock = threading.Condition()

        self._listeners: list[Callable[[Snapshot], None]] = []
        self._result_listeners: list[Callable[[ActionResult], None]] = []

        # State, written only by the scheduler thread (or by step() in tests).
        self.infos: list[RepoInfo] = []
        self.states: dict[Path, RepoState] = {}
        self.running: dict[Path, ActionKind] = {}
        self.results: deque[ActionResult] = deque(maxlen=MAX_RESULTS)
        self.paused = False
        self.fetching = False
        self.all_fetches_failed = False
        self.git_missing = False
        self.last_fetch_pass_at: float | None = None
        self.fetch_delay = float(cfg.fetch_interval)
        self.sync_all_progress: tuple[int, int] | None = None
        self.scan_warnings: list[str] = []
        self._scan_key = None
        self._started = False

        self.next_status = 0.0
        self.next_fetch = 0.0
        self.next_rescan = 0.0
        self._last_wall = 0.0
        self._last_mono = 0.0
        self._snapshot = Snapshot()

    # ----- public, thread-safe API -------------------------------------------------------------

    @property
    def config(self) -> Config:
        return self.watcher.config

    def on_snapshot(self, cb: Callable[[Snapshot], None]) -> None:
        self._listeners.append(cb)

    def on_result(self, cb: Callable[[ActionResult], None]) -> None:
        self._result_listeners.append(cb)

    def snapshot(self) -> Snapshot:
        return self._snapshot

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="repotray-scheduler", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stopping.set()
        self._q.put(lambda: None)
        kill = getattr(self.runner, "kill_all", None)
        if kill:
            kill()
        self._status_pool.shutdown(wait=False, cancel_futures=True)
        self._fetch_pool.shutdown(wait=False, cancel_futures=True)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout)

    def refresh_now(self) -> None:
        self._post(self._status_pass)

    def fetch_now(self, path: Path | None = None) -> None:
        if path is None:
            self._post(lambda: self._start_fetch_pass(manual=True))
        else:
            self._post(lambda: self._submit_action(ActionKind.FETCH, path))

    def rescan_now(self) -> None:
        self._post(lambda: self._rescan())

    def pause_fetching(self, paused: bool) -> None:
        self._post(lambda: self._set_paused(paused))

    def run_action(self, kind: ActionKind, path: Path) -> None:
        self._post(lambda: self._submit_action(kind, path))

    def sync_all(self) -> None:
        self._post(self._start_sync_all)

    # ----- loop --------------------------------------------------------------------------------

    def _post(self, fn: Callable[[], None]) -> None:
        self._q.put(fn)

    def _loop(self) -> None:
        try:
            self.startup()
            while not self._stopping.is_set():
                self.step(timeout=self._seconds_to_next())
        except Exception:  # pragma: no cover - logged, keeps the tray alive in degraded state
            log.exception("scheduler thread crashed")

    def _seconds_to_next(self) -> float:
        due = min(self.next_status, self.next_rescan)
        if not self.paused and not self.fetching:
            due = min(due, self.next_fetch)
        return max(0.05, min(due - self.mono(), 5.0))

    def startup(self) -> None:
        now_m = self.mono()
        self._last_wall, self._last_mono = self.clock(), now_m
        self.watcher.load()
        self._scan_key = None
        self._rescan(emit=False)
        self._status_pass()
        self.next_fetch = self.mono() + self.first_fetch_delay
        self._started = True
        self._emit()

    def step(self, timeout: float = 0.0) -> None:
        """Run queued commands, then due timers, then wait up to ``timeout`` for a command."""
        self._drain()
        self._detect_resume()
        now = self.mono()
        if now >= self.next_rescan:
            self._rescan()
        if now >= self.next_status:
            self._status_pass()
        if not self.paused and not self.fetching and now >= self.next_fetch:
            self._start_fetch_pass()
        try:
            fn = self._q.get(timeout=timeout) if timeout > 0 else self._q.get_nowait()
        except queue.Empty:
            return
        self._run(fn)
        self._drain()

    def _drain(self) -> None:
        while True:
            try:
                fn = self._q.get_nowait()
            except queue.Empty:
                return
            self._run(fn)

    def _run(self, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception:
            log.exception("scheduler command failed")

    def wait_idle(self, timeout: float = 10.0) -> bool:
        """Test helper: process commands until no pool work is outstanding."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.step(timeout=0.02)
            with self._out_lock:
                busy = self._outstanding
            if busy == 0 and self._q.empty():
                return True
        return False

    def _submit(self, pool: ThreadPoolExecutor, fn, done: Callable[[object], None]) -> None:
        with self._out_lock:
            self._outstanding += 1

        def finished(fut: Future) -> None:
            try:
                value = fut.result()
            except Exception as exc:  # noqa: BLE001 - surfaced as a failed result
                log.exception("worker failed")
                value = exc
            self._q.put(lambda: done(value))
            with self._out_lock:
                self._outstanding -= 1
                self._out_lock.notify_all()

        try:
            pool.submit(fn).add_done_callback(finished)
        except RuntimeError:  # pool shut down
            with self._out_lock:
                self._outstanding -= 1

    # ----- passes ------------------------------------------------------------------------------

    def _detect_resume(self) -> None:
        wall, mono = self.clock(), self.mono()
        gap = (wall - self._last_wall) - (mono - self._last_mono)
        self._last_wall, self._last_mono = wall, mono
        if self._started and gap > SLEEP_GAP:
            log.info("resume from suspend detected (%.0f s); fetching soon", gap)
            self.next_fetch = min(self.next_fetch, mono + RESUME_FETCH_DELAY)
            self.next_status = min(self.next_status, mono)

    def _apply_config(self, cfg: Config) -> None:
        """Reschedule after a config reload. Pool sizes keep until restart (rare, harmless)."""
        now = self.mono()
        if not self.all_fetches_failed:
            self.fetch_delay = float(cfg.fetch_interval)
            self.next_fetch = min(self.next_fetch, now + cfg.fetch_interval)
        self.next_rescan = min(self.next_rescan, now + cfg.rescan_interval)

    def _rescan(self, emit: bool = True) -> None:
        cfg = self.config
        self.next_rescan = self.mono() + cfg.rescan_interval
        self.git_missing = not self.git_check()
        if self.git_missing:
            self.infos, self.states = [], {}
            if emit:
                self._emit()
            return
        key = cfg.scan_key()
        infos, warnings = scan(cfg, self.runner, workers=cfg.workers)
        self._scan_key = key
        self.scan_warnings = warnings
        old = self.states
        self.infos = infos
        self.states = {}
        for info in infos:
            prev = old.get(info.path)
            self.states[info.path] = (
                replace(prev, info=info) if prev else RepoState(info=info, checked_at=0.0)
            )
        new_paths = [i for i in infos if i.path not in old]
        if self._started and new_paths:
            self._check_repos(new_paths)
        if emit:
            self._emit()

    def _check_repos(self, infos: list[RepoInfo]) -> None:
        cfg = self.config
        now = self.clock()

        def check(info: RepoInfo) -> RepoState:
            return check_status(
                self.runner,
                info,
                count_untracked=cfg.count_untracked_as_dirty,
                previous=self.states.get(info.path),
                now=now,
            )

        try:
            results = list(self._status_pool.map(check, infos))
        except RuntimeError:  # shutting down
            return
        for st in results:
            if st.path in self.states:
                self.states[st.path] = st

    def _status_pass(self) -> None:
        if self.watcher.poll():
            cfg = self.config
            self._apply_config(cfg)
            if cfg.scan_key() != self._scan_key:
                self._rescan(emit=False)
        self.next_status = self.mono() + self.config.status_interval
        if not self.git_missing:
            self._check_repos(list(self.infos))
        self._emit()

    def _start_fetch_pass(self, manual: bool = False) -> None:
        if self.fetching or self.git_missing:
            return
        if manual:
            self.fetch_delay = float(self.config.fetch_interval)
        targets = [i for i in self.infos if i.fetch_enabled and not self.locks.locked(i.path)]
        self.fetching = True
        self._emit()
        if not targets:
            self._finish_fetch_pass([])
            return
        timeout = float(self.config.fetch_timeout)
        results: list[tuple[RepoInfo, object]] = []
        remaining = [len(targets)]

        for info in targets:

            def job(info: RepoInfo = info):
                with self.locks.hold(info.path, timeout=0) as ok:
                    if not ok:
                        return None  # an action took the repo; skip, don't wait
                    return fetch_repo(self.runner, info.path, timeout)

            def done(res, info: RepoInfo = info) -> None:
                results.append((info, res))
                remaining[0] -= 1
                if remaining[0] == 0:
                    self._finish_fetch_pass(results)

            self._submit(self._fetch_pool, job, done)

    def _finish_fetch_pass(self, results: list[tuple[RepoInfo, object]]) -> None:
        now = self.clock()
        attempted = 0
        failed = 0
        for info, res in results:
            if res is None or isinstance(res, Exception):
                continue
            attempted += 1
            st = self.states.get(info.path)
            if st is None:
                continue
            new = apply_fetch_result(st, res, now)
            if new.fetch_error:
                failed += 1
            self.states[info.path] = new
        self.fetching = False
        self.last_fetch_pass_at = now
        if attempted and failed == attempted:
            self.all_fetches_failed = True
            self.fetch_delay = min(
                self.fetch_delay * 2, max(MAX_BACKOFF, self.config.fetch_interval)
            )
        else:
            if attempted:
                self.all_fetches_failed = False
            self.fetch_delay = float(self.config.fetch_interval)
        self.next_fetch = self.mono() + self.fetch_delay
        self._status_pass()

    def _set_paused(self, paused: bool) -> None:
        self.paused = paused
        if not paused and self.next_fetch < self.mono():
            self.next_fetch = self.mono()
        self._emit()

    # ----- actions -----------------------------------------------------------------------------

    def _ctx(self) -> ActionContext:
        cfg = self.config
        return ActionContext(
            runner=self.runner,
            timeout=float(cfg.action_timeout),
            sync_strategy=cfg.sync_strategy,
            locks=self.locks,
            clock=self.clock,
        )

    def _info(self, path: Path) -> RepoInfo | None:
        st = self.states.get(path)
        return st.info if st else None

    def _submit_action(self, kind: ActionKind, path: Path, on_done=None) -> bool:
        info = self._info(path)
        if info is None or path in self.running:
            return False
        ctx = self._ctx()
        if kind is ActionKind.FETCH:
            ctx.timeout = float(self.config.fetch_timeout)
        self.running[path] = kind
        self._emit()

        def done(res) -> None:
            if isinstance(res, Exception):
                res = ActionResult(
                    repo=path, action=kind, ok=False, message=str(res), name=info.name
                )
            self.running.pop(path, None)
            self._after_action(info, res)
            if on_done:
                on_done(res)

        self._submit(self._fetch_pool, lambda: run_action(ctx, kind, info), done)
        return True

    def _after_action(self, info: RepoInfo, res: ActionResult) -> None:
        prev = self.states.get(info.path)
        if prev is not None:
            st = check_status(
                self.runner,
                info,
                count_untracked=self.config.count_untracked_as_dirty,
                previous=prev,
                now=self.clock(),
            )
            if res.action is ActionKind.FETCH:
                st = replace(
                    st,
                    fetch_error=None if res.ok else res.message,
                    fetched_at=self.clock() if res.ok else st.fetched_at,
                )
            self.states[info.path] = st
        self._record(res)

    def _record(self, res: ActionResult, emit: bool = True) -> None:
        self.results.appendleft(res)
        for cb in list(self._result_listeners):
            try:
                cb(res)
            except Exception:
                log.exception("result listener failed")
        if emit:
            self._emit()

    def _start_sync_all(self) -> None:
        if self.sync_all_progress is not None:
            return
        plan = plan_sync_all(s for s in self.states.values() if s.path not in self.running)
        started = self.clock()
        if not plan.jobs:
            self._record(summarize_sync_all(plan, [], started, self.clock()))
            return
        total = len(plan.jobs)
        self.sync_all_progress = (0, total)
        collected: list[ActionResult] = []

        def one_done(res: ActionResult) -> None:
            collected.append(res)
            self.sync_all_progress = (len(collected), total)
            if len(collected) == total:
                self.sync_all_progress = None
                self._record(summarize_sync_all(plan, collected, started, self.clock()))
            else:
                self._emit()

        for kind, info in plan.jobs:
            if not self._submit_action(kind, info.path, on_done=one_done):
                one_done(
                    ActionResult(
                        repo=info.path, action=kind, ok=False, message="busy", name=info.name
                    )
                )
        self._emit()

    # ----- snapshots ---------------------------------------------------------------------------

    def build_snapshot(self) -> Snapshot:
        if self.paused:
            mode = FetchMode.PAUSED
        elif self.fetching:
            mode = FetchMode.FETCHING
        elif self.all_fetches_failed:
            mode = FetchMode.BACKOFF
        else:
            mode = FetchMode.IDLE
        next_fetch_at = None
        if not self.paused and not self.fetching:
            next_fetch_at = self.clock() + max(0.0, self.next_fetch - self.mono())
        repos = tuple(sorted(self.states.values(), key=lambda s: (s.name.casefold(), str(s.path))))
        warning = self.watcher.warning_text
        if warning is None and self.scan_warnings:
            warning = self.scan_warnings[0]
        return Snapshot(
            repos=repos,
            generated_at=self.clock(),
            fetch_mode=mode,
            last_fetch_pass_at=self.last_fetch_pass_at,
            next_fetch_at=next_fetch_at,
            all_fetches_failed=self.all_fetches_failed,
            git_missing=self.git_missing,
            running=dict(self.running),
            sync_all=self.sync_all_progress,
            recent_results=tuple(self.results),
            config_warning=warning,
        )

    def _emit(self) -> None:
        snap = self.build_snapshot()
        self._snapshot = snap
        for cb in list(self._listeners):
            try:
                cb(snap)
            except Exception:
                log.exception("snapshot listener failed")
