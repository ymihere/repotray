#!/usr/bin/env python3
"""Render the panel offscreen from the demo snapshot to a PNG (works with a locked screen too).

    scripts/dev/render-panel.py [-o panel.png] [--theme dark|light] [--state STATE] [--scale 2]

STATE: normal (default) · busy (a push and a sync running) · error (failed pull banner) ·
success (success banner) · empty (nothing to push or pull) · paused · fetching · offline ·
syncall (Sync all in progress)
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf, Gtk  # noqa: E402

from repotray.core.config import Config  # noqa: E402
from repotray.core.demo import PULL_FAILURE, demo_snapshot  # noqa: E402
from repotray.core.model import control_menu, panel_model  # noqa: E402
from repotray.core.types import ActionKind, ActionResult, FetchMode  # noqa: E402
from repotray.ui.gtk3 import theme  # noqa: E402
from repotray.ui.gtk3.panel import PanelView  # noqa: E402


def snapshot_for(state: str, now: float):
    s = demo_snapshot(now)
    by = {r.name: r for r in s.repos}
    if state == "busy":
        s = replace(
            s,
            running={by["infra"].path: ActionKind.PUSH, by["design-system"].path: ActionKind.SYNC},
        )
    elif state == "error":
        r = ActionResult(
            by["mobile-app"].path, ActionKind.PULL, False,
            "Not possible to fast-forward, aborting.", stderr=PULL_FAILURE,
            started_at=now - 3, duration=1.5, name="mobile-app",
        )  # fmt: skip
        s = replace(s, recent_results=(r,))
    elif state == "success":
        r = ActionResult(
            by["infra"].path, ActionKind.PUSH, True, "Pushed 1 commit to origin/main",
            started_at=now - 2, duration=1.5, name="infra",
        )  # fmt: skip
        repos = tuple(replace(x, ahead=0) if x.name == "infra" else x for x in s.repos)
        s = replace(s, repos=repos, recent_results=(r,))
    elif state == "empty":
        s = replace(s, repos=tuple(replace(x, ahead=0, behind=0) for x in s.repos))
    elif state == "paused":
        s = replace(s, fetch_mode=FetchMode.PAUSED)
    elif state == "fetching":
        s = replace(s, fetch_mode=FetchMode.FETCHING)
    elif state == "offline":
        s = replace(
            s, all_fetches_failed=True, fetch_mode=FetchMode.BACKOFF, next_fetch_at=now + 480
        )
    elif state == "syncall":
        s = replace(s, bulk=(ActionKind.SYNC, 2, 5), running={by["website"].path: ActionKind.PULL})
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="panel.png")
    ap.add_argument("--theme", choices=["dark", "light"], default="dark")
    ap.add_argument("--state", default="normal")
    ap.add_argument("--scale", type=int, default=1)
    ap.add_argument("--expand", action="store_true", help="expand the In sync group")
    a = ap.parse_args()

    theme.apply(a.theme, None)
    now = time.time()
    snap = snapshot_for(a.state, now)
    win = Gtk.OffscreenWindow()
    frame = Gtk.EventBox()
    frame.get_style_context().add_class("repotray-panel")
    frame.get_style_context().add_class("background")
    view = PanelView(lambda *_: None)
    view.expanded = a.expand
    view.set_control_menu(control_menu(snap))
    view.set_model(panel_model(snap, Config(), now))
    frame.add(view)
    win.add(frame)
    frame.show()
    win.show()
    for _ in range(50):
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.01)
    pb = win.get_pixbuf()
    if a.scale != 1:
        pb = pb.scale_simple(
            pb.get_width() * a.scale, pb.get_height() * a.scale, GdkPixbuf.InterpType.BILINEAR
        )
    pb.savev(a.output, "png", [], [])
    print(f"{a.output} {pb.get_width()}x{pb.get_height()}")
    assert Gdk  # keep import for gi version pinning


if __name__ == "__main__":
    main()
