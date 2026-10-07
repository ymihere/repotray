"""Icons for the Qt front end: the tray icon from an IconSpec, and the panel's button icons.

Button icons are named like the GTK ones (``go-up-symbolic`` …, see core.model). On Windows they
are glyphs of the system icon font (Segoe Fluent Icons on Windows 11, Segoe MDL2 Assets on 10),
painted in the palette's text colour, so they follow dark/light like Windows' own UI. Elsewhere
the freedesktop icon theme is asked; ``TEXT`` is the last resort for a toolkit without either.
"""

from __future__ import annotations

from functools import cache

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import (
    QFont,
    QFontDatabase,
    QGuiApplication,
    QIcon,
    QIconEngine,
    QImage,
    QPainter,
    QPalette,
    QPixmap,
)

from repotray.core.indicator import IconSpec

SEGOE_FONTS = ("Segoe Fluent Icons", "Segoe MDL2 Assets")
SEGOE_GLYPHS = {
    "go-up-symbolic": "",
    "go-down-symbolic": "",
    "emblem-synchronizing-symbolic": "",
    "view-refresh-symbolic": "",
    "emblem-system-symbolic": "",
    "dialog-warning-symbolic": "",
    "document-edit-symbolic": "",
    "object-select-symbolic": "",
}
TEXT = {
    "go-up-symbolic": "↑",
    "go-down-symbolic": "↓",
    "emblem-synchronizing-symbolic": "⇅",
    "view-refresh-symbolic": "⟳",
    "emblem-system-symbolic": "⚙",
    "dialog-warning-symbolic": "⚠",
    "document-edit-symbolic": "✎",
    "object-select-symbolic": "✓",
}
TRAY_SIZES = (16, 20, 24, 32, 40, 48, 64)


@cache
def segoe_family() -> str | None:
    families = set(QFontDatabase.families())
    return next((f for f in SEGOE_FONTS if f in families), None)


class GlyphEngine(QIconEngine):
    """A font glyph drawn in the palette's text colour (greyed when disabled), at any size."""

    def __init__(self, family: str, char: str) -> None:
        super().__init__()
        self.family = family
        self.char = char

    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State) -> None:
        pal = QGuiApplication.palette()
        disabled = mode == QIcon.Mode.Disabled
        group = QPalette.ColorGroup.Disabled if disabled else QPalette.ColorGroup.Normal
        font = QFont(self.family)
        font.setPixelSize(max(1, min(rect.width(), rect.height())))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(font)
        painter.setPen(pal.color(group, QPalette.ColorRole.ButtonText))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.char)
        painter.restore()

    def scaledPixmap(  # noqa: N802 - Qt override
        self, size: QSize, mode: QIcon.Mode, state: QIcon.State, scale: float
    ) -> QPixmap:
        pm = QPixmap(QSize(round(size.width() * scale), round(size.height() * scale)))
        pm.setDevicePixelRatio(scale)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        self.paint(p, QRect(QPoint(0, 0), size), mode, state)
        p.end()
        return pm

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        return self.scaledPixmap(size, mode, state, 1.0)

    def clone(self) -> QIconEngine:
        return GlyphEngine(self.family, self.char)


def theme_icon(name: str) -> QIcon:
    """The icon for a model icon name; null if this system has none (use ``TEXT[name]``)."""
    family = segoe_family()
    if family is not None and name in SEGOE_GLYPHS:
        return QIcon(GlyphEngine(family, SEGOE_GLYPHS[name]))
    icon = QIcon.fromTheme(name)
    if icon.isNull():
        icon = QIcon.fromTheme(name.removesuffix("-symbolic"))
    return icon


def set_icon(button, name: str, text: str = "") -> None:
    """Give a button the named icon, or the icon's text stand-in when the system has none."""
    icon = theme_icon(name)
    if icon.isNull():
        button.setIcon(QIcon())
        button.setText(f"{TEXT.get(name, '')} {text}".strip())
    else:
        button.setIcon(icon)
        button.setText(text)


def tray_icon(spec: IconSpec, glyph_color: str) -> QIcon:
    """The tray icon, rendered at each size Windows may ask for (16 px at 100 % up to 64 px), so
    it is never scaled down from one large bitmap."""
    from repotray.icons.raster import render

    icon = QIcon()
    for px in TRAY_SIZES:
        img = render(spec, px, glyph_color=glyph_color).convert("RGBA")
        data = img.tobytes("raw", "RGBA")
        qimg = QImage(data, px, px, 4 * px, QImage.Format.Format_RGBA8888).copy()
        icon.addPixmap(QPixmap.fromImage(qimg))
    return icon
