"""KDE, GNOME (with the AppIndicator extension), Xfce, … via StatusNotifierItem (AppIndicator).

AppIndicator delivers no click events: left click always opens its menu. The menu is therefore the
panel rendered as a menu, starting with "Open panel…"; middle click (secondary activate) opens the
panel at the pointer. There are no tooltips.
"""

from __future__ import annotations

from typing import ClassVar

from repotray.backends.base import ProbeResult, caps
from repotray.backends.gtkbase import GtkBackendBase, bus_names, is_linux


def _indicator_module():
    import gi

    for name in ("AyatanaAppIndicator3", "AppIndicator3"):
        try:
            gi.require_version(name, "0.1")
            return __import__("gi.repository", fromlist=[name]).__dict__[name]
        except (ValueError, ImportError, KeyError):
            continue
    raise ImportError("neither AyatanaAppIndicator3 nor AppIndicator3 0.1 is installed")


class AppIndicatorBackend(GtkBackendBase):
    name: ClassVar[str] = "appindicator"
    caps = caps(label=True, panel=True, notifications=True)
    wants_fallback_menu = True

    @classmethod
    def probe(cls, platform) -> ProbeResult:
        if not is_linux(platform):
            return ProbeResult(0, "Linux only")
        mod = _indicator_module()
        if "org.kde.StatusNotifierWatcher" in bus_names():
            return ProbeResult(80, f"{mod.__name__.split('.')[-1]} with a StatusNotifierWatcher")
        return ProbeResult(5, "no StatusNotifierWatcher on the bus")

    def __init__(self, platform, controller) -> None:
        super().__init__(platform, controller)
        ai = _indicator_module()
        self.indicator = ai.Indicator.new(
            "repotray", "repotray-symbolic", ai.IndicatorCategory.APPLICATION_STATUS
        )
        self.indicator.set_status(ai.IndicatorStatus.ACTIVE)
        self.indicator.set_title("repotray")
        self._label = None
        self._theme_path: str | None = None

    def set_icon(self, spec) -> None:
        ref = self.icon_ref(spec)
        if ref == self._icon_name:
            return
        self._icon_name = ref
        if spec.hex_mode:
            # AppIndicator wants a name: point its theme path at our cache dir.
            from pathlib import Path

            p = Path(ref)
            if self._theme_path != str(p.parent):
                self._theme_path = str(p.parent)
                self.indicator.set_icon_theme_path(self._theme_path)
            self.indicator.set_icon_full(p.stem, "repotray")
        else:
            self.indicator.set_icon_full(ref, "repotray")

    def set_label(self, text: str) -> None:
        if text != self._label:
            self._label = text
            self.indicator.set_label(text, "↑99 ↓99")

    def set_tooltip(self, text: str) -> None:
        pass  # not supported by StatusNotifierItem hosts we target

    def apply_menus(self, control, fallback) -> None:
        menu = fallback if fallback is not None else control
        items = menu.get_children()
        if items:
            # The first item is "Open panel…": middle click activates it.
            self.indicator.set_secondary_activate_target(items[0])
        self.indicator.set_menu(menu)
