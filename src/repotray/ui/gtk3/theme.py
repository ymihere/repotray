"""Panel theme: dark/light choice and a small CSS provider. No hard-coded colours."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

CSS = b"""
.repotray-panel {
    border: 1px solid alpha(currentColor, 0.18);
}
.repotray-panel .rt-header { font-weight: bold; }
.repotray-panel .rt-column-title { font-weight: bold; }
.repotray-panel .rt-count { font-feature-settings: "tnum"; }
.repotray-panel .rt-name { padding-left: 4px; padding-right: 4px; }
.repotray-panel .rt-chip { padding: 0 4px; min-height: 0; }
.repotray-panel .rt-action { padding: 2px; min-width: 0; min-height: 0; }
.repotray-panel .rt-group-title { font-weight: bold; }
.repotray-panel .rt-error { font-weight: bold; }
"""

_provider: Gtk.CssProvider | None = None


def apply(panel_theme: str, prefers_dark: bool | None) -> None:
    """``auto``: follow the desktop panel's dark/light choice; ``dark``/``light`` force it."""
    settings = Gtk.Settings.get_default()
    if settings is None:
        return
    if panel_theme == "dark":
        settings.props.gtk_application_prefer_dark_theme = True
    elif panel_theme == "light":
        settings.props.gtk_application_prefer_dark_theme = False
    elif panel_theme == "auto" and prefers_dark is not None:
        settings.props.gtk_application_prefer_dark_theme = prefers_dark
    install_css()


def install_css() -> None:
    global _provider
    if _provider is not None:
        return
    screen = Gdk.Screen.get_default()
    if screen is None:
        return
    _provider = Gtk.CssProvider()
    _provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        screen, _provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
