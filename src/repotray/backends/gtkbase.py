"""Shared plumbing for the GTK 3 backends (xapp, appindicator, gtkstatusicon)."""

from __future__ import annotations

import logging
import signal
from collections.abc import Callable

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from repotray.icons.names import icon_name  # noqa: E402
from repotray.icons.svg import write_hex_icon  # noqa: E402
from repotray.ui.gtk3 import theme  # noqa: E402
from repotray.ui.gtk3.menus import build_menu  # noqa: E402
from repotray.ui.gtk3.panel import Panel  # noqa: E402

log = logging.getLogger(__name__)


def is_linux(platform) -> bool:
    return getattr(platform, "name", "") == "linux"


def bus_names() -> list[str]:
    """Names on the session bus (empty if there is no bus)."""
    from gi.repository import Gio

    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        res = bus.call_sync(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "ListNames",
            None,
            GLib.VariantType.new("(as)"),
            Gio.DBusCallFlags.NONE,
            2000,
            None,
        )
        return list(res.unpack()[0])
    except Exception:  # noqa: BLE001
        return []


class GtkBackendBase:
    """call_soon/run/quit on the GLib main loop, menus, panel, notifications, clipboard."""

    has_panel = True

    def __init__(self, platform, controller) -> None:
        self.platform = platform
        self.controller = controller
        if not Gtk.init_check(None)[0]:
            raise RuntimeError("cannot open a display")
        cfg = controller.config
        try:
            dark = platform.prefers_dark_panel() if cfg.panel_theme == "auto" else None
        except Exception:  # noqa: BLE001
            dark = None
        theme.apply(cfg.panel_theme, dark)
        self.panel = Panel(controller) if self.caps["panel"] else None
        self._control_items: list = []
        self._fallback_items: list | None = None
        self._icon_name: str | None = None
        self._notify_ok = self._init_notify()

    # --- icons ---
    def icon_ref(self, spec) -> str:
        """Theme icon name, or the path of a full-colour SVG in hex mode."""
        if spec.hex_mode:
            return str(write_hex_icon(spec, self.platform.cache_dir()))
        return icon_name(spec)

    # --- menus ---
    def dispatch(self, action: str, path) -> None:
        self.controller.dispatch(action, path)

    def _menu_state(self, opened: bool) -> None:
        if self.panel is not None:
            self.panel._menu_state(opened)

    def set_menus(self, control, fallback) -> None:
        if self.panel is not None:
            self.panel.set_control_menu(control)
        if control == self._control_items and fallback == self._fallback_items:
            return
        self._control_items, self._fallback_items = (
            list(control),
            (list(fallback) if fallback is not None else None),
        )
        self.apply_menus(
            build_menu(control, self.dispatch),
            build_menu(fallback, self.dispatch) if fallback is not None else None,
        )

    def apply_menus(self, control: Gtk.Menu, fallback: Gtk.Menu | None) -> None:
        raise NotImplementedError

    # --- panel ---
    def show_panel_model(self, model) -> None:
        if self.panel is not None:
            self.panel.set_model(model)

    def open_panel(self) -> None:
        if self.panel is not None:
            self.panel.toggle(None)

    # --- services ---
    def _init_notify(self) -> bool:
        try:
            gi.require_version("Notify", "0.7")
            from gi.repository import Notify

            return bool(Notify.init("repotray"))
        except (ValueError, ImportError):
            return False

    def notify(self, title: str, body: str) -> None:
        if self._notify_ok:
            from gi.repository import Notify

            try:
                n = Notify.Notification.new(title, body, "repotray-symbolic")
                n.show()
                return
            except GLib.Error as exc:
                log.warning("notification failed: %s", exc)
        self.platform.notify(title, body)

    def show_commits(self, title: str, subtitle: str, log, on_open_editor) -> None:
        from repotray.ui.gtk3.commits import CommitsDialog

        def make(parent):
            dlg = CommitsDialog(parent, title, subtitle, log, on_open_editor)
            dlg.present()
            return dlg

        if self.panel is not None:
            self.panel.track_dialog(make)
        else:
            make(None)

    def copy_to_clipboard(self, text: str) -> None:
        cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        cb.set_text(text, -1)
        cb.store()

    def show_about(self, info: dict) -> None:
        dlg = Gtk.AboutDialog(
            program_name=info["name"],
            version=info["version"],
            comments=info["comments"],
            website=info["website"],
            license_type=Gtk.License.MIT_X11,
            copyright=info["copyright"],
            logo_icon_name="repotray-symbolic",
        )
        dlg.add_credit_section("Icon", [info["credits"]])
        dlg.set_keep_above(True)
        dlg.connect("response", lambda d, _r: d.destroy())
        dlg.present()

    # --- loop ---
    def call_soon(self, fn: Callable[[], None]) -> None:
        def run_once():
            try:
                fn()
            except Exception:  # noqa: BLE001
                log.exception("UI callback failed")
            return False

        GLib.idle_add(run_once)

    def install_signal_handlers(self, on_quit: Callable[[], None]) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda *_: on_quit() or False)

    def run(self) -> None:
        Gtk.main()

    def quit(self) -> None:
        GLib.idle_add(lambda: Gtk.main_quit() or False)
