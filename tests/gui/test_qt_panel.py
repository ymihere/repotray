"""GUI tests for the Qt panel and the ``qt`` backend, driven by the demo scheduler.

They run on Qt's offscreen platform (set in tests/conftest.py), so no display is needed; with
REPOTRAY_GUI_TESTS=1 they use the real one (and show windows):

    pytest tests/gui/test_qt_panel.py
"""

from __future__ import annotations

import time

import pytest

pytestmark = pytest.mark.gui

pytest.importorskip("PySide6")
from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QToolButton, QWidget  # noqa: E402

from repotray.app import Controller  # noqa: E402
from repotray.backends.qt import QtBackend  # noqa: E402
from repotray.core.config import ConfigWatcher  # noqa: E402
from repotray.core.demo import DemoScheduler  # noqa: E402
from repotray.platform import current  # noqa: E402
from repotray.ui.placement import Anchor  # noqa: E402
from repotray.ui.qt.menus import literal  # noqa: E402
from repotray.ui.qt.panel import BANNER_COLORS, NameButton  # noqa: E402
from repotray.ui.qt.widgets import Spinner  # noqa: E402

BOTTOM = Anchor(1500, 1150, "bottom")


def pump(seconds: float = 0.2, until=None) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.01)
    return until() if until else True


@pytest.fixture
def ui(tmp_path):
    sched = DemoScheduler(ConfigWatcher(tmp_path / "c.toml"))
    ctl = Controller(current(), sched, QtBackend, demo=True)
    ctl.render()
    sched.start()
    pump(0.2)
    panel = ctl.backend.panel
    yield ctl, panel
    panel.hide_panel()
    sched.stop()
    ctl.backend.icon.hide()
    pump(0.1)


def name_of(widget) -> str | None:
    return widget.full_name if isinstance(widget, NameButton) else None


def test_panel_rows_and_buttons(ui):
    ctl, panel = ui
    v = panel.view
    assert v.left_title.text() == "Push (3)" and v.right_title.text() == "Pull (3)"
    # One repo per row, alphabetical: push side left, pull side right.
    assert [name_of(v.cell(0, r)) for r in range(5)] == [
        "api-gateway",
        "design-system",
        "infra",
        None,
        None,
    ]
    assert [name_of(v.cell(6, r)) for r in range(5)] == [
        None,
        "design-system",
        None,
        "mobile-app",
        "website",
    ]
    sync = v.cell(3, 1)
    assert isinstance(sync, QToolButton) and sync.isEnabled()
    diverged_push = v.cell(2, 1)
    assert not diverged_push.isEnabled() and diverged_push.toolTip() == "Diverged — use Sync"
    push = v.cell(2, 0)
    assert push.isEnabled() and push.toolTip() == "Push 3 commits to origin/main"
    labels = [w.label_text() for w in (v.push_all, v.sync_all, v.pull_all)]
    assert labels == ["Push all", "Sync all", "Pull all"]
    assert all(w.isEnabled() for w in (v.push_all, v.sync_all, v.pull_all))
    assert v.sync_all.isDefault()
    assert [g.title for g in v.model.groups] == [
        "Uncommitted (3)",
        "No upstream (2)",
        "Fetch failed (1)",
        "In sync (2)",
    ]
    assert v.groups.count() == 5  # three title lines + the "In sync" expander and its chips


def test_push_shows_spinner_then_success_banner(ui):
    ctl, panel = ui
    panel.show_at(BOTTOM)
    pump(0.2)
    panel.view.cell(2, 2).click()  # infra ↑1
    assert pump(1.0, lambda: isinstance(panel.view.cell(2, 2), Spinner))
    assert panel.view.cell(2, 2).is_spinning()
    assert pump(
        3.0,
        lambda: panel.view.banner.isVisible() and "Pushed infra" in panel.view.banner_label.text(),
    )
    assert panel.view.banner_kind == "success"
    names = [name_of(panel.view.cell(c, r)) for r in range(5) for c in (0, 6)]
    assert "infra" not in names  # nothing left to do: its row is gone


def test_push_all_runs_every_push(ui):
    ctl, panel = ui
    panel.show_at(BOTTOM)
    pump(0.2)
    panel.view.push_all.click()
    assert pump(1.0, lambda: panel.view.push_all.busy)
    assert "Pushing" in panel.view.push_all.label_text()
    assert pump(5.0, lambda: "Pushed 2 of 2" in panel.view.banner_label.text())
    assert panel.view.push_all.label_text() == "Push all"
    assert not panel.view.push_all.isEnabled()  # nothing left to push


def test_failed_pull_shows_error_banner_and_details(ui):
    ctl, panel = ui
    panel.show_at(BOTTOM)
    pump(0.2)
    panel.view.cell(4, 3).click()  # mobile-app: pulling fails in the demo
    assert pump(3.0, lambda: "fast-forward" in panel.view.banner_label.text())
    assert panel.view.banner_kind == "error"
    assert panel.view.details_btn.isVisible()
    panel.view.details_btn.click()
    pump(0.2)
    dialogs = [w for w in QApplication.topLevelWidgets() if w.isVisible() and w is not panel]
    details = next(d for d in dialogs if d.windowTitle() == "repotray — mobile-app")
    assert "mobile-app: pull failed" in details.text
    assert panel.dialog_open and panel.isVisible()  # the dialog keeps the panel open
    details.close()
    assert pump(1.0, lambda: not panel.dialog_open)


def test_escape_hides(ui):
    ctl, panel = ui
    panel.show_at(BOTTOM)
    assert pump(1.0, panel.isVisible)
    assert ctl.panel_visible
    QApplication.sendEvent(
        panel, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )
    pump(0.1)
    assert not panel.isVisible() and not ctl.panel_visible


