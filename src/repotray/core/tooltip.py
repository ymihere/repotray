"""Snapshot → tooltip text (SPEC §2.2)."""

from __future__ import annotations

import html

from repotray.core.config import Config
from repotray.core.indicator import counts
from repotray.core.model import fetched_text, summary
from repotray.core.types import FetchMode, RepoState, Snapshot

MAX_REPO_LINES = 15
CHIP_LINE_CHARS = 48


def _key(s: RepoState) -> tuple[str, str]:
    return (s.name.casefold(), str(s.path))


def _panel_order(repos: list[RepoState]) -> list[RepoState]:
    """Diverged first, then by name — the panel's order."""
    return sorted(repos, key=lambda s: (not s.diverged, *_key(s)))


def tooltip_text(
    snapshot: Snapshot,
    config: Config,
    now: float,
    *,
    markup: bool = False,
    max_chars: int | None = None,
) -> str:
    if max_chars is not None:
        return _summary_line(snapshot, config, now, max_chars)

    esc = html.escape if markup else (lambda s: s)

    def title(t: str) -> str:
        return f"<b>{esc(t)}</b>" if markup else t

    untracked = config.count_untracked_as_dirty
    repos = list(snapshot.repos)
    push = _panel_order([s for s in repos if s.pushable])
    pull = _panel_order([s for s in repos if s.pullable])
    dirty = sorted((s for s in repos if s.dirty(untracked)), key=_key)
    no_up = sorted((s for s in repos if s.no_upstream), key=_key)

    lines: list[str] = []
    text, is_error = summary(snapshot, config, now)
    if is_error or snapshot.fetch_mode in (FetchMode.PAUSED, FetchMode.FETCHING):
        lines.append(title(text))
    elif not (push or pull or dirty):
        lines.append(text)

    budget = MAX_REPO_LINES
    hidden = 0
    width = max((len(s.name) for s in push + pull), default=0)

    def repo_line(s: RepoState, count: str) -> str:
        mark = "  ✎" if s.dirty(untracked) else ""
        if markup:
            return f"  {esc(s.name)}  {count}{mark}"
        return f"  {s.name.ljust(width)}  {count}{mark}"

    for name, lst, count in (
        ("Push", push, lambda s: f"↑{s.ahead}"),
        ("Pull", pull, lambda s: f"↓{s.behind}"),
    ):
        if not lst:
            continue
        lines.append(title(f"{name} ({len(lst)})"))
        for s in lst:
            if budget > 0:
                lines.append(repo_line(s, count(s)))
                budget -= 1
            else:
                hidden += 1

    if dirty:
        lines.append(title(f"Uncommitted ({len(dirty)})"))
        chunk: list[str] = []
        for s in dirty:
            if budget <= 0:
                hidden += 1
                continue
            if chunk and len("  ".join([*chunk, s.name])) > CHIP_LINE_CHARS:
                lines.append("  " + esc("  ".join(chunk)))
                budget -= 1
                chunk = []
                if budget <= 0:
                    hidden += 1
                    continue
            chunk.append(s.name)
        if chunk:
            lines.append("  " + esc("  ".join(chunk)))
            budget -= 1

    if no_up:
        names = ", ".join(s.name for s in no_up[:6])
        more = f" … +{len(no_up) - 6}" if len(no_up) > 6 else ""
        lines.append(f"{title(f'No upstream ({len(no_up)})')}: {esc(names)}{more}")

    failed = [s for s in repos if s.fetch_error]
    if failed and not snapshot.all_fetches_failed:
        names = ", ".join(s.name for s in failed[:6])
        lines.append(f"{title(f'Fetch failed ({len(failed)})')}: {esc(names)}")

    if hidden:
        lines.append(f"… and {hidden} more")
    lines.append(fetched_text(snapshot, now))
    return "\n".join(lines)


def _summary_line(snapshot: Snapshot, config: Config, now: float, limit: int) -> str:
    c = counts(snapshot, config)
    parts = [f"{sym}{n}" for sym, n in (("↑", c.push), ("↓", c.pull), ("✎", c.dirty)) if n]
    if snapshot.git_missing:
        state = "git not found"
    elif snapshot.all_fetches_failed:
        state = "offline"
    elif snapshot.fetch_mode is FetchMode.PAUSED:
        state = "paused"
    else:
        state = " ".join(parts) if parts else "all in sync"
    text = f"repotray: {state} · {fetched_text(snapshot, now).lower()}"
    if len(text) > limit:
        text = text[: max(0, limit - 1)] + "…"
    return text
