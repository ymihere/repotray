"""Snapshot → PanelModel and menu models. Pure functions, no I/O.

All user-visible strings of the panel and menus are produced here, so a GUI only lays them out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from repotray.core.actions import (
    block_reason,
    plan_sync_all,
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
class Footer:
    sync_all: Button
    label: str


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
    footer: Footer
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
    )


def _key(s: RepoState) -> tuple[str, str]:
    return (s.name.casefold(), str(s.path))


def build_rows(snapshot: Snapshot, config: Config) -> tuple[Row, ...]:
    repos = sorted(snapshot.repos, key=_key)
    rows: list[Row] = []
    for s in repos:
        if s.diverged:
            rows.append(
                Row(
                    left=_cell(s, snapshot, config, "left"),
                    sync=sync_button(s, snapshot, config),
                    right=_cell(s, snapshot, config, "right"),
                    sync_path=s.path,
                )
            )
    push = [s for s in repos if s.pushable and not s.diverged]
    pull = [s for s in repos if s.pullable and not s.diverged]
    for i in range(max(len(push), len(pull))):
        left = _cell(push[i], snapshot, config, "left") if i < len(push) else None
        right = _cell(pull[i], snapshot, config, "right") if i < len(pull) else None
        rows.append(Row(left=left, sync=None, right=right))
    return tuple(rows)


def build_groups(snapshot: Snapshot, config: Config) -> tuple[Group, ...]:
    repos = sorted(snapshot.repos, key=_key)

    def chips(items: list[RepoState], tip=None) -> tuple[Chip, ...]:
        return tuple(
            Chip(s.path, s.name, tip(s) if tip else repo_tooltip(s, config)) for s in items
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
    if r.name == "Sync all":
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


def build_footer(snapshot: Snapshot) -> Footer:
    if snapshot.sync_all is not None:
        done, total = snapshot.sync_all
        return Footer(
            Button(ActionKind.SYNC, False, True, "Sync all is running"),
            f"Syncing {done}/{total}…",
        )
    plan = plan_sync_all(s for s in snapshot.repos if s.path not in snapshot.running)
    if not plan.jobs:
        tip = "Nothing to push or pull"
        if plan.skipped:
            tip += f" ({len(plan.skipped)} skipped: {plan.skipped[0][1].lower()})"
        return Footer(Button(ActionKind.SYNC, False, False, tip), "Sync all")
    kinds = [k for k, _ in plan.jobs]
    bits = []
    for k, word in (
        (ActionKind.PUSH, "push"),
        (ActionKind.PULL, "pull"),
        (ActionKind.SYNC, "sync"),
    ):
        n = kinds.count(k)
        if n:
            bits.append(f"{word} {n}")
    tip = "Sync all: " + ", ".join(bits)
    if plan.skipped:
        tip += f"; skips {', '.join(n for n, _ in plan.skipped)} ({plan.skipped[0][1].lower()})"
    return Footer(Button(ActionKind.SYNC, True, False, tip), "Sync all")


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
        footer=build_footer(snapshot),
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


def repo_menu(path: Path) -> tuple[MenuItem, ...]:
    return (
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
                MenuItem(ch.name, None, children=repo_menu(ch.path), tooltip=ch.tooltip)
                for ch in g.chips
            )
            items.append(MenuItem(g.title, None, children=children))
    footer = build_footer(snapshot)
    items.append(MenuItem.sep())
    items.append(
        MenuItem(
            footer.label,
            "sync_all",
            enabled=footer.sync_all.enabled,
            tooltip=footer.sync_all.tooltip,
        )
    )
    items.append(MenuItem.sep())
    items += control_menu(snapshot, ui)
    return tuple(items)


__all__ = [
    "Banner",
    "Button",
    "Cell",
    "Chip",
    "Footer",
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
