"""Snapshot → PanelModel and menu models. Pure functions, no I/O.

All user-visible strings of the panel and menus are produced here, so a GUI only lays them out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from repotray.core.actions import (
    BULK_NAMES,
    block_reason,
    plan_bulk,
    plural,
    pull_block_reason,
    push_block_reason,
    sync_block_reason,
)
from repotray.core.config import Config
from repotray.core.indicator import counts
from repotray.core.types import ActionKind, ActionResult, FetchMode, RepoState, Snapshot

SUCCESS_BANNER_SECONDS = 6.0

ACTION_ICONS = {
    ActionKind.PUSH: "go-up-symbolic",
    ActionKind.PULL: "go-down-symbolic",
    ActionKind.SYNC: "emblem-synchronizing-symbolic",
    ActionKind.FETCH: "view-refresh-symbolic",
}
ICON_WARNING = "dialog-warning-symbolic"
ICON_DIRTY = "document-edit-symbolic"
ICON_OK = "object-select-symbolic"
ICON_GEAR = "emblem-system-symbolic"

_BUSY_VERB = {
    ActionKind.PUSH: "pushing",
    ActionKind.PULL: "pulling",
    ActionKind.SYNC: "syncing",
    ActionKind.FETCH: "fetching",
}
_DONE_VERB = {
    ActionKind.PUSH: "Pushed",
    ActionKind.PULL: "Pulled",
    ActionKind.SYNC: "Synced",
    ActionKind.FETCH: "Fetched",
}


@dataclass(frozen=True, slots=True)
class Button:
    action: ActionKind
    enabled: bool
    busy: bool
    tooltip: str


@dataclass(frozen=True, slots=True)
class Cell:
    path: Path
    name: str
    tooltip: str
    count_text: str
    dirty: bool
    warning: str | None
    button: Button
    menu: tuple[MenuItem, ...] = ()  # context menu of the repo name


@dataclass(frozen=True, slots=True)
class Row:
    left: Cell | None
    sync: Button | None
    right: Cell | None
    sync_path: Path | None = None


@dataclass(frozen=True, slots=True)
class Chip:
    path: Path
    name: str
    tooltip: str
    menu: tuple[MenuItem, ...] = ()


@dataclass(frozen=True, slots=True)
class Group:
    kind: str
    title: str
    icon_name: str
    chips: tuple[Chip, ...]
    collapsed: bool = False


@dataclass(frozen=True, slots=True)
class Header:
    summary: str
    fetched_text: str
    fetching: bool
    paused: bool
    warning: str | None
    error: bool = False


@dataclass(frozen=True, slots=True)
class BulkButton:
    action: ActionKind  # PUSH = Push all, PULL = Pull all, SYNC = Sync all
    label: str  # "Push all" / "Pushing 2/5…"
    enabled: bool
    busy: bool
    tooltip: str


@dataclass(frozen=True, slots=True)
class BulkBar:
    """Push all · Sync all · Pull all, at the top of the panel."""

    push: BulkButton
    sync: BulkButton
    pull: BulkButton


@dataclass(frozen=True, slots=True)
class Banner:
    kind: str  # "success" | "error"
    text: str
    result: ActionResult | None
    expires_at: float | None


@dataclass(frozen=True, slots=True)
class PanelModel:
    header: Header
    columns_title: tuple[str, str]
    rows: tuple[Row, ...]
    empty_text: str | None
    groups: tuple[Group, ...]
    bulk: BulkBar
    banner: Banner | None


@dataclass(frozen=True, slots=True)
class MenuItem:
    label: str = ""
    action: str | None = None  # see Controller.dispatch
    enabled: bool = True
    checked: bool | None = None  # None = not a check item
    children: tuple[MenuItem, ...] = ()
    separator: bool = False
    path: Path | None = None
    tooltip: str = ""
    icon_name: str = ""

    @staticmethod
    def sep() -> MenuItem:
        return MenuItem(separator=True)


@dataclass(frozen=True, slots=True)
class UiState:
    """Controller-side state the model needs besides the snapshot."""

    banner_ack: float = 0.0  # failures finished before this time are acknowledged
    autostart: bool = False
    extras: dict = field(default_factory=dict)


# --- text helpers --------------------------------------------------------------------------------


def ago(t: float | None, now: float) -> str:
    if t is None:
        return "never"
    d = max(0.0, now - t)
    if d < 60:
        return "just now"
    if d < 3600:
        return f"{int(d // 60)} min ago"
    if d < 86400:
        return f"{int(d // 3600)} h ago"
    return f"{int(d // 86400)} d ago"


def fetched_text(snapshot: Snapshot, now: float) -> str:
    if snapshot.last_fetch_pass_at is None:
        return "Never fetched"
    return f"Fetched {ago(snapshot.last_fetch_pass_at, now)}"


def minutes_until(t: float | None, now: float) -> str:
    if t is None:
        return "later"
    d = max(0.0, t - now)
    if d < 60:
        return "in less than a minute"
    return f"in {round(d / 60)} min"


def _abbrev(path: Path) -> str:
    home = Path.home()
    try:
        return "~/" + str(path.relative_to(home))
    except ValueError:
        return str(path)


def repo_tooltip(s: RepoState, config: Config) -> str:
    lines = [_abbrev(s.path)]
    if s.detached:
        lines.append("HEAD detached")
    elif s.branch:
        up = s.upstream or "no upstream"
        if s.upstream_gone:
            up = f"{s.upstream} (gone)"
        lines.append(f"{s.branch} → {up}")
    if s.dirty(config.count_untracked_as_dirty):
        bits = []
        if s.staged:
            bits.append(f"{s.staged} staged")
        if s.unstaged:
            bits.append(f"{s.unstaged} modified")
        if s.unmerged:
            bits.append(f"{s.unmerged} unmerged")
        if s.untracked:
            bits.append(f"{s.untracked} untracked")
        lines.append("Uncommitted: " + ", ".join(bits) + " (push sends commits only)")
    if s.operation:
        lines.append(f"{s.operation} in progress")
    if s.fetch_error:
        lines.append(f"Fetch failed: {s.fetch_error}")
    if s.status_error:
        lines.append(f"Status failed: {s.status_error}")
    return "\n".join(lines)


def summary(snapshot: Snapshot, config: Config, now: float) -> tuple[str, bool]:
    """Header sentence and whether it reports an error."""
    if snapshot.git_missing:
        return "git not found — install git to use repotray", True
    if snapshot.fetch_mode is FetchMode.FETCHING:
        return "Fetching…", False
    if snapshot.all_fetches_failed:
        retry = minutes_until(snapshot.next_fetch_at, now)
        return f"Offline — fetch failed for every repo, retrying {retry}", True
    if snapshot.fetch_mode is FetchMode.PAUSED:
        return "Fetching paused", False
    n = sum(
        1
        for s in snapshot.repos
        if s.pushable or s.pullable or s.dirty(config.count_untracked_as_dirty)
    )
    total = len(snapshot.repos)
    if total == 0:
        return "No repositories found", False
    if n == 0:
        return (f"All {total} repos in sync" if total != 1 else "The repo is in sync"), False
    return (f"{n} repo needs attention" if n == 1 else f"{n} repos need attention"), False


# --- panel ---------------------------------------------------------------------------------------


def _latest_result(snapshot: Snapshot, path: Path) -> ActionResult | None:
    for r in snapshot.recent_results:
        if r.repo == path:
            return r
    return None


def _warning(snapshot: Snapshot, s: RepoState) -> str | None:
    last = _latest_result(snapshot, s.path)
    if last is not None and not last.ok and last.action is not ActionKind.FETCH:
        return last.message
    return s.fetch_error or s.status_error


def _button(
    kind: ActionKind,
    s: RepoState,
    snapshot: Snapshot,
    tooltip_ok: str,
    reason: str | None,
) -> Button:
    running = snapshot.running.get(s.path)
    if running is not None:
        busy = running is kind
        return Button(kind, False, busy, f"Busy: {_BUSY_VERB[running]}…")
    if reason:
        return Button(kind, False, False, reason)
    return Button(kind, True, False, tooltip_ok)


def push_button(s: RepoState, snapshot: Snapshot) -> Button:
    tip = f"Push {plural(s.ahead, 'commit')} to {s.upstream}"
    return _button(ActionKind.PUSH, s, snapshot, tip, push_block_reason(s))


def pull_button(s: RepoState, snapshot: Snapshot) -> Button:
    tip = f"Pull {plural(s.behind, 'commit')} from {s.upstream} (fast-forward)"
    return _button(ActionKind.PULL, s, snapshot, tip, pull_block_reason(s))


def sync_button(s: RepoState, snapshot: Snapshot, config: Config) -> Button:
    if config.sync_strategy == "merge":
        tip = "Sync: merge, then push"
    else:
        tip = "Sync: pull --rebase, then push"
    return _button(ActionKind.SYNC, s, snapshot, tip, sync_block_reason(s))


def _cell(s: RepoState, snapshot: Snapshot, config: Config, side: str) -> Cell:
    if side == "left":
        count, button = f"↑{s.ahead}", push_button(s, snapshot)
    else:
        count, button = f"↓{s.behind}", pull_button(s, snapshot)
    return Cell(
        path=s.path,
        name=s.name,
        tooltip=repo_tooltip(s, config),
        count_text=count,
        dirty=s.dirty(config.count_untracked_as_dirty),
        warning=_warning(snapshot, s),
        button=button,
        menu=repo_menu(s.path, s.behind if s.pullable else 0),
    )


def _key(s: RepoState) -> tuple[str, str]:
    return (s.name.casefold(), str(s.path))


def _state_rank(s: RepoState) -> int:
    return 0 if s.diverged else (1 if s.pushable else 2)


def build_rows(snapshot: Snapshot, config: Config) -> tuple[Row, ...]:
    """One row per repo with something to push or pull: its push cell on the left, its pull
    cell on the right, and a Sync button in the middle when it diverged.

    Sorted by name, or with ``panel_sort = "state"`` syncable first, then pushable, then pullable
    (each by name).
    """
    repos = [s for s in snapshot.repos if s.pushable or s.pullable]
    if config.panel_sort == "state":
        repos.sort(key=lambda s: (_state_rank(s), *_key(s)))
    else:
        repos.sort(key=_key)
    return tuple(
        Row(
            left=_cell(s, snapshot, config, "left") if s.pushable else None,
            sync=sync_button(s, snapshot, config) if s.diverged else None,
            right=_cell(s, snapshot, config, "right") if s.pullable else None,
            sync_path=s.path if s.diverged else None,
        )
        for s in repos
    )


def build_groups(snapshot: Snapshot, config: Config) -> tuple[Group, ...]:
    repos = sorted(snapshot.repos, key=_key)

    def chips(items: list[RepoState], tip=None) -> tuple[Chip, ...]:
        return tuple(
            Chip(
                s.path,
                s.name,
                tip(s) if tip else repo_tooltip(s, config),
                repo_menu(s.path, s.behind if s.pullable else 0),
            )
            for s in items
        )

    groups: list[Group] = []
    dirty = [s for s in repos if s.dirty(config.count_untracked_as_dirty)]
    if dirty:
        groups.append(Group("dirty", f"Uncommitted ({len(dirty)})", ICON_DIRTY, chips(dirty)))
    no_up = [s for s in repos if s.no_upstream]
    if no_up:

        def no_up_tip(s: RepoState) -> str:
            if s.upstream_gone:
                why = f"Upstream {s.upstream} is gone"
            else:
                why = "No upstream branch configured"
            return f"{why}\n{repo_tooltip(s, config)}"

        groups.append(
            Group(
                "no_upstream", f"No upstream ({len(no_up)})", ICON_WARNING, chips(no_up, no_up_tip)
            )
        )
    detached = [s for s in repos if s.detached]
    if detached:
        groups.append(Group("detached", f"Detached ({len(detached)})", "", chips(detached)))
    ops = [s for s in repos if s.operation]
    if ops:
        groups.append(
            Group(
                "in_progress",
                f"In progress ({len(ops)})",
                ICON_WARNING,
                chips(ops, lambda s: f"{s.operation} in progress\n{repo_tooltip(s, config)}"),
            )
        )
    failed = [s for s in repos if s.fetch_error]
    if failed:
        groups.append(
            Group(
                "fetch_failed",
                f"Fetch failed ({len(failed)})",
                ICON_WARNING,
                chips(failed, lambda s: f"{s.fetch_error}\n{_abbrev(s.path)}"),
            )
        )
    broken = [s for s in repos if s.status_error]
    if broken:
        groups.append(
            Group(
                "status_failed",
                f"Unreadable ({len(broken)})",
                ICON_WARNING,
                chips(broken, lambda s: f"{s.status_error}\n{_abbrev(s.path)}"),
            )
        )
    clean = [
        s
        for s in repos
        if not (
            s.dirty(config.count_untracked_as_dirty)
            or s.pushable
            or s.pullable
            or s.no_upstream
            or s.detached
            or s.operation
            or s.fetch_error
            or s.status_error
        )
    ]
    if clean:
        groups.append(Group("in_sync", f"In sync ({len(clean)})", "", chips(clean), True))
    return tuple(groups)


def result_end(r: ActionResult) -> float:
    return r.started_at + r.duration


def result_text(r: ActionResult) -> str:
    if r.name in BULK_NAMES.values():
        return r.message
    if r.ok:
        return f"{_DONE_VERB[r.action]} {r.name}"
    return f"{r.name}: {r.message}"


def build_banner(snapshot: Snapshot, now: float, ack: float) -> Banner | None:
    for r in snapshot.recent_results:
        end = result_end(r)
        if not r.ok and end > ack:
            return Banner("error", result_text(r), r, None)
        if r.ok and now - end < SUCCESS_BANNER_SECONDS:
            return Banner("success", result_text(r), r, end + SUCCESS_BANNER_SECONDS)
        if r.ok:
            continue
    return None


_BULK_ING = {ActionKind.PUSH: "Pushing", ActionKind.PULL: "Pulling", ActionKind.SYNC: "Syncing"}


def _bulk_button(kind: ActionKind, snapshot: Snapshot) -> BulkButton:
    name = BULK_NAMES[kind]
    if snapshot.bulk is not None:
        running, done, total = snapshot.bulk
        if running is kind:
            return BulkButton(kind, f"{_BULK_ING[kind]} {done}/{total}…", False, True, f"{name}…")
        return BulkButton(kind, name, False, False, f"Busy: {BULK_NAMES[running]} is running")
    plan = plan_bulk(kind, (s for s in snapshot.repos if s.path not in snapshot.running))
    skipped = ""
    if plan.skipped:
        names = ", ".join(n for n, _ in plan.skipped)
        skipped = f"; skips {names} ({plan.skipped[0][1].lower()})"
    if not plan.jobs:
        what = "push or pull" if kind is ActionKind.SYNC else kind.value
        return BulkButton(kind, name, False, False, f"Nothing to {what}{skipped}")
    if kind is ActionKind.SYNC:
        kinds = [k for k, _ in plan.jobs]
        bits = [
            f"{word} {kinds.count(k)}"
            for k, word in ((ActionKind.PUSH, "push"), (ActionKind.PULL, "pull"),
                            (ActionKind.SYNC, "sync"))
            if kinds.count(k)
        ]  # fmt: skip
        tip = "Sync all: " + ", ".join(bits)
    else:
        repos = ", ".join(i.name for _, i in plan.jobs)
        tip = f"{kind.value.capitalize()} {plural(len(plan.jobs), 'repo')}: {repos}"
    return BulkButton(kind, name, True, False, tip + skipped)


def build_bulk(snapshot: Snapshot) -> BulkBar:
    return BulkBar(
        push=_bulk_button(ActionKind.PUSH, snapshot),
        sync=_bulk_button(ActionKind.SYNC, snapshot),
        pull=_bulk_button(ActionKind.PULL, snapshot),
    )


def panel_model(
    snapshot: Snapshot, config: Config, now: float, ui: UiState | None = None
) -> PanelModel:
    ui = ui or UiState()
    text, is_error = summary(snapshot, config, now)
    c = counts(snapshot, config)
    header = Header(
        summary=text,
        fetched_text=fetched_text(snapshot, now),
        fetching=snapshot.fetch_mode is FetchMode.FETCHING,
        paused=snapshot.fetch_mode is FetchMode.PAUSED,
        warning=snapshot.config_warning,
        error=is_error,
    )
    rows = build_rows(snapshot, config)
    n_push = sum(1 for s in snapshot.repos if s.pushable)
    return PanelModel(
        header=header,
        columns_title=(f"Push ({n_push})", f"Pull ({c.pull})"),
        rows=rows,
        empty_text=None if rows else "Nothing to push or pull",
        groups=build_groups(snapshot, config),
        bulk=build_bulk(snapshot),
        banner=build_banner(snapshot, now, ui.banner_ack),
    )


# --- menus ---------------------------------------------------------------------------------------


def control_menu(snapshot: Snapshot, ui: UiState | None = None) -> tuple[MenuItem, ...]:
    ui = ui or UiState()
    return (
        MenuItem("Fetch all now", "fetch_all", icon_name="view-refresh-symbolic"),
        MenuItem("Pause fetching", "toggle_pause", checked=snapshot.fetch_mode is FetchMode.PAUSED),
        MenuItem("Rescan roots", "rescan"),
        MenuItem("Open config file", "open_config"),
        MenuItem.sep(),
        MenuItem("Autostart", "toggle_autostart", checked=ui.autostart),
        MenuItem("About", "about"),
        MenuItem("Quit", "quit"),
    )


def repo_menu(path: Path, behind: int = 0) -> tuple[MenuItem, ...]:
    """The context menu of a repo name. ``behind`` > 0 adds the incoming-commits viewer."""
    incoming = ()
    if behind > 0:
        label = f"Show incoming commits ({behind})…"
        tip = "The commit messages a pull would bring, as of the last fetch"
        incoming = (MenuItem(label, "show_incoming", path=path, tooltip=tip), MenuItem.sep())
    return (
        *incoming,
        MenuItem("Open terminal here", "open_terminal", path=path),
        MenuItem("Open folder", "open_folder", path=path),
        MenuItem("Copy path", "copy_path", path=path),
        MenuItem("Fetch now", "fetch", path=path),
    )


def _action_item(kind: ActionKind, s: RepoState, snapshot: Snapshot, config: Config) -> MenuItem:
    if kind is ActionKind.PUSH:
        b, extra = push_button(s, snapshot), f"↑{s.ahead}"
    elif kind is ActionKind.PULL:
        b, extra = pull_button(s, snapshot), f"↓{s.behind}"
    else:
        b, extra = sync_button(s, snapshot, config), f"↑{s.ahead} ↓{s.behind}"
    verb = kind.value.capitalize()
    dirty = " ✎" if s.dirty(config.count_untracked_as_dirty) else ""
    label = f"{verb} {s.name}  {extra}{dirty}"
    if b.busy:
        label += " …"
    return MenuItem(label, kind.value, enabled=b.enabled, path=s.path, tooltip=b.tooltip)


def fallback_menu(
    snapshot: Snapshot,
    config: Config,
    now: float,
    ui: UiState | None = None,
    open_panel: bool = False,
) -> tuple[MenuItem, ...]:
    """The panel rendered as a menu, for backends without a popup window (SPEC §2.3)."""
    items: list[MenuItem] = []
    if open_panel:
        items += [MenuItem("Open panel…", "open_panel"), MenuItem.sep()]
    text, _ = summary(snapshot, config, now)
    items.append(MenuItem(f"{text} · {fetched_text(snapshot, now)}", None, enabled=False))
    banner = build_banner(snapshot, now, (ui or UiState()).banner_ack)
    if banner:
        mark = "✓" if banner.kind == "success" else "⚠"
        items.append(MenuItem(f"{mark} {banner.text}", "ack_banner"))
    repos = sorted(snapshot.repos, key=_key)
    diverged = [s for s in repos if s.diverged]
    push = [s for s in repos if s.pushable and not s.diverged]
    pull = [s for s in repos if s.pullable and not s.diverged]
    for title, kind, lst in (
        ("Sync", ActionKind.SYNC, diverged),
        ("Push", ActionKind.PUSH, push),
        ("Pull", ActionKind.PULL, pull),
    ):
        if lst:
            items.append(MenuItem.sep())
            items.append(MenuItem(f"{title} ({len(lst)})", None, enabled=False))
            items += [_action_item(kind, s, snapshot, config) for s in lst]
    groups = build_groups(snapshot, config)
    if groups:
        items.append(MenuItem.sep())
        for g in groups:
            children = tuple(
                MenuItem(ch.name, None, children=ch.menu, tooltip=ch.tooltip) for ch in g.chips
            )
            items.append(MenuItem(g.title, None, children=children))
    bulk = build_bulk(snapshot)
    items.append(MenuItem.sep())
    for b, action in ((bulk.push, "push_all"), (bulk.pull, "pull_all"), (bulk.sync, "sync_all")):
        items.append(MenuItem(b.label, action, enabled=b.enabled, tooltip=b.tooltip))
    items.append(MenuItem.sep())
    items += control_menu(snapshot, ui)
    return tuple(items)


__all__ = [
    "Banner",
    "BulkBar",
    "BulkButton",
    "Button",
    "Cell",
    "Chip",
    "Group",
    "Header",
    "MenuItem",
    "PanelModel",
    "Row",
    "UiState",
    "block_reason",
    "control_menu",
    "fallback_menu",
    "panel_model",
    "repo_menu",
]
