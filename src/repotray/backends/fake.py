"""A headless backend that records every call. For tests, conformance runs and `--backend fake`."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import ClassVar

from repotray.backends.base import Capabilities, ProbeResult, caps


class FakeBackend:
    name: ClassVar[str] = "fake"

    def __init__(self, platform=None, controller=None, capabilities: Capabilities | None = None):
        self.platform = platform
        self.controller = controller
        self.caps = capabilities or caps(
            tooltip=True,
            tooltip_markup=True,
            label=True,
            panel=True,
            two_menus=True,
            notifications=True,
            anchor=True,
        )
        self.calls: list[tuple[str, object]] = []
        self.icon = None
        self.label = ""
        self.tooltip = ""
        self.control_menu: list = []
        self.fallback_menu: list | None = None
        self.panel_model = None
        self.notifications: list[tuple[str, str]] = []
        self.clipboard = ""
        self.ui_thread: threading.Thread | None = None
        self._q: queue.Queue[Callable[[], None] | None] = queue.Queue()
        self._running = threading.Event()

    @classmethod
    def probe(cls, platform) -> ProbeResult:
        return ProbeResult(1, "test backend")

    def _rec(self, name: str, value: object) -> None:
        self.calls.append((name, value))

    def set_icon(self, icon) -> None:
        self.icon = icon
        self._rec("icon", icon)

    def set_label(self, text: str) -> None:
        self.label = text
        self._rec("label", text)

    def set_tooltip(self, text: str) -> None:
        self.tooltip = text
        self._rec("tooltip", text)

    def set_menus(self, control, fallback) -> None:
        self.control_menu = list(control)
        self.fallback_menu = list(fallback) if fallback is not None else None
        self._rec("menus", (control, fallback))

    def show_panel_model(self, model) -> None:
        if self.caps["panel"]:
            self.panel_model = model
            self._rec("panel", model)

    def notify(self, title: str, body: str) -> None:
        self.notifications.append((title, body))
        self._rec("notify", (title, body))

    def copy_to_clipboard(self, text: str) -> None:
        self.clipboard = text
        self._rec("clipboard", text)

    def call_soon(self, fn: Callable[[], None]) -> None:
        self._q.put(fn)

    def run(self) -> None:
        self.ui_thread = threading.current_thread()
        self._running.set()
        while True:
            fn = self._q.get()
            if fn is None:
                break
            try:
                fn()
            except Exception:  # noqa: BLE001 - a callback must never kill the loop
                import logging

                logging.getLogger(__name__).exception("callback failed")
        self._running.clear()

    def quit(self) -> None:
        self._q.put(None)

    # test helpers
    def drain(self) -> None:
        """Run queued callbacks on the calling thread (when run() is not used)."""
        while True:
            try:
                fn = self._q.get_nowait()
            except queue.Empty:
                return
            if fn is None:
                return
            fn()
