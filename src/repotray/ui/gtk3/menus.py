"""MenuItem models → Gtk.Menu."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk  # noqa: E402


def build_menu(
    items: Sequence, dispatch: Callable[[str, object], None], on_open_close=None
) -> Gtk.Menu:
    """Build a Gtk.Menu. ``dispatch(action, path)`` is called on activation."""
    menu = Gtk.Menu()
    for item in items:
        menu.append(_item(item, dispatch, on_open_close))
    menu.show_all()
    if on_open_close is not None:
        menu.connect("show", lambda *_: on_open_close(True))
        menu.connect("deactivate", lambda *_: on_open_close(False))
    return menu


def _item(item, dispatch, on_open_close) -> Gtk.MenuItem:
    if item.separator:
        return Gtk.SeparatorMenuItem()
    if item.checked is not None:
        mi = Gtk.CheckMenuItem(label=item.label)
        mi.set_active(bool(item.checked))
    else:
        mi = Gtk.MenuItem(label=item.label)
    mi.set_sensitive(item.enabled and (item.action is not None or bool(item.children)))
    if item.tooltip:
        mi.set_tooltip_text(item.tooltip)
    if item.children:
        mi.set_submenu(build_menu(item.children, dispatch))
    elif item.action is not None:
        action, path = item.action, item.path
        mi.connect("activate", lambda *_: dispatch(action, path))
    return mi
