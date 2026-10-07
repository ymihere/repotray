"""Data types shared by every layer. Stdlib only."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class ActionKind(StrEnum):
    FETCH = "fetch"
    PUSH = "push"
    PULL = "pull"
    SYNC = "sync"


class FetchMode(StrEnum):
    IDLE = "idle"
    FETCHING = "fetching"
    PAUSED = "paused"
    BACKOFF = "backoff"


@dataclass(frozen=True, slots=True)
class RepoInfo:
    """A discovered repository."""

    path: Path
    git_dir: Path
    name: str
    fetch_enabled: bool = True


@dataclass(frozen=True, slots=True)
class RepoState:
    """The result of one status check of a repository."""

    info: RepoInfo
    branch: str | None = None
    oid: str | None = None
    upstream: str | None = None
    upstream_remote: str | None = None
    upstream_merge: str | None = None
    ahead: int = 0
    behind: int = 0
    staged: int = 0
    unstaged: int = 0
    unmerged: int = 0
    untracked: int = 0
    detached: bool = False
    upstream_gone: bool = False
    operation: str | None = None
    status_error: str | None = None
    fetch_error: str | None = None
    fetched_at: float | None = None
    checked_at: float = 0.0

    @property
    def path(self) -> Path:
        return self.info.path

    @property
    def name(self) -> str:
        return self.info.name

    @property
    def tracked_changes(self) -> bool:
        return self.staged + self.unstaged + self.unmerged > 0

    def dirty(self, count_untracked: bool = True) -> bool:
        return self.tracked_changes or (count_untracked and self.untracked > 0)

    @property
    def has_upstream(self) -> bool:
        return bool(self.upstream) and not self.upstream_gone

    @property
    def pushable(self) -> bool:
        return self.has_upstream and self.ahead > 0 and not self.detached

    @property
    def pullable(self) -> bool:
        return self.has_upstream and self.behind > 0 and not self.detached

    @property
    def diverged(self) -> bool:
        return self.pushable and self.pullable

    @property
    def no_upstream(self) -> bool:
        """On a branch, but without a usable upstream (none configured, or gone)."""
        return not self.detached and not self.has_upstream and self.status_error is None


@dataclass(frozen=True, slots=True)
class ActionResult:
    repo: Path
    action: ActionKind
    ok: bool
    message: str
    command: tuple[str, ...] = ()
    stdout: str = ""
    stderr: str = ""
    started_at: float = 0.0
    duration: float = 0.0
    restored: bool | None = None
    name: str = ""


@dataclass(frozen=True, slots=True)
class Snapshot:
    repos: tuple[RepoState, ...] = ()
    generated_at: float = 0.0
    fetch_mode: FetchMode = FetchMode.IDLE
    last_fetch_pass_at: float | None = None
    next_fetch_at: float | None = None
    all_fetches_failed: bool = False
    git_missing: bool = False
    running: Mapping[Path, ActionKind] = field(default_factory=dict)
    bulk: tuple[ActionKind, int, int] | None = None  # (kind, done, total) of a running "… all"
    recent_results: tuple[ActionResult, ...] = ()
    config_warning: str | None = None
