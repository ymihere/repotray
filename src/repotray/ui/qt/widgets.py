"""Small widgets Qt lacks: a spinner, a wrapping flow layout and a label that elides."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QLayout, QSizePolicy, QWidget, QWidgetItem

SPIN_MS = 80
SPIN_STEP = 30  # degrees per frame


def spinner_pixmap(size: int, angle: int, scale: float = 1.0) -> QPixmap:
    """One frame of the busy indicator: a three-quarter arc in the palette's highlight colour."""
    pm = QPixmap(round(size * scale), round(size * scale))
    pm.setDevicePixelRatio(scale)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    width = max(1.5, size / 8)
    pen = QPen(QGuiApplication.palette().color(QPalette.ColorRole.Highlight), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    m = width
    p.drawArc(QRectF(m, m, size - 2 * m, size - 2 * m), -angle * 16, 270 * 16)
    p.end()
    return pm


def dim(widget: QWidget) -> QWidget:
    """Secondary text (Gtk's dim-label): the palette's placeholder colour."""
    pal = widget.palette()
    pal.setColor(QPalette.ColorRole.WindowText, pal.color(QPalette.ColorRole.PlaceholderText))
    widget.setPalette(pal)
    return widget


def bold(widget: QWidget) -> QWidget:
    f = widget.font()
    f.setBold(True)
    widget.setFont(f)
    return widget


class Spinner(QWidget):
    """Busy indicator; spins while visible and started."""

    def __init__(self, size: int = 16, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.px = size
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.setInterval(SPIN_MS)
        self.timer.timeout.connect(self._step)
        self.setFixedSize(size + 4, size + 4)

    def start(self) -> None:
        self.timer.start()

    def stop(self) -> None:
        self.timer.stop()

    def is_spinning(self) -> bool:
        return self.timer.isActive()

    def _step(self) -> None:
        self.angle = (self.angle + SPIN_STEP) % 360
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        p = QPainter(self)
        pm = spinner_pixmap(self.px, self.angle, self.devicePixelRatioF())
        p.drawPixmap(2, 2, pm)
        p.end()


class ElidedLabel(QLabel):
    """A one-line label that shortens its text with … when it does not fit."""

    def __init__(self, text: str = "", mode=Qt.TextElideMode.ElideRight, parent=None) -> None:
        super().__init__(parent)
        self.full = text
        self.mode = mode
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(1)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt override
        self.full = text
        super().setText(text)
        self._elide()

    def text_full(self) -> str:
        return self.full

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        shown = self.fontMetrics().elidedText(self.full, self.mode, max(1, self.width()))
        if shown != super().text():
            super().setText(shown)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(self.fontMetrics().horizontalAdvance(self.full), super().sizeHint().height())


class FlowLayout(QLayout):
    """Lays children out left to right and wraps to the next line (like Gtk.FlowBox)."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 0) -> None:
        super().__init__(parent)
        self.items: list = []
        self.gap = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802 - Qt override
        self.items.append(item)

    def add(self, widget: QWidget) -> None:
        self.addChildWidget(widget)
        self.addItem(QWidgetItem(widget))

    def count(self) -> int:
        return len(self.items)

    def itemAt(self, index: int):  # noqa: N802 - Qt override
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index: int):  # noqa: N802 - Qt override
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802 - Qt override
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt override
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt override
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 - Qt override
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 - Qt override
        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _layout(self, rect: QRect, apply: bool) -> int:
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = r.x(), r.y(), 0
        for item in self.items:
            hint = item.sizeHint()
            if x + hint.width() > r.right() + 1 and line_h > 0:
                x, y, line_h = r.x(), y + line_h + self.gap, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.gap
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()
