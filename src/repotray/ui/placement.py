"""Pure geometry for anchoring the panel to the tray icon. No toolkit imports."""

from __future__ import annotations

from dataclasses import dataclass

ICON_HALF = 12  # the anchor is the applet's leading edge; centre on the (24 px) icon
GAP = 0


@dataclass(frozen=True, slots=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def contains(self, x: int, y: int) -> bool:
        return self.x <= x < self.right and self.y <= y < self.bottom


@dataclass(frozen=True, slots=True)
class Anchor:
    """Where the click happened. ``side`` is the panel edge: top, bottom, left, right or None
    (no panel information: open at the pointer)."""

    x: int
    y: int
    side: str | None = None


SIDES = {0: "left", 1: "right", 2: "top", 3: "bottom"}  # Gtk.PositionType


def side_from_position(pos: int) -> str | None:
    return SIDES.get(pos)


def anchor_from_icon(area: Rect, monitor: Rect) -> Anchor:
    """Anchor for a tray icon at ``area`` on ``monitor`` (its full geometry), for hosts that give
    the icon rectangle but not the panel side (Gtk.StatusIcon, Qt's QSystemTrayIcon): an icon in
    the lower half sits in a bottom bar; a short one near the top in a top, left or right bar."""
    cx = area.x + area.w // 2 - ICON_HALF
    cy = area.y + area.h // 2 - ICON_HALF
    if area.y > monitor.y + monitor.h // 2:
        return Anchor(cx, area.y, "bottom")
    if area.bottom < monitor.y + monitor.h // 2 and area.h < monitor.h // 4:
        if area.x < monitor.x + monitor.w // 8:
            return Anchor(area.right, cy, "left")
        if area.x > monitor.x + monitor.w * 7 // 8:
            return Anchor(area.x, cy, "right")
        return Anchor(cx, area.bottom, "top")
    return Anchor(cx, area.y, None)


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(v, hi)) if hi >= lo else lo


def place(anchor: Anchor | None, size: tuple[int, int], workarea: Rect) -> tuple[int, int]:
    """Top-left position for a window of ``size`` anchored to ``anchor`` inside ``workarea``."""
    w, h = size
    if anchor is None:
        x, y = workarea.right - w, workarea.bottom - h
    elif anchor.side == "bottom":
        x = anchor.x + ICON_HALF - w // 2
        y = workarea.bottom - h - GAP
    elif anchor.side == "top":
        x = anchor.x + ICON_HALF - w // 2
        y = workarea.y + GAP
    elif anchor.side == "left":
        x = workarea.x + GAP
        y = anchor.y + ICON_HALF - h // 2
    elif anchor.side == "right":
        x = workarea.right - w - GAP
        y = anchor.y + ICON_HALF - h // 2
    else:  # at the pointer: above it if it fits, else below
        x = anchor.x - w // 2
        y = anchor.y - h - 4
        if y < workarea.y:
            y = anchor.y + 4
    x = _clamp(x, workarea.x, workarea.right - w)
    y = _clamp(y, workarea.y, workarea.bottom - h)
    return x, y


def monitor_for(anchor: Anchor | None, monitors: list[tuple[Rect, Rect]]) -> Rect:
    """Work area of the monitor containing the anchor (or nearest to it); monitors are
    (geometry, workarea) pairs, the first being the fallback."""
    if not monitors:
        raise ValueError("no monitors")
    if anchor is None:
        return monitors[0][1]
    for geo, work in monitors:
        if geo.contains(anchor.x, anchor.y):
            return work

    def dist(geo: Rect) -> int:
        dx = max(geo.x - anchor.x, 0, anchor.x - geo.right + 1)
        dy = max(geo.y - anchor.y, 0, anchor.y - geo.bottom + 1)
        return dx * dx + dy * dy

    return min(monitors, key=lambda m: dist(m[0]))[1]
