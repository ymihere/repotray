"""Dialog listing the commits a pull would bring, with a button to open them in an editor."""

from __future__ import annotations

import time
from collections.abc import Callable

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Pango  # noqa: E402

from repotray.core.model import ACTION_ICONS, ago  # noqa: E402
from repotray.ui.text import (  # noqa: E402
    ACTION_LABELS,
    NO_INCOMING_TEXT,
    blocked_text,
    commit_epoch,
    more_commits_text,
)

EDITOR_RESPONSE = 1
ACTION_RESPONSE = 2


class CommitsDialog(Gtk.Dialog):
    def __init__(
        self,
        parent: Gtk.Window | None,
        title: str,
        subtitle: str,
        log,
        on_open_editor: Callable[[], None],
        action=None,
        on_action: Callable[[], None] | None = None,
    ) -> None:
        """``action`` is the model's Button for Pull (or Sync); None = no such button."""
        super().__init__(title=f"repotray — {title}", transient_for=parent, modal=False)
        self.set_default_size(640, 460)
        self.set_skip_taskbar_hint(True)
        self.set_keep_above(True)
        self.on_open_editor = on_open_editor

        area = self.get_content_area()
        area.set_spacing(6)
        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        head.set_margin_start(12)
        head.set_margin_end(12)
        head.set_margin_top(10)
        heading = Gtk.Label(label=title, xalign=0.0)
        heading.get_style_context().add_class("rt-header")
        heading.set_attributes(_bold())
        sub = Gtk.Label(label=subtitle, xalign=0.0)
        sub.get_style_context().add_class("dim-label")
        head.pack_start(heading, False, False, 0)
        head.pack_start(sub, False, False, 0)
        area.pack_start(head, False, False, 0)

        self.view = Gtk.TextView(editable=False, cursor_visible=False)
        self.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        for side in ("left", "right", "top", "bottom"):
            getattr(self.view, f"set_{side}_margin")(12)
        self._fill(log)
        sw = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        sw.add(self.view)
        area.pack_start(sw, True, True, 0)

        self.on_action = on_action
        self.add_button("Open in editor", EDITOR_RESPONSE)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.set_default_response(Gtk.ResponseType.CLOSE)
        self.action_button = None
        if action is not None and on_action is not None:
            label = ACTION_LABELS[action.action.value]
            b = self.add_button(label, ACTION_RESPONSE)
            icon = ACTION_ICONS[action.action]
            b.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
            b.set_always_show_image(True)
            b.get_style_context().add_class("suggested-action")
            b.set_sensitive(action.enabled)
            b.set_tooltip_text(action.tooltip)
            self.action_button = b
            if action.enabled:
                self.set_default_response(ACTION_RESPONSE)
            else:
                # Insensitive buttons may not show tooltips: say why in the dialog itself.
                reason = Gtk.Label(label=blocked_text(label, action.tooltip))
                reason.set_xalign(0.0)
                reason.set_line_wrap(True)
                reason.get_style_context().add_class("dim-label")
                head.pack_start(reason, False, False, 4)
                reason.show()
        self.connect("response", self._response)
        self.show_all()

    def _fill(self, log) -> None:
        buf = self.view.get_buffer()
        bold = buf.create_tag("subject", weight=Pango.Weight.BOLD)
        dim_color = self.view.get_style_context().get_color(Gtk.StateFlags.NORMAL)
        dim_color.alpha = 0.6  # the theme's text colour, dimmed: no hard-coded colours
        dim = buf.create_tag("meta", scale=0.9, style=Pango.Style.ITALIC, foreground_rgba=dim_color)
        body = buf.create_tag("body", left_margin=24)
        mono = buf.create_tag("sha", family="monospace")
        now = time.time()
        it = buf.get_end_iter()
        if not log.commits:
            buf.insert(it, NO_INCOMING_TEXT)
            return
        for c in log.commits:
            buf.insert_with_tags(it, c.subject + "\n", bold)
            buf.insert_with_tags(it, c.sha[:8], dim, mono)
            when = commit_epoch(c.date)
            buf.insert_with_tags(it, f" · {c.author} · {ago(when, now)}\n", dim)
            if c.body:
                buf.insert_with_tags(it, c.body + "\n", body)
            buf.insert(it, "\n")
        if log.total > len(log.commits):
            buf.insert_with_tags(it, more_commits_text(log.total - len(log.commits)) + "\n", dim)

    def _response(self, _dialog, response) -> None:
        if response == EDITOR_RESPONSE:
            self.on_open_editor()
            return
        if response == ACTION_RESPONSE and self.on_action is not None:
            self.on_action()  # the panel shows progress and the result
        self.destroy()


def _bold():
    attrs = Pango.AttrList()
    attrs.insert(Pango.attr_weight_new(Pango.Weight.BOLD))
    return attrs
