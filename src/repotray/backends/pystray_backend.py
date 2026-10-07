"""macOS / Windows (and a Linux fallback) via pystray. Experimental: icon, tooltip and one menu.

pystray cannot host a popup window, so the panel is rendered as a menu (SPEC §2.3). Icons are
Pillow images drawn from the same geometry as the SVGs. ``call_soon`` enqueues; a worker thread
applies updates under a lock and refreshes the menu.
"""

from __future__ import annotations

import contextlib
import logging
import queue
import sys
import threading
from collections.abc import Callable
from typing import ClassVar

from repotray.backends.base import ProbeResult, caps

log = logging.getLogger(__name__)

ICON_PX = 64


class PystrayBackend:
    name: ClassVar[str] = "pystray"
    caps = caps(
        tooltip=True,
        tooltip_max_chars=127 if sys.platform == "win32" else None,
        notifications=True,
    )

    @classmethod
    def probe(cls, platform) -> ProbeResult:
        import PIL  # noqa: F401
        import pystray  # noqa: F401

        if getattr(platform, "name", "") in ("macos", "windows"):
            return ProbeResult(50, "pystray available (experimental)")
        return ProbeResult(10, "pystray available; native Linux backends are preferred")

    def __init__(self, platform, controller) -> None:
        import pystray

        self.pystray = pystray
        self.platform = platform
        self.controller = controller
        self.caps = dict(type(self).caps)
        self.caps["notifications"] = bool(getattr(pystray.Icon, "HAS_NOTIFICATION", False))
        self._q: queue.Queue[Callable[[], None] | None] = queue.Queue()
        self._lock = threading.Lock()
        self._items: list = []
        self._spec = None
        self.ui_thread: threading.Thread | None = None
        self.icon = pystray.Icon(
            "repotray", self._image(None), "repotray", menu=pystray.Menu(lambda: self._menu_items())
        )

    # --- rendering ---
    def _glyph_color(self) -> str:
        try:
            dark = self.platform.prefers_dark_panel()
        except Exception:  # noqa: BLE001
            dark = None
        if dark is None:
            dark = sys.platform != "darwin"  # Windows' default taskbar is dark
        return "#e1e1e1" if dark else "#1e1e1e"

    def _image(self, spec):
        from repotray.core.indicator import IconSpec
        from repotray.icons.raster import render

        return render(spec or IconSpec(), ICON_PX, glyph_color=self._glyph_color())

    def _menu_items(self):
        with self._lock:
            return tuple(self._convert(i) for i in self._items)

    def _convert(self, item):
        ps = self.pystray
        if item.separator:
            return ps.Menu.SEPARATOR
        if item.children:
            return ps.MenuItem(item.label, ps.Menu(*[self._convert(c) for c in item.children]))
        action, path = item.action, item.path

        def on_click(_icon, _item):
            if action:
                self.call_soon(lambda: self.controller.dispatch(action, path))

        checked = (lambda _i, v=bool(item.checked): v) if item.checked is not None else None
        return ps.MenuItem(
            item.label, on_click, checked=checked, enabled=item.enabled and action is not None
        )

    # --- TrayBackend ---
    def set_icon(self, spec) -> None:
        if spec != self._spec:
            self._spec = spec
            self.icon.icon = self._image(spec)

    def set_label(self, text: str) -> None:
        pass

    def set_tooltip(self, text: str) -> None:
        self.icon.title = text

    def set_menus(self, control, fallback) -> None:
        with self._lock:
            self._items = list(fallback if fallback is not None else control)
        with contextlib.suppress(Exception):  # not running yet
            self.icon.update_menu()

    def show_panel_model(self, model) -> None:
        pass

    def notify(self, title: str, body: str) -> None:
        if self.caps["notifications"]:
            try:
                self.icon.notify(body or title, title if body else "repotray")
                return
            except Exception:  # noqa: BLE001
                log.exception("pystray notify failed")
        self.platform.notify(title, body)

    def copy_to_clipboard(self, text: str) -> None:
        import subprocess

        cmd = {"darwin": ["pbcopy"], "win32": ["clip"]}.get(sys.platform, ["xclip", "-sel", "clip"])
        try:
            subprocess.run(cmd, input=text.encode(), check=False, timeout=5)
        except OSError:
            log.warning("no clipboard tool available")

    def call_soon(self, fn: Callable[[], None]) -> None:
        self._q.put(fn)

    def _worker(self) -> None:
        self.ui_thread = threading.current_thread()
        while True:
            fn = self._q.get()
            if fn is None:
                return
            try:
                fn()
            except Exception:  # noqa: BLE001
                log.exception("UI callback failed")

    def run(self) -> None:
        worker = threading.Thread(target=self._worker, name="repotray-ui", daemon=True)
        self.ui_thread = worker
        worker.start()

        def setup(icon):
            icon.visible = True

        self.icon.run(setup)
        self._q.put(None)
        worker.join(2)

    def quit(self) -> None:
        self.icon.stop()
