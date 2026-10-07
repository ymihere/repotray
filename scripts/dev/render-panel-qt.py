"""Render the Qt panel from the demo snapshot to PNGs, light and dark (no tray icon needed).

    python scripts/dev/render-panel-qt.py OUT_DIR

Writes panel-qt-light.png, panel-qt-dark.png, panel-qt-error.png and commits-qt.png.
"""

from __future__ import annotations

import sys
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

from repotray.core.config import Config
from repotray.core.demo import demo_incoming, demo_snapshot
from repotray.core.model import control_menu, panel_model
from repotray.core.types import ActionKind, ActionResult
from repotray.ui.qt.app import application
from repotray.ui.qt.panel import Panel


class Ctl:
    config = Config()

    def dispatch(self, action, path=None):
        print("dispatch", action, path)

    def refresh(self):
        pass

    def panel_opened(self):
        pass

    def panel_closed(self):
        pass


def grab(panel: Panel, out: Path) -> None:
    panel.fit()
    panel.show()
    QGuiApplication.processEvents()
    panel.grab().save(str(out))
    panel.hide()


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    app = application()
    snap = demo_snapshot()
    now = time.time()
    for scheme in (Qt.ColorScheme.Light, Qt.ColorScheme.Dark):
        QGuiApplication.styleHints().setColorScheme(scheme)
        app.processEvents()
        panel = Panel(Ctl())
        panel.set_control_menu(control_menu(snap))
        panel.set_model(panel_model(snap, Config(), now))
        grab(panel, out / f"panel-qt-{scheme.name.lower()}.png")
    mobile = next(s for s in snap.repos if s.name == "mobile-app")
    failed = ActionResult(
        repo=mobile.path,
        name="mobile-app",
        action=ActionKind.PULL,
        ok=False,
        message="Not possible to fast-forward",
        started_at=now - 2,
        duration=1.0,
    )
    panel.set_model(panel_model(replace(snap, recent_results=(failed,)), Config(), now))
    grab(panel, out / "panel-qt-error.png")
    from repotray.ui.qt.dialogs import CommitsDialog

    website = next(s for s in snap.repos if s.name == "website")
    log = demo_incoming(website, now)
    title = f"website: {log.total} incoming commits"
    dlg = CommitsDialog(None, title, "origin/main → main", log, lambda: None)
    dlg.show()
    QGuiApplication.processEvents()
    dlg.grab().save(str(out / "commits-qt.png"))
    print("written to", out)


if __name__ == "__main__":
    main()
