"""Legacy XEmbed tray via Gtk.StatusIcon (X11 only; deprecated in GTK but still widely hosted).

``activate`` toggles the panel anchored with ``get_geometry()``; ``popup-menu`` shows the control
menu; middle click fetches. No label support.
"""

from __future__ import annotations

import os
import warnings
from typing import ClassVar

from repotray.backends.base import ProbeResult, caps
from repotray.backends.gtkbase import GtkBackendBase, is_linux
from repotray.ui.placement import ICON_HALF, Anchor

# Gtk.StatusIcon is deprecated but remains the only XEmbed tray API in GTK 3.
warnings.filterwarnings("ignore", message=r".*Gtk\.StatusIcon", category=DeprecationWarning)


class GtkStatusIconBackend(GtkBackendBase):
    name: ClassVar[str] = "gtkstatusicon"
    caps = caps(
        tooltip=True,
        tooltip_markup=True,
        panel=True,
        two_menus=True,
        notifications=True,
        anchor=True,
    )

    @classmethod
    def probe(cls, platform) -> ProbeResult:
        if not is_linux(platform):
            return ProbeResult(0, "Linux only")
        if os.environ.get("XDG_SESSION_TYPE") == "wayland" or not os.environ.get("DISPLAY"):
            return ProbeResult(0, "needs an X11 session")
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk

        if not hasattr(Gtk, "StatusIcon"):
            return ProbeResult(0, "Gtk.StatusIcon missing")
        return ProbeResult(20, "X11 session (XEmbed tray, deprecated)")

    def __init__(self, platform, controller) -> None:
        super().__init__(platform, controller)
        from gi.repository import Gtk

        self.icon = Gtk.StatusIcon()
        self.icon.set_title("repotray")
        self.icon.set_name("repotray")
        self.icon.set_from_icon_name("repotray-symbolic")
        self.icon.connect("activate", self._on_activate)
        self.icon.connect("popup-menu", self._on_popup)
        self.icon.connect("button-press-event", self._on_press)
        self._menu = None
        self._tooltip = None

    def set_icon(self, spec) -> None:
        ref = self.icon_ref(spec)
        if ref == self._icon_name:
            return
        self._icon_name = ref
        if spec.hex_mode:
            self.icon.set_from_file(ref)
        else:
            self.icon.set_from_icon_name(ref)

    def set_label(self, text: str) -> None:
        pass

    def set_tooltip(self, text: str) -> None:
        if text != self._tooltip:
            self._tooltip = text
            self.icon.set_tooltip_markup(text)

    def apply_menus(self, control, fallback) -> None:
        self._menu = control

    def anchor(self) -> Anchor | None:
        from gi.repository import Gdk

        ok, _screen, area, _orientation = self.icon.get_geometry()
        if not ok:
            return None
        display = Gdk.Display.get_default()
        mon = display.get_monitor_at_point(area.x, area.y)
        geo = mon.get_geometry()
        cx = area.x + area.width // 2 - ICON_HALF
        cy = area.y + area.height // 2 - ICON_HALF
        if area.y > geo.y + geo.height // 2:
            return Anchor(cx, area.y, "bottom")
        if area.y + area.height < geo.y + geo.height // 2 and area.height < geo.height // 4:
            if area.x < geo.x + geo.width // 8:
                return Anchor(area.x + area.width, cy, "left")
            if area.x > geo.x + geo.width * 7 // 8:
                return Anchor(area.x, cy, "right")
            return Anchor(cx, area.y + area.height, "top")
        return Anchor(cx, area.y, None)

    def _on_activate(self, _icon) -> None:
        from gi.repository import Gtk

        if self.panel is not None:
            self.panel.toggle(self.anchor(), Gtk.get_current_event_time())

    def _on_popup(self, icon, button, time) -> None:
        from gi.repository import Gtk

        if self._menu is not None:
            self._menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, time)

    def _on_press(self, _icon, event) -> bool:
        if event.button == 2:
            self.controller.fetch_all()
            return True
        return False
