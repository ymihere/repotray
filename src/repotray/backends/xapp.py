"""Cinnamon / MATE / Xfce via XApp.StatusIcon (the first-class Linux Mint backend).

No primary menu: the applet forwards every click as ``button-release-event(x, y, button, time,
panel_position)``; button 1 toggles the panel anchored to the icon, button 2 fetches, button 3
shows the secondary (control) menu.
"""

from __future__ import annotations

from typing import ClassVar

from repotray.backends.base import ProbeResult, caps
from repotray.backends.gtkbase import GtkBackendBase, bus_names, is_linux
from repotray.ui.placement import Anchor, side_from_position


class XAppBackend(GtkBackendBase):
    name: ClassVar[str] = "xapp"
    caps = caps(
        tooltip=True,
        tooltip_markup=True,
        label=True,
        panel=True,
        two_menus=True,
        notifications=True,
        anchor=True,
    )

    @classmethod
    def probe(cls, platform) -> ProbeResult:
        if not is_linux(platform):
            return ProbeResult(0, "Linux only")
        import gi

        gi.require_version("XApp", "1.0")
        from gi.repository import XApp  # noqa: F401

        if any(n.startswith("org.x.StatusIconMonitor.") for n in bus_names()):
            return ProbeResult(100, "XApp status applet running")
        return ProbeResult(30, "XApp available, but no status applet on the bus")

    def __init__(self, platform, controller) -> None:
        super().__init__(platform, controller)
        import gi

        gi.require_version("XApp", "1.0")
        from gi.repository import XApp

        self.icon = XApp.StatusIcon()
        self.icon.set_name("repotray")
        self.icon.set_icon_name("repotray-symbolic")
        self.icon.set_tooltip_text("repotray")
        self.icon.connect("button-release-event", self._on_release)
        self._label = None
        self._tooltip = None

    def set_icon(self, spec) -> None:
        ref = self.icon_ref(spec)
        if ref != self._icon_name:
            self._icon_name = ref
            self.icon.set_icon_name(ref)

    def reload_icon(self) -> None:
        """Make the applet look the icon up again (after new icon files were installed)."""
        if self._icon_name:
            self.icon.set_icon_name("image-missing")
            self.icon.set_icon_name(self._icon_name)

    def set_label(self, text: str) -> None:
        if text != self._label:
            self._label = text
            self.icon.set_label(text)

    def set_tooltip(self, text: str) -> None:
        if text != self._tooltip:
            self._tooltip = text
            self.icon.set_tooltip_text(text)

    def apply_menus(self, control, fallback) -> None:
        self.icon.set_secondary_menu(control)

    def _on_release(self, _icon, x, y, button, time, position) -> None:
        if button == 1 and self.panel is not None:
            self.panel.toggle(Anchor(x, y, side_from_position(position)), time)
        elif button == 2:
            self.controller.fetch_all()
