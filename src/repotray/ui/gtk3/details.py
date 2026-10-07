"""Details dialog for an ActionResult: the exact commands, exit status and full output."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from repotray.ui.text import details_text  # noqa: E402


class DetailsDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window | None, result) -> None:
        super().__init__(title=f"repotray — {result.name}", transient_for=parent, modal=False)
        self.set_default_size(640, 360)
        self.set_skip_taskbar_hint(True)
        self.set_keep_above(True)
        self.text = details_text(result)
        view = Gtk.TextView(editable=False, monospace=True, cursor_visible=False)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        view.get_buffer().set_text(self.text)
        view.set_left_margin(8)
        view.set_top_margin(8)
        sw = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        sw.add(view)
        self.get_content_area().pack_start(sw, True, True, 0)
        copy = self.add_button("Copy", 1)
        copy.connect("clicked", self._copy)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.connect("response", self._response)
        self.show_all()

    def _copy(self, *_):
        cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        cb.set_text(self.text, -1)
        cb.store()

    def _response(self, _dialog, response):
        if response != 1:
            self.destroy()
