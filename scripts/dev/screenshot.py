#!/usr/bin/env python3
"""Screenshot the panel tray strip, a window rectangle or an explicit area, scaled for viewing.

    scripts/dev/screenshot.py tray  [-o out.png] [--width 1000] [--scale 3]
    scripts/dev/screenshot.py rect X Y W H [-o out.png] [--scale 1]
    scripts/dev/screenshot.py window TITLE [-o out.png]       (a toplevel of this X display)

The tray strip is computed from the primary monitor's geometry vs. its work area: the band the
panel occupies, right end. Works on X11 only (root window capture).
"""

from __future__ import annotations

import argparse
import subprocess
import sys

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf  # noqa: E402


def primary_monitor():
    display = Gdk.Display.get_default()
    mon = display.get_primary_monitor() or display.get_monitor(0)
    return mon.get_geometry(), mon.get_workarea()


def panel_strip(width: int) -> tuple[int, int, int, int]:
    geo, work = primary_monitor()
    right = geo.x + geo.width
    w = min(width, geo.width)
    if work.y + work.height < geo.y + geo.height:  # bottom panel
        y = work.y + work.height
        h = geo.y + geo.height - y
    elif work.y > geo.y:  # top panel
        y, h = geo.y, work.y - geo.y
    else:
        y, h = geo.y + geo.height - 40, 40
    return right - w, y, w, h


def find_window(title: str) -> tuple[int, int, int, int]:
    out = subprocess.run(["xwininfo", "-name", title], capture_output=True, text=True).stdout
    vals = {}
    for line in out.splitlines():
        k, _, v = line.strip().partition(":")
        vals[k] = v.strip()
    return (
        int(vals["Absolute upper-left X"]),
        int(vals["Absolute upper-left Y"]),
        int(vals["Width"]),
        int(vals["Height"]),
    )


def capture(x: int, y: int, w: int, h: int, scale: int, out: str) -> None:
    root = Gdk.get_default_root_window()
    pb = Gdk.pixbuf_get_from_window(root, x, y, w, h)
    if pb is None:
        sys.exit("capture failed (Wayland?)")
    if scale != 1:
        pb = pb.scale_simple(w * scale, h * scale, GdkPixbuf.InterpType.NEAREST)
    pb.savev(out, "png", [], [])
    print(f"{out}  ({x},{y} {w}x{h} ×{scale})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["tray", "rect", "window"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("-o", "--output", default="screenshot.png")
    ap.add_argument("--width", type=int, default=1000, help="tray strip width")
    ap.add_argument("--scale", type=int, default=None)
    a = ap.parse_args()
    if a.what == "tray":
        rect, scale = panel_strip(a.width), a.scale or 3
    elif a.what == "rect":
        rect, scale = tuple(int(v) for v in a.args[:4]), a.scale or 1
    else:
        rect, scale = find_window(" ".join(a.args)), a.scale or 1
    capture(*rect, scale, a.output)


if __name__ == "__main__":
    main()
