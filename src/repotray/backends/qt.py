"""Windows (and, untested, macOS) via Qt 6 / PySide6: tray icon plus the full panel.

``QSystemTrayIcon`` reports left, middle and right clicks and where the icon is, so this backend
has what pystray lacks: left click toggles the panel anchored above the icon, middle click
fetches, right click shows the control menu. Callbacks from worker threads reach the Qt thread
through a queued signal.
"""

from __future__ import annotations

import logging
import signal
import sys
from collections.abc import Callable
from typing import ClassVar

from repotray.backends.base import ProbeResult, caps

log = logging.getLogger(__name__)

WAKE_MS = 200  # how often Python gets to run its signal handlers inside Qt's loop


class QtBackend:
    name: ClassVar[str] = "qt"
    caps = caps(
        tooltip=True,
        tooltip_max_chars=127 if sys.platform == "win32" else None,
        panel=True,
        two_menus=True,
        notifications=True,
        anchor=True,
    )
    has_panel = True

    @classmethod
    def probe(cls, platform) -> ProbeResult:
        from PySide6 import QtCore  # noqa: F401 - raises if PySide6 is missing

        name = getattr(platform, "name", "")
        if name == "windows":
            return ProbeResult(70, "Qt tray icon with the panel")
        if name == "macos":
            return ProbeResult(40, "Qt available (untested on macOS; select with --backend qt)")
        return ProbeResult(5, "Qt available; native Linux backends are preferred")

    def __init__(self, platform, controller) -> None:
        import threading

        from PySide6.QtCore import QObject, Qt, Signal
        from PySide6.QtWidgets import QSystemTrayIcon

        from repotray.icons.raster import bar_glyph_color
        from repotray.ui.qt.app import application, apply_theme
        from repotray.ui.qt.menus import build_menu
        from repotray.ui.qt.panel import Panel

        self.platform = platform
        self.controller = controller
        self.app = application()
        cfg = controller.config
        try:
            dark = platform.prefers_dark_panel() if cfg.panel_theme == "auto" else None
        except Exception:  # noqa: BLE001
            log.warning("reading the taskbar theme failed", exc_info=True)
            dark = None
        apply_theme(cfg.panel_theme, dark)

        class Invoker(QObject):
            call = Signal(object)

        self._invoker = Invoker()
        # Queued even from the Qt thread itself: call_soon never runs ``fn`` re-entrantly.
        self._invoker.call.connect(self._run_callback, Qt.ConnectionType.QueuedConnection)
        self.ui_thread = threading.current_thread()  # the thread that owns the QApplication
        self.panel = Panel(controller)
        self.glyph_color = bar_glyph_color(platform)
        self.dialog = None
        self._spec = None
        self._tooltip = None
        self._control_items: list | None = None
        self.menu = build_menu((), self.dispatch)
        self.icon = QSystemTrayIcon()
        self.icon.setToolTip("repotray")
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._on_activated)
        self.caps = dict(type(self).caps)
        self.caps["notifications"] = QSystemTrayIcon.supportsMessages()
        self._wake = None

    # --- TrayBackend -------------------------------------------------------------------------

    def set_icon(self, spec) -> None:
        from repotray.ui.qt.icons import tray_icon

        if spec != self._spec:
            self._spec = spec
            self.icon.setIcon(tray_icon(spec, self.glyph_color))
            if not self.icon.isVisible():
                self.icon.show()

    def set_label(self, text: str) -> None:
        pass  # Windows tray icons have no label; counts are in the tooltip and the panel

    def set_tooltip(self, text: str) -> None:
        if text != self._tooltip:
            self._tooltip = text
            self.icon.setToolTip(text)

    def set_menus(self, control, fallback) -> None:
        from repotray.ui.qt.menus import fill_menu

        self.panel.set_control_menu(control)
        if list(control) != self._control_items:
            self._control_items = list(control)
            fill_menu(self.menu, control, self.dispatch)

    def show_panel_model(self, model) -> None:
        self.panel.set_model(model)

    def open_panel(self) -> None:
        self.panel.toggle(self.anchor())

    def notify(self, title: str, body: str) -> None:
        from PySide6.QtWidgets import QSystemTrayIcon

        if self.caps["notifications"] and self.icon.isVisible():
            self.icon.showMessage(title, body, QSystemTrayIcon.MessageIcon.NoIcon, 8000)
            return
        if not self.platform.notify(title, body):
            log.info("notification (not shown): %s — %s", title, body)

    def copy_to_clipboard(self, text: str) -> None:
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.clipboard().setText(text)

    def show_commits(
        self, title: str, subtitle: str, log, on_open_editor, action=None, on_action=None
    ) -> None:
        from repotray.ui.qt.dialogs import CommitsDialog

        def make(parent):
            dlg = CommitsDialog(parent, title, subtitle, log, on_open_editor, action, on_action)
            self.dialog = dlg  # the open commits dialog, for tests; None once it is closed
            dlg.destroyed.connect(lambda *_: setattr(self, "dialog", None))
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            return dlg

        self.panel.track_dialog(make)

    def show_about(self, info: dict) -> None:
        import html

        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QMessageBox

        e = {k: html.escape(v) for k, v in info.items()}
        text = (
            f"<b>{e['name']} {e['version']}</b><p>{e['comments']}</p>"
            f"<p><a href='{e['website']}'>{e['website']}</a></p>"
            f"<p>{e['copyright']} · {e['license']} licence</p><p><small>{e['credits']}</small></p>"
        )

        def make(parent):
            box = QMessageBox(parent)
            box.setWindowTitle(f"About {info['name']}")
            box.setTextFormat(Qt.TextFormat.RichText)
            box.setText(text)
            box.setIconPixmap(self.icon.icon().pixmap(48, 48))
            box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
            box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            box.show()
            return box

        self.panel.track_dialog(make)

    def dispatch(self, action: str, path) -> None:
        self.controller.dispatch(action, path)

    # --- clicks ------------------------------------------------------------------------------

    def anchor(self):
        """Where to open the panel: above (or beside) the icon, from its screen rectangle."""
        from PySide6.QtGui import QGuiApplication

        from repotray.ui.placement import Rect, anchor_from_icon

        r = self.icon.geometry()
        if r.isEmpty():
            return None  # unknown (some hosts): the panel opens at the pointer
        screen = QGuiApplication.screenAt(r.center()) or QGuiApplication.primaryScreen()
        g = screen.geometry()
        return anchor_from_icon(
            Rect(r.x(), r.y(), r.width(), r.height()), Rect(g.x(), g.y(), g.width(), g.height())
        )

    def _on_activated(self, reason) -> None:
        from PySide6.QtWidgets import QSystemTrayIcon

        R = QSystemTrayIcon.ActivationReason  # noqa: N806
        if reason == R.Trigger:
            self.panel.toggle(self.anchor())
        elif reason == R.MiddleClick:
            self.controller.fetch_all()
        # R.Context shows the control menu (set as the context menu); a double click arrives as
        # two Triggers on Windows, which open and close the panel.

    # --- loop --------------------------------------------------------------------------------

    def _run_callback(self, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception:  # noqa: BLE001
            log.exception("UI callback failed")

    def call_soon(self, fn: Callable[[], None]) -> None:
        self._invoker.call.emit(fn)  # queued to the Qt thread when emitted from another thread

    def install_signal_handlers(self, on_quit: Callable[[], None]) -> None:
        from PySide6.QtCore import QTimer

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: self.call_soon(on_quit))
        # Qt's loop does not return to Python on its own; wake it so handlers run (Ctrl+C).
        self._wake = QTimer()
        self._wake.timeout.connect(lambda: None)
        self._wake.start(WAKE_MS)

    def run(self) -> None:
        self.icon.show()
        self.app.exec()

    def quit(self) -> None:
        self.call_soon(self._quit)

    def _quit(self) -> None:
        self.panel.hide()
        self.icon.hide()
        self.app.quit()
