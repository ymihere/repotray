"""The panel in Qt: a frameless popup above the tray icon (SPEC §2.5), laid out like the GTK one.

``PanelView`` lays out a PanelModel and rebuilds only the sections whose part of the model
changed; ``Panel`` is the window around it with the show/hide behaviour.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from repotray.core.model import (
    ACTION_ICONS,
    ICON_DIRTY,
    ICON_GEAR,
    ICON_WARNING,
    BulkButton,
    Button,
    Cell,
    PanelModel,
    Row,
)
from repotray.core.types import ActionKind
from repotray.ui.placement import Anchor, Rect, monitor_for, place
from repotray.ui.qt import winapi
from repotray.ui.qt.app import is_dark
from repotray.ui.qt.icons import TEXT, set_icon, theme_icon
from repotray.ui.qt.menus import build_menu, fill_menu, literal
from repotray.ui.qt.widgets import (
    SPIN_MS,
    SPIN_STEP,
    ElidedLabel,
    FlowLayout,
    Spinner,
    bold,
    dim,
    spinner_pixmap,
)

log = logging.getLogger(__name__)

WIDTH = 480
MAX_ROWS = 12
NAME_CHARS = 24
REOPEN_GUARD = 0.3
TICK_MS = 2000
FOCUS_CHECK_MS = 60
ICON_PX = 16
GUTTER = 28  # width of the sync column when a row has no Sync button
LAYOUT_DEPTH = 8  # nesting levels of layouts in the panel, with room to spare
# Windows 11 InfoBar colours (WinUI "critical" and "success"): Windows has no theme colour for
# errors, so these are fixed, in a light and a dark variant.
BANNER_COLORS = {
    ("error", False): ("#fde7e9", "#c42b1c"),
    ("error", True): ("#442726", "#ff99a4"),
    ("success", False): ("#dff6dd", "#0f7b0f"),
    ("success", True): ("#393d1b", "#6ccb5f"),
}


def _flat_button(icon: str, tooltip: str, on_click: Callable[[], None]) -> QToolButton:
    b = QToolButton()
    b.setAutoRaise(True)
    set_icon(b, icon)
    b.setToolTip(tooltip)
    b.clicked.connect(lambda _checked=False: on_click())
    return b


def _icon_label(name: str, tooltip: str) -> QLabel:
    lbl = QLabel()
    icon = theme_icon(name)
    if icon.isNull():
        lbl.setText(TEXT.get(name, ""))
    else:
        lbl.setPixmap(icon.pixmap(ICON_PX, ICON_PX))
    lbl.setToolTip(tooltip)
    return lbl


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.hide()
            w.deleteLater()
        elif item.layout() is not None:
            _clear(item.layout())


class BulkWidget(QPushButton):
    """A Push all / Sync all / Pull all button: icon (spinning while busy) and label."""

    def __init__(self, kind: ActionKind, action: str, dispatch) -> None:
        super().__init__()
        self.kind = kind
        self.label = ""
        self.busy = False
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.setInterval(SPIN_MS)
        self.timer.timeout.connect(self._spin)
        set_icon(self, ACTION_ICONS[kind])
        self.clicked.connect(lambda _checked=False: dispatch(action, None))

    def label_text(self) -> str:
        """The model's label ("Push all", "Pushing 1/3…"), without an icon's text stand-in."""
        return self.label

    def set_model(self, b: BulkButton) -> None:
        self.label = b.label
        set_icon(self, ACTION_ICONS[self.kind], literal(b.label))
        self.setEnabled(b.enabled)
        self.setToolTip(b.tooltip)
        self.busy = b.busy
        if b.busy:
            self.timer.start()
            self._spin()
        else:
            self.timer.stop()

    def _spin(self) -> None:
        self.angle = (self.angle + SPIN_STEP) % 360
        self.setIcon(QIcon(spinner_pixmap(ICON_PX, self.angle, self.devicePixelRatioF())))


class NameButton(QToolButton):
    """A repo name: flat, shortened in the middle when long; opens the repo menu when clicked."""

    def __init__(self, name: str, tooltip: str) -> None:
        super().__init__()
        self.full_name = name
        self.setAutoRaise(True)
        fm = self.fontMetrics()
        shown = fm.elidedText(
            name, Qt.TextElideMode.ElideMiddle, fm.averageCharWidth() * NAME_CHARS
        )
        self.setText(literal(shown))
        self.setToolTip(tooltip)


class PanelView(QWidget):
    """Everything inside the panel window. Usable without showing it, for tests and screenshots."""

    def __init__(self, dispatch: Callable[[str, object], None]) -> None:
        super().__init__()
        self.dispatch = dispatch
        self.on_details: Callable[[object], None] | None = None
        self.model: PanelModel | None = None
        self.control_items: tuple = ()
        self.expanded = False
        self.open_menu = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        # Header
        header = QHBoxLayout()
        header.setSpacing(8)
        self.summary = bold(ElidedLabel(""))
        self.resume = QLabel('<a href="resume">Resume</a>')
        self.resume.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.resume.linkActivated.connect(lambda _href: self.dispatch("toggle_pause", None))
        self.resume.hide()
        self.fetched = dim(QLabel(""))
        self.refresh_btn = _flat_button(
            ACTION_ICONS[ActionKind.FETCH],
            "Fetch all now",
            lambda: self.dispatch("fetch_all", None),
        )
        self.header_spinner = Spinner(ICON_PX)
        self.header_spinner.hide()
        self.gear = QToolButton()
        self.gear.setAutoRaise(True)
        set_icon(self.gear, ICON_GEAR)
        self.gear.setToolTip("Settings and more")
        self.gear.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.gear.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
        self.gear_menu = build_menu((), self.dispatch, self)
        self.gear.setMenu(self.gear_menu)
        header.addWidget(self.summary, 1)
        for w in (self.resume, self.fetched, self.refresh_btn, self.header_spinner, self.gear):
            header.addWidget(w)
        lay.addLayout(header)

        self.warning = dim(QLabel(""))
        self.warning.setWordWrap(True)
        self.warning.setTextFormat(Qt.TextFormat.PlainText)
        self.warning.hide()
        lay.addWidget(self.warning)

        # Banner
        self.banner = QFrame()
        self.banner.setObjectName("banner")
        self.banner_kind = ""
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(10, 6, 6, 6)
        self.banner_label = QLabel("")
        self.banner_label.setWordWrap(True)
        self.banner_label.setTextFormat(Qt.TextFormat.PlainText)
        self.details_btn = QPushButton("Details…")
        self.details_btn.clicked.connect(self._on_details)
        bl.addWidget(self.banner_label, 1)
        bl.addWidget(self.details_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.banner.hide()
        lay.addWidget(self.banner)

        # Push all · Sync all · Pull all, above the columns they act on
        bar = QGridLayout()
        bar.setContentsMargins(0, 2, 0, 2)
        self.push_all = BulkWidget(ActionKind.PUSH, "push_all", self.dispatch)
        self.sync_all = BulkWidget(ActionKind.SYNC, "sync_all", self.dispatch)
        self.pull_all = BulkWidget(ActionKind.PULL, "pull_all", self.dispatch)
        self.sync_all.setDefault(True)  # the primary button
        bar.addWidget(self.push_all, 0, 0, Qt.AlignmentFlag.AlignLeft)
        bar.addWidget(self.sync_all, 0, 1, Qt.AlignmentFlag.AlignHCenter)
        bar.addWidget(self.pull_all, 0, 2, Qt.AlignmentFlag.AlignRight)
        for col in range(3):
            bar.setColumnStretch(col, 1)
        lay.addLayout(bar)
        lay.addWidget(self._separator())

        # Columns
        titles = QHBoxLayout()
        self.left_title = bold(QLabel(""))
        self.right_title = bold(QLabel(""))
        titles.addWidget(self.left_title)
        titles.addStretch(1)
        titles.addWidget(self.right_title)
        self.titles = QWidget()
        self.titles.setLayout(titles)
        titles.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.titles)

        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(6)
        self.grid.setVerticalSpacing(2)
        self.scroller = QScrollArea()
        self.scroller.setWidget(self.grid_host)
        self.scroller.setWidgetResizable(True)
        self.scroller.setFrameShape(QFrame.Shape.NoFrame)
        self.scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay.addWidget(self.scroller)

        self.empty = dim(QLabel(""))
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setContentsMargins(0, 6, 0, 6)
        lay.addWidget(self.empty)

        self.sep2 = self._separator()
        lay.addWidget(self.sep2)
        self.groups = QVBoxLayout()
        self.groups.setSpacing(2)
        lay.addLayout(self.groups)
        self.setFixedWidth(WIDTH)

    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    # --- helpers -----------------------------------------------------------------------------

    def popup_repo_menu(self, widget: QWidget, items) -> None:
        if self.open_menu is not None:
            self.open_menu.close()
        menu = build_menu(items, self.dispatch, self)
        menu.aboutToHide.connect(menu.deleteLater)
        self.open_menu = menu
        menu.destroyed.connect(lambda *_: setattr(self, "open_menu", None))
        menu.popup(widget.mapToGlobal(QPoint(0, widget.height())))

    def _name_button(self, name: str, tooltip: str, menu) -> NameButton:
        b = NameButton(name, tooltip)
        b.clicked.connect(lambda _checked=False: self.popup_repo_menu(b, menu))
        return b

    def _action_button(self, btn: Button, path) -> QWidget:
        if btn.busy:
            sp = Spinner(ICON_PX)
            sp.setToolTip(btn.tooltip)
            sp.start()
            return sp
        b = _flat_button(
            ACTION_ICONS[btn.action],
            btn.tooltip,
            lambda: self.dispatch(btn.action.value, path),
        )
        b.setEnabled(btn.enabled)  # Qt keeps showing tooltips on disabled widgets
        return b

    def _markers(self, cell: Cell, right: bool) -> QWidget:
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        parts: list[QWidget] = [QLabel(cell.count_text)]
        if cell.dirty:
            parts.append(_icon_label(ICON_DIRTY, "Uncommitted changes (push sends commits only)"))
        if cell.warning:
            parts.append(_icon_label(ICON_WARNING, cell.warning))
        if right:
            parts.reverse()
        for p in parts:
            lay.addWidget(p)
        return box

    # --- model -------------------------------------------------------------------------------

    def set_control_menu(self, items: tuple) -> None:
        if items == self.control_items:
            return
        self.control_items = items
        fill_menu(self.gear_menu, items, self.dispatch)

    def set_model(self, m: PanelModel) -> None:
        old = self.model
        self.model = m
        if old is None or old.header != m.header:
            self._set_header(m)
        if old is None or old.banner != m.banner:
            self._set_banner(m)
        if old is None or old.rows != m.rows or old.columns_title != m.columns_title:
            self._set_rows(m)
        if old is None or old.groups != m.groups:
            self._set_groups(m)
        if old is None or old.bulk != m.bulk:
            self.push_all.set_model(m.bulk.push)
            self.sync_all.set_model(m.bulk.sync)
            self.pull_all.set_model(m.bulk.pull)

    def _set_header(self, m: PanelModel) -> None:
        h = m.header
        self.summary.setText(h.summary)
        self.summary.setToolTip(h.summary)
        self.fetched.setText(h.fetched_text)
        self.resume.setVisible(h.paused)
        self.refresh_btn.setVisible(not h.fetching)
        self.header_spinner.setVisible(h.fetching)
        (self.header_spinner.start if h.fetching else self.header_spinner.stop)()
        self.warning.setText(h.warning or "")
        self.warning.setVisible(bool(h.warning))

    def _set_banner(self, m: PanelModel) -> None:
        b = m.banner
        if b is None:
            self.banner.hide()
            self.banner_kind = ""
            return
        self.banner_kind = b.kind
        bg, fg = BANNER_COLORS[(b.kind if b.kind == "error" else "success", is_dark())]
        self.banner.setStyleSheet(
            f"QFrame#banner {{ background: {bg}; border-radius: 4px; }}"
            f"QFrame#banner > QLabel {{ color: {fg}; }}"
        )
        if b.kind == "error":
            self.banner_label.setText(f"⚠ {b.text}")
            self.details_btn.show()
        else:
            self.banner_label.setText(f"{b.text} ✓")
            self.details_btn.setVisible(b.result is not None and b.result.name == "Sync all")
        self.banner.show()

    def _on_details(self) -> None:
        banner = self.model.banner if self.model else None
        if banner and banner.result and self.on_details:
            self.on_details(banner.result)

    def _set_rows(self, m: PanelModel) -> None:
        self.left_title.setText(m.columns_title[0])
        self.right_title.setText(m.columns_title[1])
        _clear(self.grid)
        has_rows = bool(m.rows)
        self.titles.setVisible(has_rows)
        self.scroller.setVisible(has_rows)
        self.empty.setText(m.empty_text or "")
        self.empty.setVisible(not has_rows)
        for i, row in enumerate(m.rows):
            self._add_row(i, row)
        for col in range(7):
            self.grid.setColumnStretch(col, 1 if col in (0, 6) else 0)
        # Cap the visible height at MAX_ROWS rows; scroll beyond.
        self.grid.activate()
        nat = self.grid_host.sizeHint().height()
        row_h = max(24, nat // max(1, len(m.rows)))
        self.scroller.setFixedHeight(min(nat, row_h * MAX_ROWS))

    def _add_row(self, i: int, row: Row) -> None:
        g = self.grid
        left, right = Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignRight
        # columns: name | markers | push | sync | pull | markers | name
        if row.left:
            c = row.left
            g.addWidget(self._name_button(c.name, c.tooltip, c.menu), i, 0, left)
            g.addWidget(self._markers(c, right=False), i, 1, left)
            g.addWidget(self._action_button(c.button, c.path), i, 2)
        if row.sync:
            g.addWidget(self._action_button(row.sync, row.sync_path), i, 3)
        else:
            spacer = QWidget()
            spacer.setFixedWidth(GUTTER)
            g.addWidget(spacer, i, 3)
        if row.right:
            c = row.right
            g.addWidget(self._action_button(c.button, c.path), i, 4)
            g.addWidget(self._markers(c, right=True), i, 5, right)
            g.addWidget(self._name_button(c.name, c.tooltip, c.menu), i, 6, right)

    def cell(self, col: int, row: int) -> QWidget | None:
        """The widget in grid column ``col`` of row ``row`` (tests use the GTK numbering)."""
        item = self.grid.itemAtPosition(row, col)
        return item.widget() if item is not None else None

    def _set_groups(self, m: PanelModel) -> None:
        _clear(self.groups)
        self.sep2.setVisible(bool(m.groups))
        for g in m.groups:
            flow_host = QWidget()
            flow = FlowLayout(flow_host)
            for chip in g.chips:
                b = NameButton(chip.name, chip.tooltip)
                b.clicked.connect(
                    lambda _checked=False, w=b, items=chip.menu: self.popup_repo_menu(w, items)
                )
                flow.add(b)
            if g.collapsed:
                exp = QToolButton()
                exp.setText(literal(g.title))
                exp.setCheckable(True)
                exp.setChecked(self.expanded)
                exp.setAutoRaise(True)
                exp.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                exp.setArrowType(
                    Qt.ArrowType.DownArrow if self.expanded else Qt.ArrowType.RightArrow
                )
                flow_host.setVisible(self.expanded)
                exp.toggled.connect(lambda on, e=exp, f=flow_host: self._on_expanded(e, f, on))
                self.groups.addWidget(exp)
                self.groups.addWidget(flow_host)
                continue
            line = QHBoxLayout()
            line.setSpacing(6)
            title = QHBoxLayout()
            title.setSpacing(4)
            if g.icon_name:
                title.addWidget(_icon_label(g.icon_name, ""))
            title.addWidget(bold(QLabel(g.title)))
            title_host = QWidget()
            title_host.setLayout(title)
            title.setContentsMargins(0, 5, 0, 0)
            line.addWidget(title_host, 0, Qt.AlignmentFlag.AlignTop)
            line.addWidget(flow_host, 1)
            self.groups.addLayout(line)
        self.updateGeometry()

    def _on_expanded(self, button: QToolButton, flow_host: QWidget, on: bool) -> None:
        self.expanded = on
        button.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        flow_host.setVisible(on)
        fit = getattr(self.window(), "fit", None)
        if fit is not None:
            fit()


class Panel(QWidget):
    """The popup window. Toggled by a tray click; hidden on Escape, focus loss or a second click."""

    def __init__(self, controller) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.controller = controller
        self.setWindowTitle("repotray")
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
        self.dialog_open = False
        self.was_active = False  # got focus since it was last shown
        self.anchor: Anchor | None = None
        self.last_focus_hide = 0.0
        self._rounded = False
        self.frame = QFrame(self)
        self.frame.setObjectName("panelFrame")
        self.frame.setStyleSheet(
            "QFrame#panelFrame { border: 1px solid palette(mid); background: palette(window); }"
        )
        self.view = PanelView(self._dispatch)
        self.view.on_details = self.show_details
        inner = QVBoxLayout(self.frame)
        inner.setContentsMargins(1, 1, 1, 1)
        inner.addWidget(self.view)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.frame)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.tick = QTimer(self)
        self.tick.setInterval(TICK_MS)
        self.tick.timeout.connect(self.controller.refresh)

    def _dispatch(self, action: str, path) -> None:
        self.controller.dispatch(action, path)

    # --- model -------------------------------------------------------------------------------

    def set_model(self, model: PanelModel) -> None:
        self.view.set_model(model)
        if self.isVisible():
            self.fit()

    def fit(self) -> None:
        """Resize to the content (rows come and go) and re-anchor. Qt recomputes nested layouts
        lazily, one LayoutRequest per level, so deliver those first or adjustSize() would use
        stale sizes and squeeze the content."""
        for _ in range(LAYOUT_DEPTH):
            QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
        self.adjustSize()
        if self.isVisible():
            self._place()

    def set_control_menu(self, items) -> None:
        self.view.set_control_menu(tuple(items))

    # --- show / hide -------------------------------------------------------------------------

    def toggle(self, anchor: Anchor | None) -> None:
        if self.isVisible():
            self.hide_panel()
            return
        if time.monotonic() - self.last_focus_hide < REOPEN_GUARD:
            return  # this click already closed us via focus loss
        self.show_at(anchor)

    def pointer_anchor(self) -> Anchor:
        pos = QCursor.pos()
        return Anchor(pos.x(), pos.y(), None)

    def _workarea(self, anchor: Anchor | None) -> Rect:
        screens = QGuiApplication.screens()
        primary = QGuiApplication.primaryScreen()
        screens.sort(key=lambda s: s is not primary)
        monitors = []
        for s in screens:
            g, a = s.geometry(), s.availableGeometry()
            monitors.append(
                (
                    Rect(g.x(), g.y(), g.width(), g.height()),
                    Rect(a.x(), a.y(), a.width(), a.height()),
                )
            )
        return monitor_for(anchor, monitors)

    def _place(self) -> None:
        """Move next to the anchor at the current size (fit() sets it; with wrapping chip rows
        it is the height for this width, not sizeHint())."""
        size = self.size()
        x, y = place(self.anchor, (size.width(), size.height()), self._workarea(self.anchor))
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def show_at(self, anchor: Anchor | None) -> None:
        self.anchor = anchor or self.pointer_anchor()
        self.was_active = False
        self.fit()
        self._place()
        self.show()
        if not self._rounded:
            self._rounded = winapi.round_corners(int(self.winId()))
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(50, self._ensure_foreground)
        self.tick.start()
        self.controller.panel_opened()

    def _ensure_foreground(self) -> None:
        """Windows may refuse to activate a window of a background process; without focus the
        panel could not notice a click elsewhere, so insist (once) the way Qt can be told to.
        Only if it never got focus: once the user has moved on, focus is theirs to keep."""
        if self.isVisible() and not self.was_active and not self.dialog_open:
            log.info("panel was not activated; asking Windows for the foreground")
            winapi.force_foreground(int(self.winId()))
            self.activateWindow()

    def hide_panel(self) -> None:
        if not self.isVisible():
            return
        if self.view.open_menu is not None:
            self.view.open_menu.close()
        self.hide()
        self.tick.stop()
        self.controller.panel_closed()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        if self.isVisible():
            self._place()  # grow away from the taskbar, stay on screen

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.key() == Qt.Key.Key_Escape:
            self.hide_panel()
            return
        super().keyPressEvent(event)

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().changeEvent(event)
        if event.type() != event.Type.ActivationChange:
            return
        if self.isActiveWindow():
            self.was_active = True
        else:
            # A menu opening or a dialog of ours may take activation; look again shortly.
            QTimer.singleShot(FOCUS_CHECK_MS, self._focus_out_check)

    def _busy(self) -> bool:
        return self.dialog_open or QApplication.activePopupWidget() is not None

    def _focus_out_check(self) -> None:
        if self.isVisible() and not self.isActiveWindow() and not self._busy():
            self.last_focus_hide = time.monotonic()
            self.hide_panel()

    def _refocus(self) -> None:
        if self.isVisible() and not self.isActiveWindow():
            self.raise_()
            self.activateWindow()

    def show_details(self, result) -> None:
        from repotray.ui.qt.dialogs import DetailsDialog

        def make(parent):
            dlg = DetailsDialog(parent, result)
            dlg.show()
            return dlg

        self.track_dialog(make)

    def track_dialog(self, make) -> QWidget:
        """Open a dialog over the panel; the panel stays open while the dialog is shown."""
        parent = self if self.isVisible() else None
        self.dialog_open = parent is not None
        dlg = make(parent)

        def closed(*_):
            self.dialog_open = False
            if parent is not None:
                QTimer.singleShot(100, self._refocus)

        dlg.destroyed.connect(closed)
        return dlg
