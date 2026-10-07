"""The panel: an undecorated popup anchored to the tray icon (SPEC §2.5).

``PanelView`` lays out a PanelModel; ``Panel`` is the window around it with show/hide behaviour.
The view rebuilds only the sections whose part of the model changed.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import gi

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
from repotray.ui.placement import Anchor, Rect, place

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from repotray.ui.gtk3.details import DetailsDialog  # noqa: E402
from repotray.ui.gtk3.menus import build_menu  # noqa: E402

WIDTH = 480
MAX_ROWS = 12
NAME_CHARS = 24
REOPEN_GUARD = 0.3
TICK_SECONDS = 2


def _icon(name: str, size=Gtk.IconSize.MENU) -> Gtk.Image:
    return Gtk.Image.new_from_icon_name(name, size)


def _label(text: str, *classes: str, xalign: float = 0.0, **kw) -> Gtk.Label:
    lbl = Gtk.Label(label=text, xalign=xalign, **kw)
    ctx = lbl.get_style_context()
    for c in classes:
        ctx.add_class(c)
    return lbl


def _clear(box: Gtk.Container) -> None:
    for child in box.get_children():
        box.remove(child)
        child.destroy()


class BulkWidget(Gtk.Button):
    """A Push all / Sync all / Pull all button: icon (spinner while busy) and label."""

    def __init__(self, kind: ActionKind, action: str, dispatch) -> None:
        super().__init__()
        box = Gtk.Box(spacing=6)
        self.icon = _icon(ACTION_ICONS[kind], Gtk.IconSize.BUTTON)
        self.spinner = Gtk.Spinner()
        self.spinner.set_no_show_all(True)
        self.label = Gtk.Label(label="")
        for w in (self.icon, self.spinner, self.label):
            box.pack_start(w, False, False, 0)
        self.add(box)
        self.connect("clicked", lambda *_: dispatch(action, None))

    def set_model(self, b: BulkButton) -> None:
        self.label.set_text(b.label)
        self.set_sensitive(b.enabled)
        self.set_tooltip_text(b.tooltip)
        self.icon.set_visible(not b.busy)
        self.spinner.set_visible(b.busy)
        (self.spinner.start if b.busy else self.spinner.stop)()


class PanelView(Gtk.Box):
    """Everything inside the panel window. Usable offscreen for screenshots and tests."""

    def __init__(self, dispatch: Callable[[str, object], None], menu_state=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.dispatch = dispatch
        self.menu_state = menu_state or (lambda _open: None)
        self.on_details: Callable[[object], None] | None = None
        self.model: PanelModel | None = None
        self.control_items: tuple = ()
        self.set_margin_top(10)
        self.set_margin_bottom(10)
        self.set_margin_start(12)
        self.set_margin_end(12)
        self.set_size_request(WIDTH - 2 - 24, -1)  # minus border and margins

        # Header
        self.header = Gtk.Box(spacing=8)
        self.summary = _label("", "rt-header", hexpand=True)
        self.summary.set_ellipsize(Pango.EllipsizeMode.END)
        self.resume = Gtk.LinkButton(label="Resume", uri="")
        self.resume.set_no_show_all(True)
        self.resume.connect("activate-link", self._on_resume)
        self.fetched = _label("", "dim-label", xalign=1.0)
        self.refresh_btn = self._flat_icon_button(
            ACTION_ICONS[ActionKind.FETCH],
            "Fetch all now",
            lambda *_: self.dispatch("fetch_all", None),
        )
        self.header_spinner = Gtk.Spinner()
        self.header_spinner.set_no_show_all(True)
        self.header.pack_start(self.summary, True, True, 0)
        self.header.pack_start(self.resume, False, False, 0)
        self.header.pack_start(self.fetched, False, False, 0)
        self.header.pack_start(self.refresh_btn, False, False, 0)
        self.header.pack_start(self.header_spinner, False, False, 6)
        self.gear = Gtk.MenuButton()
        self.gear.add(_icon(ICON_GEAR, Gtk.IconSize.BUTTON))
        self.gear.set_tooltip_text("Settings and more")
        self.gear.set_relief(Gtk.ReliefStyle.NONE)
        self.gear.get_style_context().add_class("rt-action")
        self.header.pack_start(self.gear, False, False, 0)
        self.pack_start(self.header, False, False, 0)

        self.warning = _label("", "dim-label", wrap=True)
        self.warning.set_no_show_all(True)
        self.pack_start(self.warning, False, False, 0)

        # Banner
        self.banner = Gtk.InfoBar()
        self.banner.set_no_show_all(True)
        self.banner_label = _label("", wrap=True)
        self.banner_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.banner.get_content_area().add(self.banner_label)
        self.banner_label.show()
        self.details_btn = self.banner.add_button("Details…", 1)
        self.banner.connect("response", self._on_banner_response)
        self.pack_start(self.banner, False, False, 0)

        # Push all · Sync all · Pull all, above the columns they act on
        bar = Gtk.Box(spacing=6)
        self.push_all = BulkWidget(ActionKind.PUSH, "push_all", self.dispatch)
        self.sync_all = BulkWidget(ActionKind.SYNC, "sync_all", self.dispatch)
        self.pull_all = BulkWidget(ActionKind.PULL, "pull_all", self.dispatch)
        self.sync_all.get_style_context().add_class("suggested-action")
        bar.pack_start(self.push_all, False, False, 0)
        bar.set_center_widget(self.sync_all)
        bar.pack_end(self.pull_all, False, False, 0)
        self.pack_start(bar, False, False, 2)

        self.pack_start(Gtk.Separator(), False, False, 2)

        # Columns
        self.titles = Gtk.Box()
        self.left_title = _label("", "rt-column-title", hexpand=True)
        self.right_title = _label("", "rt-column-title", xalign=1.0, hexpand=True)
        self.titles.pack_start(self.left_title, True, True, 0)
        self.titles.pack_end(self.right_title, True, True, 0)
        self.pack_start(self.titles, False, False, 0)

        self.grid = Gtk.Grid(column_spacing=6, row_spacing=2)
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_propagate_natural_height(True)
        self.scroller.add(self.grid)
        self.pack_start(self.scroller, False, False, 0)

        self.empty = _label("", "dim-label", xalign=0.5)
        self.empty.set_margin_top(6)
        self.empty.set_margin_bottom(6)
        self.pack_start(self.empty, False, False, 0)

        self.sep2 = Gtk.Separator()
        self.pack_start(self.sep2, False, False, 2)
        self.groups = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.pack_start(self.groups, False, False, 0)
        self.expanded = False

        self.show_all()
        # Visibility of these follows the model; a later show_all() must not reveal them.
        for w in (self.empty, self.titles, self.scroller, self.sep2, self.refresh_btn):
            w.set_no_show_all(True)
        self.details_btn.set_no_show_all(True)

    # --- helpers -----------------------------------------------------------------------------

    def _flat_icon_button(self, icon: str, tooltip: str, cb) -> Gtk.Button:
        b = Gtk.Button()
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.add(_icon(icon, Gtk.IconSize.BUTTON))
        b.set_tooltip_text(tooltip)
        b.get_style_context().add_class("rt-action")
        b.connect("clicked", cb)
        return b

    def _popup_repo_menu(self, widget: Gtk.Widget, items) -> None:
        menu = build_menu(items, self.dispatch, self.menu_state)
        menu.attach_to_widget(widget, None)
        menu.popup_at_widget(widget, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)

    def _name_button(self, name: str, tooltip: str, menu, xalign: float) -> Gtk.Button:
        b = Gtk.Button()
        b.set_relief(Gtk.ReliefStyle.NONE)
        lbl = Gtk.Label(label=name, xalign=xalign)
        lbl.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        lbl.set_max_width_chars(NAME_CHARS)
        b.add(lbl)
        b.set_tooltip_text(tooltip)
        b.get_style_context().add_class("rt-name")
        b.connect("clicked", lambda w: self._popup_repo_menu(w, menu))
        return b

    def _action_button(self, btn: Button, path) -> Gtk.Widget:
        if btn.busy:
            sp = Gtk.Spinner()
            sp.start()
            sp.set_tooltip_text(btn.tooltip)
            sp.set_size_request(24, 24)
            return sp
        b = self._flat_icon_button(
            ACTION_ICONS[btn.action],
            btn.tooltip,
            lambda *_: self.dispatch(btn.action.value, path),
        )
        b.set_sensitive(btn.enabled)
        if not btn.enabled:
            # Insensitive widgets show no tooltip; wrap so the reason stays visible.
            ev = Gtk.EventBox()
            ev.add(b)
            ev.set_tooltip_text(btn.tooltip)
            return ev
        return b

    def _markers(self, cell: Cell, right: bool) -> Gtk.Box:
        box = Gtk.Box(spacing=3)
        count = _label(cell.count_text, "rt-count")
        parts: list[Gtk.Widget] = [count]
        if cell.dirty:
            img = _icon(ICON_DIRTY)
            img.set_tooltip_text("Uncommitted changes (push sends commits only)")
            parts.append(img)
        if cell.warning:
            img = _icon(ICON_WARNING)
            img.set_tooltip_text(cell.warning)
            parts.append(img)
        if right:
            parts.reverse()
        for p in parts:
            box.pack_start(p, False, False, 0)
        box.set_halign(Gtk.Align.END if right else Gtk.Align.START)
        return box

    # --- model -------------------------------------------------------------------------------

    def set_control_menu(self, items: tuple) -> None:
        if items == self.control_items:
            return
        self.control_items = items
        self.gear.set_popup(build_menu(items, self.dispatch, self.menu_state))

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
        self.summary.set_text(h.summary)
        self.summary.set_tooltip_text(h.summary)
        ctx = self.summary.get_style_context()
        (ctx.add_class if h.error else ctx.remove_class)("rt-error")
        self.fetched.set_text(h.fetched_text)
        self.resume.set_visible(h.paused)
        self.refresh_btn.set_visible(not h.fetching)
        self.header_spinner.set_visible(h.fetching)
        (self.header_spinner.start if h.fetching else self.header_spinner.stop)()
        self.warning.set_text(h.warning or "")
        self.warning.set_visible(bool(h.warning))

    def _set_banner(self, m: PanelModel) -> None:
        b = m.banner
        if b is None:
            self.banner.hide()
            return
        if b.kind == "error":
            self.banner.set_message_type(Gtk.MessageType.ERROR)
            self.banner_label.set_text(f"⚠ {b.text}")
            self.details_btn.show()
        else:
            self.banner.set_message_type(Gtk.MessageType.INFO)
            self.banner_label.set_text(f"{b.text} ✓")
            self.details_btn.set_visible(b.result is not None and b.result.name == "Sync all")
        self.banner.show()

    def _on_banner_response(self, _bar, response) -> None:
        banner = self.model.banner if self.model else None
        if response == 1 and banner and banner.result and self.on_details:
            self.on_details(banner.result)

    def _on_resume(self, *_):
        self.dispatch("toggle_pause", None)
        return True

    def _set_rows(self, m: PanelModel) -> None:
        self.left_title.set_text(m.columns_title[0])
        self.right_title.set_text(m.columns_title[1])
        _clear(self.grid)
        has_rows = bool(m.rows)
        self.titles.set_visible(has_rows)
        self.scroller.set_visible(has_rows)
        self.empty.set_text(m.empty_text or "")
        self.empty.set_visible(not has_rows)
        for i, row in enumerate(m.rows):
            self._add_row(i, row)
        # Cap the visible height at MAX_ROWS rows; scroll beyond.
        self.grid.show_all()
        # Toplevels may allocate only the minimum height, so pin it: all rows up to MAX_ROWS.
        _min, nat = self.grid.get_preferred_height()
        row_h = max(24, nat // max(1, len(m.rows)))
        cap = row_h * MAX_ROWS
        self.scroller.set_min_content_height(-1)
        self.scroller.set_max_content_height(cap)
        self.scroller.set_min_content_height(min(nat, cap))

    def _add_row(self, i: int, row: Row) -> None:
        g = self.grid
        # columns: name | markers | push | sync | pull | markers | name
        if row.left:
            c = row.left
            g.attach(self._name_button(c.name, c.tooltip, c.menu, 0.0), 0, i, 1, 1)
            g.attach(self._markers(c, right=False), 1, i, 1, 1)
            g.attach(self._action_button(c.button, c.path), 2, i, 1, 1)
        if row.sync:
            g.attach(self._action_button(row.sync, row.sync_path), 3, i, 1, 1)
        else:
            spacer = Gtk.Box()
            spacer.set_size_request(28, -1)
            g.attach(spacer, 3, i, 1, 1)
        if row.right:
            c = row.right
            g.attach(self._action_button(c.button, c.path), 4, i, 1, 1)
            g.attach(self._markers(c, right=True), 5, i, 1, 1)
            name = self._name_button(c.name, c.tooltip, c.menu, 1.0)
            g.attach(name, 6, i, 1, 1)
        # The two name columns share the free width, so the buttons meet in the middle.
        for col in (0, 6):
            w = g.get_child_at(col, i)
            if w is None:
                w = Gtk.Box()
                g.attach(w, col, i, 1, 1)
            w.set_hexpand(True)
            w.set_halign(Gtk.Align.START if col == 0 else Gtk.Align.END)

    def _set_groups(self, m: PanelModel) -> None:
        _clear(self.groups)
        self.sep2.set_visible(bool(m.groups))
        for g in m.groups:
            flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=False)
            flow.set_max_children_per_line(12)
            flow.set_column_spacing(0)
            flow.set_row_spacing(0)
            for chip in g.chips:
                b = Gtk.Button(label=chip.name)
                b.set_relief(Gtk.ReliefStyle.NONE)
                b.get_style_context().add_class("rt-chip")
                b.set_tooltip_text(chip.tooltip)
                b.connect("clicked", lambda w, m=chip.menu: self._popup_repo_menu(w, m))
                flow.add(b)
            if g.collapsed:
                exp = Gtk.Expander(label=g.title)
                exp.set_expanded(self.expanded)
                exp.connect("notify::expanded", self._on_expanded)
                exp.add(flow)
                self.groups.pack_start(exp, False, False, 0)
                continue
            line = Gtk.Box(spacing=6)
            title = Gtk.Box(spacing=4)
            if g.icon_name:
                title.pack_start(_icon(g.icon_name), False, False, 0)
            title.pack_start(_label(g.title, "rt-group-title"), False, False, 0)
            title.set_valign(Gtk.Align.START)
            title.set_margin_top(5)
            line.pack_start(title, False, False, 0)
            line.pack_start(flow, True, True, 0)
            self.groups.pack_start(line, False, False, 0)
        self.groups.show_all()

    def _on_expanded(self, expander: Gtk.Expander, _pspec) -> None:
        self.expanded = expander.get_expanded()


class Panel(Gtk.Window):
    """The popup window. Toggled by a tray click, hidden on Escape, focus loss or second click."""

    def __init__(self, controller, type_hint=Gdk.WindowTypeHint.UTILITY) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.controller = controller
        self.set_title("repotray")
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.set_resizable(False)
        self.set_type_hint(type_hint)
        self.stick()
        self.get_style_context().add_class("repotray-panel")
        self.menus_open = 0
        self.dialog_open = False
        self.anchor: Anchor | None = None
        self.last_focus_hide = 0.0
        self._tick: int | None = None
        self._last_size = (0, 0)
        self.view = PanelView(self._dispatch, self._menu_state)
        self.view.on_details = self.show_details
        self.add(self.view)
        self.view.show()
        self.connect("key-press-event", self._on_key)
        self.connect("focus-out-event", self._on_focus_out)
        self.connect("size-allocate", self._on_size)
        self.connect("delete-event", lambda *_: self.hide_panel() or True)

    def _dispatch(self, action: str, path) -> None:
        self.controller.dispatch(action, path)

    def _menu_state(self, opened: bool) -> None:
        self.menus_open = max(0, self.menus_open + (1 if opened else -1))
        if not opened:
            GLib.timeout_add(150, self._refocus)

    def _refocus(self) -> bool:
        if self.get_visible() and not self.is_active() and self.menus_open == 0:
            self.present()
        return False

    # --- model -------------------------------------------------------------------------------

    def set_model(self, model: PanelModel) -> None:
        self.view.set_model(model)

    def set_control_menu(self, items) -> None:
        self.view.set_control_menu(tuple(items))

    # --- show / hide -------------------------------------------------------------------------

    def toggle(self, anchor: Anchor | None, event_time: int = 0) -> None:
        if self.get_visible():
            self.hide_panel()
            return
        if time.monotonic() - self.last_focus_hide < REOPEN_GUARD:
            return  # this click already closed us via focus-out
        self.show_at(anchor, event_time)

    def _workarea(self, anchor: Anchor | None) -> Rect:
        display = Gdk.Display.get_default()
        mon = None
        if anchor is not None:
            mon = display.get_monitor_at_point(anchor.x, anchor.y)
        if mon is None:
            mon = display.get_primary_monitor() or display.get_monitor(0)
        wa = mon.get_workarea()
        return Rect(wa.x, wa.y, wa.width, wa.height)

    def _place(self) -> None:
        w, h = self.get_size()
        x, y = place(self.anchor, (w, h), self._workarea(self.anchor))
        self.move(x, y)

    def pointer_anchor(self) -> Anchor:
        seat = Gdk.Display.get_default().get_default_seat()
        _screen, x, y = seat.get_pointer().get_position()
        return Anchor(x, y, None)

    def show_at(self, anchor: Anchor | None, event_time: int = 0) -> None:
        self.anchor = anchor or self.pointer_anchor()
        self.show()
        self.resize(1, 1)  # shrink to natural size
        self._place()
        self.present_with_time(event_time or Gtk.get_current_event_time())
        gdkwin = self.get_window()
        if gdkwin is not None:
            gdkwin.focus(event_time or Gdk.CURRENT_TIME)
        if self._tick is None:
            self._tick = GLib.timeout_add_seconds(TICK_SECONDS, self._on_tick)
        self.controller.panel_opened()

    def hide_panel(self) -> None:
        if not self.get_visible():
            return
        self.hide()
        if self._tick is not None:
            GLib.source_remove(self._tick)
            self._tick = None
        self.controller.panel_closed()

    def _on_tick(self) -> bool:
        self.controller.refresh()
        return True

    def _on_key(self, _w, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.hide_panel()
            return True
        return False

    def _on_focus_out(self, *_):
        if self.menus_open or self.dialog_open:
            return False
        # Menus grab focus before their "show" fires; check again shortly.
        GLib.timeout_add(60, self._focus_out_check)
        return False

    def _focus_out_check(self) -> bool:
        busy = self.menus_open or self.dialog_open
        if self.get_visible() and not self.is_active() and not busy:
            self.last_focus_hide = time.monotonic()
            self.hide_panel()
        return False

    def _on_size(self, _w, alloc) -> None:
        size = (alloc.width, alloc.height)
        if size != self._last_size and self.get_visible():
            self._last_size = size
            GLib.idle_add(lambda: self._place() or False)

    def show_details(self, result) -> None:
        self.track_dialog(lambda parent: DetailsDialog(parent, result))

    def track_dialog(self, make) -> Gtk.Window:
        """Open a dialog over the panel; the panel stays open while the dialog is shown."""
        parent = self if self.get_visible() else None
        self.dialog_open = parent is not None
        dlg = make(parent)

        def closed(*_):
            self.dialog_open = False
            if parent is not None:
                GLib.timeout_add(100, self._refocus)

        dlg.connect("destroy", closed)
        return dlg
