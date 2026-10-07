"""GUI tests for the GTK panel, driven by the demo scheduler. Need a display:

REPOTRAY_GUI_TESTS=1 pytest tests/gui
"""

from __future__ import annotations

import os
import time

import pytest

pytestmark = [
    pytest.mark.gui,
    pytest.mark.skipif(
        os.environ.get("REPOTRAY_GUI_TESTS") != "1" or not os.environ.get("DISPLAY"),
        reason="GUI tests need REPOTRAY_GUI_TESTS=1 and a display",
    ),
]

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from repotray.app import Controller  # noqa: E402
from repotray.backends.base import caps  # noqa: E402
from repotray.backends.fake import FakeBackend  # noqa: E402
from repotray.core.config import ConfigWatcher  # noqa: E402
from repotray.core.demo import DemoScheduler  # noqa: E402
from repotray.platform import current  # noqa: E402
from repotray.ui.gtk3.panel import Panel  # noqa: E402
from repotray.ui.placement import Anchor  # noqa: E402

_KEEP: list = []


def pump(seconds: float = 0.2, until=None) -> bool:
    deadline = time.monotonic() + seconds
    ctx = GLib.MainContext.default()
    while time.monotonic() < deadline:
        while ctx.pending():
            ctx.iteration(False)
        if until is not None and until():
            return True
        time.sleep(0.01)
    return until() if until else True


class GtkTestBackend(FakeBackend):
    """Records like FakeBackend but runs callbacks on the GLib loop and hosts a real Panel."""

    def __init__(self, platform, controller):
        c = caps(tooltip=True, tooltip_markup=True, label=True, panel=True, two_menus=True)
        super().__init__(platform, controller, c)
        self.panel = Panel(controller)

    def call_soon(self, fn):
        GLib.idle_add(lambda: fn() or False)

    def show_panel_model(self, model):
        super().show_panel_model(model)
        self.panel.set_model(model)

    def set_menus(self, control, fallback):
        super().set_menus(control, fallback)
        self.panel.set_control_menu(control)

    def show_commits(self, title, subtitle, log, on_open_editor):
        from repotray.ui.gtk3.commits import CommitsDialog

        def make(parent):
            self.dialog = CommitsDialog(parent, title, subtitle, log, on_open_editor)
            self.dialog.present()
            return self.dialog

        self.panel.track_dialog(make)


@pytest.fixture
def ui(tmp_path):
    sched = DemoScheduler(ConfigWatcher(tmp_path / "c.toml"))
    ctl = Controller(current(), sched, GtkTestBackend, demo=True)
    ctl.render()
    sched.start()
    pump(0.2)
    panel = ctl.backend.panel
    yield ctl, panel
    panel.hide_panel()
    sched.stop()
    pump(0.1)
    _KEEP.append(ctl)


def grid_cell(panel, col, row):
    return panel.view.grid.get_child_at(col, row)


def name_of(widget):
    if widget is None:
        return None
    if isinstance(widget, Gtk.Button):
        return widget.get_child().get_text()
    return None


def test_panel_rows_and_buttons(ui):
    ctl, panel = ui
    v = panel.view
    assert v.left_title.get_text() == "Push (3)" and v.right_title.get_text() == "Pull (3)"
    # One repo per row, alphabetical: push side left, pull side right.
    assert [name_of(grid_cell(panel, 0, r)) for r in range(5)] == [
        "api-gateway",
        "design-system",
        "infra",
        None,
        None,
    ]
    assert [name_of(grid_cell(panel, 6, r)) for r in range(5)] == [
        None,
        "design-system",
        None,
        "mobile-app",
        "website",
    ]
    sync = grid_cell(panel, 3, 1)
    assert isinstance(sync, Gtk.Button) and sync.get_sensitive()
    diverged_push = grid_cell(panel, 2, 1)  # disabled: wrapped in an EventBox for its tooltip
    assert isinstance(diverged_push, Gtk.EventBox)
    assert diverged_push.get_tooltip_text() == "Diverged — use Sync"
    push = grid_cell(panel, 2, 0)
    assert push.get_sensitive() and push.get_tooltip_text() == "Push 3 commits to origin/main"
    labels = [w.label.get_text() for w in (v.push_all, v.sync_all, v.pull_all)]
    assert labels == ["Push all", "Sync all", "Pull all"]
    assert all(w.get_sensitive() for w in (v.push_all, v.sync_all, v.pull_all))
    titles = [c for c in v.groups.get_children()]
    assert len(titles) == 4  # uncommitted, no upstream, fetch failed, in sync


def test_push_shows_spinner_then_success_banner(ui):
    ctl, panel = ui
    panel.show_at(Anchor(4000, 1400, "bottom"))
    pump(0.2)
    grid_cell(panel, 2, 2).clicked()  # infra ↑1
    assert pump(1.0, lambda: isinstance(grid_cell(panel, 2, 2), Gtk.Spinner))
    assert pump(
        3.0,
        lambda: (
            panel.view.banner.get_visible() and "Pushed infra" in panel.view.banner_label.get_text()
        ),
    )
    # infra has nothing left to do: its row is gone
    names = [name_of(grid_cell(panel, c, r)) for r in range(5) for c in (0, 6)]
    assert "infra" not in names


