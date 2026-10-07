"""The QApplication and the panel's dark/light choice."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication


def application() -> QApplication:
    """The process's QApplication (created on first use). Closing windows never quits it."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([sys.argv[0] if sys.argv and sys.argv[0] else "repotray"])
    app.setApplicationName("repotray")
    app.setQuitOnLastWindowClosed(False)
    return app


def apply_theme(panel_theme: str, prefers_dark: bool | None) -> None:
    """``auto``: follow the taskbar's dark/light setting, like Windows' own tray flyouts;
    ``dark``/``light`` force it; ``system`` leaves Qt on the OS app setting."""
    if panel_theme == "dark":
        scheme = Qt.ColorScheme.Dark
    elif panel_theme == "light":
        scheme = Qt.ColorScheme.Light
    elif panel_theme == "auto" and prefers_dark is not None:
        scheme = Qt.ColorScheme.Dark if prefers_dark else Qt.ColorScheme.Light
    else:
        return
    QGuiApplication.styleHints().setColorScheme(scheme)


def is_dark() -> bool:
    """Whether the current palette is dark (window background darker than its text)."""
    pal = QGuiApplication.palette()
    return pal.window().color().lightness() < pal.windowText().color().lightness()
