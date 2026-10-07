"""Push, pull, sync and sync-all: the only code paths that modify a repository.

Every action re-reads the repository's status first and refuses when its preconditions no longer
hold. A failed or timed-out sync aborts any rebase/merge it started, so the repository ends up
exactly as it was.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from repotray.core.gitrun import CallKind, GitResult, Runner, first_line, strip_credentials
from repotray.core.gitstatus import check_status, detect_operation, fetch_repo
from repotray.core.types import ActionKind, ActionResult, RepoInfo, RepoState

LOCK_WAIT = 30.0


class RepoLocks:
    """One lock per repository path; serialises fetch, push, pull and sync on a repo."""

    def __init__(self) -> None:
        self._locks: dict[Path, threading.Lock] = {}
        self._guard = threading.Lock()

    def get(self, path: Path) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(path, threading.Lock())

    def locked(self, path: Path) -> bool:
        return self.get(path).locked()

    @contextmanager
    def hold(self, path: Path, timeout: float = LOCK_WAIT):
        lock = self.get(path)
        ok = lock.acquire(timeout=timeout) if timeout > 0 else lock.acquire(blocking=False)
        try:
            yield ok
        finally:
            if ok:
                lock.release()


# --- precondition rules (shared with the panel model) -------------------------------------------


def push_block_reason(s: RepoState) -> str | None:
    if s.operation:
        return f"Operation in progress: {s.operation}"
    if s.detached:
        return "HEAD is detached"
    if not s.has_upstream:
        return "No upstream branch"
    if s.upstream_remote == ".":
        return "Upstream is a local branch"
    if s.ahead == 0:
        return "Nothing to push"
    if s.behind > 0:
        return "Diverged — use Sync"
    return None


def pull_block_reason(s: RepoState) -> str | None:
    if s.operation:
        return f"Operation in progress: {s.operation}"
    if s.detached:
        return "HEAD is detached"
    if not s.has_upstream:
        return "No upstream branch"
    if s.behind == 0:
        return "Nothing to pull"
    if s.ahead > 0:
        return "Diverged — use Sync"
    return None


def sync_block_reason(s: RepoState) -> str | None:
    if s.operation:
        return f"Operation in progress: {s.operation}"
    if not s.diverged:
        return "Not diverged"
    if s.tracked_changes:
        return "Commit or stash first"
    if s.upstream_remote == ".":
        return "Upstream is a local branch"
    return None


def block_reason(kind: ActionKind, s: RepoState) -> str | None:
    if s.status_error:
        return s.status_error
    if kind is ActionKind.PUSH:
        return push_block_reason(s)
    if kind is ActionKind.PULL:
        return pull_block_reason(s)
    if kind is ActionKind.SYNC:
        return sync_block_reason(s)
    return None


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def push_args(s: RepoState) -> list[str]:
    merge = s.upstream_merge or f"refs/heads/{s.branch}"
    remote = s.upstream_remote or "origin"
    return ["push", "--porcelain", remote, f"refs/heads/{s.branch}:{merge}"]


PULL_ARGS = ["pull", "--ff-only", "--no-rebase", "--quiet"]


def sync_pull_args(strategy: str) -> list[str]:
    if strategy == "merge":
        return ["pull", "--no-rebase", "--no-edit", "--quiet"]
    return ["pull", "--rebase", "--no-autostash", "--quiet"]


# --- execution ----------------------------------------------------------------------------------


@dataclass
class ActionContext:
    runner: Runner
    timeout: float = 120.0
    sync_strategy: str = "rebase"
    locks: RepoLocks | None = None
    clock: Callable[[], float] = time.time


def _result(
    info: RepoInfo,
    kind: ActionKind,
    ok: bool,
    message: str,
    started: float,
    ctx: ActionContext,
    results: Sequence[GitResult] = (),
    restored: bool | None = None,
) -> ActionResult:
    stdout = "\n".join(r.out for r in results if r.stdout)
    stderr = "\n".join(r.err for r in results if r.stderr)
    return ActionResult(
        repo=info.path,
        action=kind,
        ok=ok,
        message=strip_credentials(message),
        command=tuple(strip_credentials(" ".join(r.command)) for r in results),
        stdout=strip_credentials(stdout),
        stderr=strip_credentials(stderr),
        started_at=started,
        duration=ctx.clock() - started,
        restored=restored,
        name=info.name,
    )


def _git_message(res: GitResult, fallback: str) -> str:
    if res.timed_out:
        return f"{fallback}: timed out"
    return first_line(res.err, res.out) or fallback


def _push_failure(res: GitResult) -> str:
    for line in res.out.splitlines():
        parts = line.split("\t")
        if parts and parts[0] == "!" and len(parts) >= 3:
            return f"push rejected: {parts[2].strip('[] ').replace('] (', ' (')}"
    return _git_message(res, "push failed")


def _clean_up_after_kill(ctx: ActionContext, info: RepoInfo, started: float) -> list[GitResult]:
    """After a timeout: remove our own stale index.lock, abort a half-done rebase/merge."""
    done: list[GitResult] = []
    lock = info.git_dir / "index.lock"
    try:
        if lock.exists() and lock.stat().st_mtime >= started - 1:
            lock.unlink()
    except OSError:
        pass
    done += _abort_operation(ctx, info)
    return done


def _abort_operation(ctx: ActionContext, info: RepoInfo) -> list[GitResult]:
    op = detect_operation(info.git_dir)
    if op == "rebase":
        return [ctx.runner(["rebase", "--abort"], info.path, 60, kind=CallKind.ACTION)]
    if op == "merge":
        return [ctx.runner(["merge", "--abort"], info.path, 60, kind=CallKind.ACTION)]
    return []


def _head(ctx: ActionContext, info: RepoInfo) -> str | None:
    res = ctx.runner(["rev-parse", "HEAD"], info.path, 15, kind=CallKind.QUERY)
    return res.out.strip() if res.ok else None


def do_push(ctx: ActionContext, s: RepoState, started: float) -> ActionResult:
    res = ctx.runner(push_args(s), s.path, ctx.timeout, kind=CallKind.ACTION)
    if res.ok:
        msg = f"Pushed {plural(s.ahead, 'commit')} to {s.upstream}"
        return _result(s.info, ActionKind.PUSH, True, msg, started, ctx, [res])
    extra = _clean_up_after_kill(ctx, s.info, started) if res.timed_out else []
    msg = _push_failure(res) if not res.timed_out else "push timed out"
    return _result(s.info, ActionKind.PUSH, False, msg, started, ctx, [res, *extra])


def do_pull(ctx: ActionContext, s: RepoState, started: float) -> ActionResult:
    res = ctx.runner(PULL_ARGS, s.path, ctx.timeout, kind=CallKind.ACTION)
    if res.ok:
        msg = f"Pulled {plural(s.behind, 'commit')} from {s.upstream}"
        return _result(s.info, ActionKind.PULL, True, msg, started, ctx, [res])
    extra = _clean_up_after_kill(ctx, s.info, started) if res.timed_out else []
    return _result(
        s.info,
        ActionKind.PULL,
        False,
        _git_message(res, "pull failed"),
        started,
        ctx,
        [res, *extra],
    )


def do_sync(ctx: ActionContext, s: RepoState, started: float) -> ActionResult:
    info = s.info
    orig = _head(ctx, info)
    if orig is None:
        return _result(info, ActionKind.SYNC, False, "cannot read HEAD", started, ctx)
    pull = ctx.runner(
        sync_pull_args(ctx.sync_strategy), info.path, ctx.timeout, kind=CallKind.ACTION
    )
    runs = [pull]
    if not pull.ok:
        if pull.timed_out:
            runs += _clean_up_after_kill(ctx, info, started)
        else:
            runs += _abort_operation(ctx, info)
        restored = _head(ctx, info) == orig and detect_operation(info.git_dir) is None
        verb = "rebase" if ctx.sync_strategy == "rebase" else "merge"
        if pull.timed_out:
            reason = "timed out"
        elif _has_conflict(pull):
            reason = f"conflicts during {verb}, aborted"
        else:
            reason = _git_message(pull, f"{verb} failed")
        msg = reason if restored else f"{reason}; repository NOT restored — see details"
        return _result(info, ActionKind.SYNC, False, msg, started, ctx, runs, restored=restored)
    fresh = check_status(ctx.runner, info)
    push = ctx.runner(push_args(fresh), info.path, ctx.timeout, kind=CallKind.ACTION)
    runs.append(push)
    if not push.ok:
        if push.timed_out:
            runs += _clean_up_after_kill(ctx, info, started)
        verb = "rebased" if ctx.sync_strategy == "rebase" else "merged"
        msg = f"{verb} locally, {_push_failure(push) if not push.timed_out else 'push timed out'}"
        return _result(info, ActionKind.SYNC, False, msg, started, ctx, runs)
    msg = f"Synced with {s.upstream} (↓{s.behind} ↑{fresh.ahead})"
    return _result(info, ActionKind.SYNC, True, msg, started, ctx, runs)


def _has_conflict(res: GitResult) -> bool:
    text = (res.out + res.err).lower()
    return "conflict" in text or "could not apply" in text


def do_fetch(ctx: ActionContext, info: RepoInfo, started: float) -> ActionResult:
    res = fetch_repo(ctx.runner, info.path, ctx.timeout)
    if res.ok:
        return _result(info, ActionKind.FETCH, True, "Fetched", started, ctx, [res])
    return _result(
        info, ActionKind.FETCH, False, _git_message(res, "fetch failed"), started, ctx, [res]
    )


def run_action(
    ctx: ActionContext,
    kind: ActionKind,
    info: RepoInfo,
    lock_timeout: float = LOCK_WAIT,
) -> ActionResult:
    """Run one action under the repo lock, after re-checking its preconditions."""
    started = ctx.clock()
    locks = ctx.locks or RepoLocks()
    with locks.hold(info.path, lock_timeout) as ok:
        if not ok:
            return _result(
                info, kind, False, "busy: another git operation is running", started, ctx
            )
        if kind is ActionKind.FETCH:
            return do_fetch(ctx, info, started)
        state = check_status(ctx.runner, info)
        reason = block_reason(kind, state)
        if reason:
            return _result(info, kind, False, reason, started, ctx)
        if kind is ActionKind.PUSH:
            return do_push(ctx, state, started)
        if kind is ActionKind.PULL:
            return do_pull(ctx, state, started)
        return do_sync(ctx, state, started)


def smart_kind(s: RepoState) -> ActionKind | None:
    """What `repotray sync REPO` / Sync all does for a repo: push, pull, sync or nothing."""
    if s.diverged:
        return ActionKind.SYNC
    if s.pushable:
        return ActionKind.PUSH
    if s.pullable:
        return ActionKind.PULL
    return None


BULK_NAMES = {ActionKind.PUSH: "Push all", ActionKind.PULL: "Pull all", ActionKind.SYNC: "Sync all"}
_BULK_DONE = {ActionKind.PUSH: "Pushed", ActionKind.PULL: "Pulled", ActionKind.SYNC: "Synced"}


@dataclass(frozen=True, slots=True)
class BulkPlan:
    kind: ActionKind
    jobs: tuple[tuple[ActionKind, RepoInfo], ...]
    skipped: tuple[tuple[str, str], ...]  # (name, reason)


def plan_bulk(kind: ActionKind, states: Iterable[RepoState]) -> BulkPlan:
    """What Push all / Pull all / Sync all would do, computed from a snapshot.

    Push all pushes every repo that is only ahead, Pull all pulls every repo that is only behind,
    Sync all does both and also syncs diverged repos. Diverged repos are listed as skipped by
    Push all / Pull all; repos whose action is blocked (e.g. uncommitted changes) are skipped.
    """
    jobs: list[tuple[ActionKind, RepoInfo]] = []
    skipped: list[tuple[str, str]] = []
    for s in states:
        k = smart_kind(s)
        if k is None:
            continue
        if kind is not ActionKind.SYNC and k is not kind:
            if k is ActionKind.SYNC:
                skipped.append((s.name, "Diverged — use Sync"))
            continue
        reason = block_reason(k, s)
        if reason:
            skipped.append((s.name, reason))
        else:
            jobs.append((k, s.info))
    return BulkPlan(kind, tuple(jobs), tuple(skipped))


def summarize_bulk(
    plan: BulkPlan, results: Sequence[ActionResult], started: float, now: float
) -> ActionResult:
    ok = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    parts = [f"{_BULK_DONE[plan.kind]} {len(ok)} of {len(results)}"]
    if failed:
        parts.append(f"{len(failed)} failed")
    if plan.skipped:
        reasons: dict[str, list[str]] = {}
        for name, reason in plan.skipped:
            reasons.setdefault(reason.lower(), []).append(name)
        detail = "; ".join(f"{r}: {', '.join(n)}" for r, n in reasons.items())
        parts.append(f"{len(plan.skipped)} skipped ({detail})")
    if not results and not plan.skipped:
        parts = [f"Nothing to {plan.kind.value}"]
    details = "\n".join(
        f"{'ok ' if r.ok else 'FAIL'} {r.action.value:5} {r.name}: {r.message}" for r in results
    )
    return ActionResult(
        repo=Path(),
        action=plan.kind,
        ok=not failed,
        message=" · ".join(parts),
        stdout=details,
        started_at=started,
        duration=now - started,
        name=BULK_NAMES[plan.kind],
    )