def test_push_all_runs_every_push(ui):
    ctl, panel = ui
    panel.show_at(Anchor(4000, 1400, "bottom"))
    pump(0.2)
    panel.view.push_all.clicked()
    assert pump(1.0, lambda: panel.view.push_all.spinner.get_visible())
    assert "Pushing" in panel.view.push_all.label.get_text()
    assert pump(5.0, lambda: "Pushed 2 of 2" in panel.view.banner_label.get_text())
    assert panel.view.push_all.label.get_text() == "Push all"
    assert not panel.view.push_all.get_sensitive()  # nothing left to push


def test_failed_pull_shows_error_banner_with_details(ui):
    ctl, panel = ui
    panel.show_at(Anchor(4000, 1400, "bottom"))
    pump(0.2)
    grid_cell(panel, 4, 3).clicked()  # mobile-app pull fails in the demo
    assert pump(3.0, lambda: "fast-forward" in panel.view.banner_label.get_text())
    assert panel.view.banner.get_message_type() == Gtk.MessageType.ERROR
    assert panel.view.details_btn.get_visible()


def _key(panel, keyval):
    ev = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
    ev.key.keyval = keyval
    ev.key.window = panel.get_window()
    return panel.emit("key-press-event", ev)


def test_escape_hides(ui):
    ctl, panel = ui
    panel.show_at(Anchor(4000, 1400, "bottom"))
    assert pump(1.0, panel.get_visible)
    assert ctl.panel_visible
    _key(panel, Gdk.KEY_Escape)
    pump(0.1)
    assert not panel.get_visible() and not ctl.panel_visible


def test_focus_loss_hides(ui):
    ctl, panel = ui
    panel.show_at(Anchor(4000, 1400, "bottom"), Gtk.get_current_event_time())
    if not pump(2.0, panel.is_active):
        pytest.skip("window manager did not focus the panel (screen locked?)")
    thief = Gtk.Window(title="focus thief")
    thief.set_default_size(100, 100)
    thief.show_all()
    pump(0.1)
    try:
        # A timestamped present, like a real click; without one Muffin's focus-stealing
        # prevention sometimes keeps focus on the panel.
        from gi.repository import GdkX11

        thief.present_with_time(GdkX11.x11_get_server_time(thief.get_window()))
    except (ImportError, TypeError, AttributeError):
        thief.present()
    try:
        pump(3.0, lambda: thief.is_active() or not panel.get_visible())
        if panel.get_visible() and panel.is_active():
            pytest.skip("window manager kept focus on the panel")
        assert pump(1.0, lambda: not panel.get_visible())
    finally:
        thief.destroy()


def test_reopen_guard(ui):
    ctl, panel = ui
    panel.last_focus_hide = time.monotonic()
    panel.toggle(Anchor(4000, 1400, "bottom"))
    pump(0.05)
    assert not panel.get_visible()  # the click that caused the focus-out does not reopen
    time.sleep(0.35)
    panel.toggle(Anchor(4000, 1400, "bottom"))
    assert pump(1.0, panel.get_visible)
    panel.toggle(Anchor(4000, 1400, "bottom"))  # second click closes
    pump(0.05)
    assert not panel.get_visible()


def test_placement_on_screen(ui):
    ctl, panel = ui
    panel.show_at(Anchor(4000, 1400, "bottom"))
    pump(0.5)
    x, y = panel.get_position()
    w, h = panel.get_size()
    display = Gdk.Display.get_default()
    wa = display.get_monitor_at_point(4000, 1400).get_workarea()
    assert wa.x <= x and x + w <= wa.x + wa.width
    assert wa.y <= y and y + h <= wa.y + wa.height


def test_incoming_commits_dialog_keeps_panel_open(ui, monkeypatch):
    ctl, panel = ui
    opened = []
    monkeypatch.setattr(ctl.platform, "open_file", lambda p, t="": opened.append((p, t)))
    monkeypatch.setattr(ctl.platform, "cache_dir", lambda: ctl.scheduler.watcher.path.parent)
    panel.show_at(Anchor(4000, 1400, "bottom"))
    pump(0.3)
    website = next(s for s in ctl.snapshot.repos if s.name == "website")
    ctl.dispatch("show_incoming", website.path)
    be = ctl.backend
    assert pump(3.0, lambda: getattr(be, "dialog", None) is not None)
    buf = be.dialog.view.get_buffer()
    text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
    assert "Fix race in session refresh" in text and "Ada Example" in text
    pump(0.5)
    assert panel.get_visible()  # the dialog does not close the panel
    be.dialog.response(1)  # Open in editor
    assert opened and opened[0][0].name == "incoming-website.txt"
    be.dialog.response(Gtk.ResponseType.CLOSE)
    pump(0.3)