def test_focus_loss_hides(ui):
    ctl, panel = ui
    panel.show_at(BOTTOM)
    if not pump(2.0, panel.isActiveWindow):
        pytest.skip("the platform did not activate the panel")
    thief = QWidget()
    thief.setWindowTitle("focus thief")
    thief.resize(100, 100)
    thief.show()
    thief.activateWindow()
    try:
        assert pump(2.0, lambda: not panel.isVisible())
        assert not ctl.panel_visible
    finally:
        thief.close()


def test_reopen_guard(ui):
    ctl, panel = ui
    panel.last_focus_hide = time.monotonic()
    panel.toggle(BOTTOM)
    pump(0.05)
    assert not panel.isVisible()  # the click that caused the focus loss does not reopen
    time.sleep(0.35)
    panel.toggle(BOTTOM)
    assert pump(1.0, panel.isVisible)
    panel.toggle(BOTTOM)  # a second click closes
    pump(0.05)
    assert not panel.isVisible()


def test_placement_flush_with_the_taskbar(ui):
    ctl, panel = ui
    screen = QGuiApplication.primaryScreen()
    avail = screen.availableGeometry()
    anchor = Anchor(avail.right() - 100, avail.bottom() + 1, "bottom")
    panel.show_at(anchor)
    pump(0.3)
    g = panel.geometry()
    assert avail.contains(g)
    assert g.bottom() == avail.bottom()  # flush with the bar
    # Rows coming and going resize the window and keep it anchored.
    panel.view.push_all.click()
    assert pump(5.0, lambda: "Pushed 2 of 2" in panel.view.banner_label.text())
    pump(0.3)
    assert panel.geometry().bottom() == avail.bottom()


def test_repo_menu_and_incoming_commits_dialog(ui, monkeypatch):
    ctl, panel = ui
    opened = []
    monkeypatch.setattr(ctl.platform, "open_file", lambda p, t="": opened.append((p, t)))
    monkeypatch.setattr(ctl.platform, "cache_dir", lambda: ctl.scheduler.watcher.path.parent)
    panel.show_at(BOTTOM)
    pump(0.3)
    website = panel.view.cell(6, 4)
    assert name_of(website) == "website"
    website.click()
    assert pump(1.0, lambda: panel.view.open_menu is not None)
    texts = [a.text() for a in panel.view.open_menu.actions() if not a.isSeparator()]
    assert texts == [
        "Show incoming commits (4)…",
        "Open terminal here",
        "Open folder",
        "Copy path",
        "Fetch now",
    ]
    panel.view.open_menu.actions()[0].trigger()
    be = ctl.backend
    assert pump(3.0, lambda: getattr(be, "dialog", None) is not None)
    text = be.dialog.view.toPlainText()
    assert "Fix race in session refresh" in text and "Ada Example" in text
    pump(0.3)
    assert panel.isVisible()  # the dialog does not close the panel
    be.dialog.editor_button.click()
    assert opened and opened[0][0].name == "incoming-website.txt"
    action = be.dialog.action_button
    assert action.text().endswith("Pull") and action.isEnabled()  # "↓ Pull" without icon font
    action.click()  # pulls and closes the dialog
    assert pump(1.0, lambda: be.dialog is None)
    assert pump(4.0, lambda: "Pulled website" in panel.view.banner_label.text())
    assert pump(1.0, lambda: not panel.dialog_open)


def test_tray_clicks(ui):
    ctl, panel = ui
    be = ctl.backend
    R = QSystemTrayIcon.ActivationReason  # noqa: N806
    be._on_activated(R.Trigger)
    assert pump(1.0, panel.isVisible)
    be._on_activated(R.Trigger)
    pump(0.05)
    assert not panel.isVisible()
    be._on_activated(R.MiddleClick)
    assert pump(1.0, lambda: ctl.snapshot.fetch_mode.value == "fetching")


def test_menus_follow_the_model(ui):
    ctl, panel = ui
    gear = [a.text() for a in panel.view.gear_menu.actions() if not a.isSeparator()]
    tray = [a.text() for a in ctl.backend.menu.actions() if not a.isSeparator()]
    assert (
        gear
        == tray
        == [
            "Fetch all now",
            "Pause fetching",
            "Rescan roots",
            "Open config file",
            "Autostart",
            "About",
            "Quit",
        ]
    )
    pause = next(a for a in ctl.backend.menu.actions() if a.text() == "Pause fetching")
    assert pause.isCheckable() and not pause.isChecked()
    pause.trigger()
    assert pump(1.0, lambda: "Fetching paused" in panel.view.summary.text_full())
    assert not panel.view.resume.isHidden()
    pause = next(a for a in ctl.backend.menu.actions() if a.text() == "Pause fetching")
    assert pause.isChecked()


def test_ampersands_are_shown_literally():
    assert literal("R&D tools") == "R&&D tools"


def test_banner_colours_exist_for_both_schemes():
    for kind in ("error", "success"):
        for dark in (False, True):
            bg, fg = BANNER_COLORS[(kind, dark)]
            assert bg.startswith("#") and fg.startswith("#")


def test_tray_icon_has_every_size():
    from repotray.core.indicator import IconSpec
    from repotray.ui.qt.icons import TRAY_SIZES, tray_icon

    icon = tray_icon(IconSpec("attention", "warning", "warning"), "#1e1e1e")
    sizes = sorted(s.width() for s in icon.availableSizes())
    assert sizes == sorted(TRAY_SIZES)
