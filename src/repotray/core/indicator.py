"""Snapshot + config → what the tray icon shows: IconSpec and label."""

from __future__ import annotations

from dataclasses import dataclass

from repotray.core.config import Config, IndicatorConfig
from repotray.core.types import FetchMode, Snapshot

LABEL_SYMBOLS = {"push": "↑", "pull": "↓", "dirty": "✎"}


@dataclass(frozen=True, slots=True)
class Counts:
    push: int = 0
    pull: int = 0
    dirty: int = 0
    diverged: int = 0
    no_upstream: int = 0
    detached: int = 0
    fetch_failed: int = 0
    total: int = 0

    def get(self, trigger: str) -> int:
        return getattr(self, trigger)


def counts(snapshot: Snapshot, config: Config) -> Counts:
    c = dict.fromkeys(
        ("push", "pull", "dirty", "diverged", "no_upstream", "detached", "fetch_failed"), 0
    )
    for s in snapshot.repos:
        if s.pushable or (config.count_no_upstream_as_push and s.no_upstream and s.branch):
            c["push"] += 1
        c["pull"] += s.pullable
        c["dirty"] += s.dirty(config.count_untracked_as_dirty)
        c["diverged"] += s.diverged
        c["no_upstream"] += s.no_upstream
        c["detached"] += s.detached
        c["fetch_failed"] += s.fetch_error is not None
    return Counts(**c, total=len(snapshot.repos))


@dataclass(frozen=True, slots=True)
class IconSpec:
    """Tray icon state. Colours are symbolic class names or ``#rrggbb``."""

    state: str = "clean"  # clean | attention | error | paused
    top: str | None = None
    bottom: str | None = None
    tint: str | None = None
    glyph_color: str = "#e1e1e1"
    marker: str = "arrow"  # corner marker shape: arrow (▲/▼) or dot

    @property
    def hex_mode(self) -> bool:
        return any(c and c.startswith("#") for c in (self.top, self.bottom, self.tint))


def _triggered(triggers: tuple[str, ...], c: Counts) -> bool:
    return any(c.get(t) > 0 for t in triggers)


def icon_spec(snapshot: Snapshot, config: Config) -> IconSpec:
    ind: IndicatorConfig = config.indicator
    if snapshot.git_missing or snapshot.all_fetches_failed:
        return IconSpec(state="error", glyph_color=ind.glyph_color, marker=ind.marker)
    if snapshot.fetch_mode is FetchMode.PAUSED:
        return IconSpec(state="paused", glyph_color=ind.glyph_color, marker=ind.marker)
    c = counts(snapshot, config)
    top = ind.top_dot_color if _triggered(ind.top_dot, c) else None
    bottom = ind.bottom_dot_color if _triggered(ind.bottom_dot, c) else None
    tint = ind.tint_color if _triggered(ind.tint, c) else None
    if top or bottom or tint:
        return IconSpec("attention", top, bottom, tint, ind.glyph_color, ind.marker)
    return IconSpec(state="clean", glyph_color=ind.glyph_color, marker=ind.marker)


def label_text(snapshot: Snapshot, config: Config) -> str:
    c = counts(snapshot, config)
    parts = [f"{LABEL_SYMBOLS[p]}{c.get(p)}" for p in config.indicator.label if c.get(p) > 0]
    return " ".join(parts)
