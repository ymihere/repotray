"""Porcelain v2 parser and the per-repo status / fetch calls."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, replace
from pathlib import Path

from repotray.core.gitrun import CallKind, GitResult, Runner, first_line
from repotray.core.types import RepoInfo, RepoState

STATUS_TIMEOUT = 15.0
QUERY_TIMEOUT = 15.0


@dataclass(slots=True)
class ParsedStatus:
    branch: str | None = None
    oid: str | None = None
    upstream: str | None = None
    ahead: int = 0
    behind: int = 0
    has_ab: bool = False
    detached: bool = False
    staged: int = 0
    unstaged: int = 0
    unmerged: int = 0
    untracked: int = 0


def parse_porcelain_v2(data: bytes) -> ParsedStatus:
    """Parse ``git status --porcelain=v2 --branch -z`` output.

    Only the start of each NUL-terminated record is inspected; ``2`` records (renames/copies)
    are followed by one extra field holding the original path, which is consumed and skipped,
    so no path content can be mistaken for a record.
    """
    st = ParsedStatus()
    fields = data.split(b"\0")
    i = 0
    n = len(fields)
    while i < n:
        rec = fields[i]
        i += 1
        if not rec:
            continue
        tag = rec[:2]
        if rec.startswith(b"# "):
            _parse_header(st, rec[2:].decode("utf-8", errors="replace"))
        elif tag == b"1 ":
            _count_xy(st, rec[2:4])
        elif tag == b"2 ":
            _count_xy(st, rec[2:4])
            i += 1  # original path
        elif tag == b"u ":
            st.unmerged += 1
        elif tag == b"? ":
            st.untracked += 1
        # "! " ignored entries and anything unknown are skipped.
    return st


def _count_xy(st: ParsedStatus, xy: bytes) -> None:
    if len(xy) < 2:
        return
    if xy[0:1] != b".":
        st.staged += 1
    if xy[1:2] != b".":
        st.unstaged += 1


def _parse_header(st: ParsedStatus, line: str) -> None:
    key, _, value = line.partition(" ")
    if key == "branch.oid":
        st.oid = None if value == "(initial)" else value
    elif key == "branch.head":
        if value == "(detached)":
            st.detached = True
            st.branch = None
        else:
            st.branch = value
    elif key == "branch.upstream":
        st.upstream = value
    elif key == "branch.ab":
        m = re.fullmatch(r"\+(\d+) -(\d+)", value)
        if m:
            st.ahead, st.behind = int(m.group(1)), int(m.group(2))
            st.has_ab = True


def detect_operation(git_dir: Path) -> str | None:
    try:
        if (git_dir / "rebase-merge").is_dir() or (git_dir / "rebase-apply").is_dir():
            return "rebase"
        if (git_dir / "MERGE_HEAD").exists():
            return "merge"
        if (git_dir / "CHERRY_PICK_HEAD").exists():
            return "cherry-pick"
        if (git_dir / "REVERT_HEAD").exists():
            return "revert"
        if (git_dir / "BISECT_LOG").exists():
            return "bisect"
    except OSError:
        return None
    return None


def _ere_escape(text: str) -> str:
    """Escape for POSIX extended regular expressions (what git config uses)."""
    return re.sub(r"([.\[\]{}()\\*+?^$|])", r"\\\1", text)


def upstream_config(runner: Runner, path: Path, branch: str) -> tuple[str | None, str | None]:
    """(branch.<b>.remote, branch.<b>.merge) from one config call."""
    pattern = r"^branch\." + _ere_escape(branch) + r"\.(remote|merge)$"
    res = runner(["config", "--get-regexp", pattern], path, QUERY_TIMEOUT, kind=CallKind.QUERY)
    remote = merge = None
    if res.ok:
        prefix = f"branch.{branch}."
        for line in res.out.splitlines():
            key, _, value = line.partition(" ")
            if key.lower() == (prefix + "remote").lower():
                remote = value
            elif key.lower() == (prefix + "merge").lower():
                merge = value
    return remote, merge


def status_args(count_untracked: bool) -> list[str]:
    return [
        "status",
        "--porcelain=v2",
        "--branch",
        "-z",
        "--untracked-files=normal" if count_untracked else "--untracked-files=no",
    ]


def check_status(
    runner: Runner,
    info: RepoInfo,
    *,
    count_untracked: bool = True,
    previous: RepoState | None = None,
    now: float | None = None,
) -> RepoState:
    """Run one status check. Fetch bookkeeping is carried over from ``previous``."""
    now = time.time() if now is None else now
    keep = {
        "fetch_error": previous.fetch_error if previous else None,
        "fetched_at": previous.fetched_at if previous else None,
    }
    res = runner(status_args(count_untracked), info.path, STATUS_TIMEOUT, kind=CallKind.STATUS)
    if not res.ok:
        msg = first_line(res.err, res.out) or f"git status exited with {res.returncode}"
        return RepoState(info=info, status_error=msg, checked_at=now, **keep)
    st = parse_porcelain_v2(res.stdout)
    remote = merge = None
    if st.upstream and st.branch:
        remote, merge = upstream_config(runner, info.path, st.branch)
    return RepoState(
        info=info,
        branch=st.branch,
        oid=st.oid,
        upstream=st.upstream,
        upstream_remote=remote,
        upstream_merge=merge,
        ahead=st.ahead,
        behind=st.behind,
        staged=st.staged,
        unstaged=st.unstaged,
        unmerged=st.unmerged,
        untracked=st.untracked,
        detached=st.detached,
        upstream_gone=bool(st.upstream) and not st.has_ab,
        operation=detect_operation(info.git_dir),
        checked_at=now,
        **keep,
    )


FETCH_ARGS = ("fetch", "--quiet", "--no-write-fetch-head", "--recurse-submodules=no")


def fetch_repo(runner: Runner, path: Path, timeout: float) -> GitResult:
    return runner(list(FETCH_ARGS), path, timeout, kind=CallKind.FETCH)


def apply_fetch_result(state: RepoState, res: GitResult, now: float) -> RepoState:
    if res.ok:
        return replace(state, fetch_error=None, fetched_at=now)
    msg = first_line(res.err, res.out) or f"git fetch exited with {res.returncode}"
    return replace(state, fetch_error=msg)
