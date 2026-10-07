"""Backend conformance suite. ``REPOTRAY_BACKEND`` selects the backend under test (default fake).

    REPOTRAY_BACKEND=xapp REPOTRAY_GUI_TESTS=1 pytest tests/conformance

Every backend must accept every IconSpec, labels, tooltips and nested menus; ``call_soon`` from
another thread must run on the UI thread; ``quit()`` must make ``run()`` return within 2 s.
"""

from __future__ import annotations

import os
import threading
import time

import pytest

from repotray.backends import registry
from repotray.core.config import Config, ConfigWatcher
from repotray.core.demo import DemoScheduler, demo_snapshot
from repotray.core.indicator import IconSpec
from repotray.core.model import MenuItem, control_menu, fallback_menu, panel_model
from repotray.icons.names import SYMBOLIC, TINTS
from repotray.platform import current

pytestmark = pytest.mark.conformance

NAME = (
    os.environ.get("REPOTRAY_CONFORMANCE_BACKEND") or os.environ.get("REPOTRAY_BACKEND") or "fake"
)
NEEDS_DISPLAY = NAME not in ("fake",)


class StubController:
    def __init__(self, tmp_path):
        self.config = Config()
        self.scheduler = DemoScheduler(ConfigWatcher(tmp_path / "c.toml"))
        self.dispatched = []

    def dispatch(self, action, path=None):
        self.dispatched.append((action, path))

    def fetch_all(self):
        self.dispatched.append(("fetch_all", None))

    def panel_opened(self):
        pass

    def panel_closed(self):
        pass

    def refresh(self):
        pass


@pytest.fixture
def backend(tmp_path):
    if NEEDS_DISPLAY and os.environ.get("REPOTRAY_GUI_TESTS") != "1":
        pytest.skip("set REPOTRAY_GUI_TESTS=1 to test a real backend")
    try:
        cls = registry.load(NAME)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"backend {NAME} unavailable: {exc}")
    probe = cls.probe(current())
    if NAME != "fake" and probe.score <= 0:
        pytest.skip(f"backend {NAME} not usable here: {probe.reason}")
    b = cls(current(), StubController(tmp_path))
    yield b
    panel = getattr(b, "panel", None)
    if panel is not None:
        panel.hide()
    icon = getattr(b, "icon", None) or getattr(b, "indicator", None)
    if icon is not None and hasattr(icon, "set_visible"):
        icon.set_visible(False)
    _flush()
    # libxapp crashes when a StatusIcon is finalised while its D-Bus registration is pending;
    # the tray never disposes its icon, so tests keep every backend alive too.
    _KEEP.append(b)


_KEEP: list = []


def _flush() -> None:
    if NAME == "fake":
        return
    from gi.repository import GLib

    ctx = GLib.MainContext.default()
    deadline = time.monotonic() + 0.3
    while time.monotonic() < deadline:
        while ctx.pending():
            ctx.iteration(False)
        time.sleep(0.02)


def all_specs():
    specs = [IconSpec(), IconSpec("error"), IconSpec("paused")]
    for tint in (None, *TINTS):
        for top in (None, *SYMBOLIC):
            for bottom in (None, *SYMBOLIC):
                if tint or top or bottom:
                    specs.append(IconSpec("attention", top, bottom, tint))
    specs.append(IconSpec("attention", "#ff0000", None, None, "#dddddd"))
    return specs


def test_capabilities_declared(backend):
    keys = {"tooltip", "tooltip_markup", "tooltip_max_chars", "label", "panel", "two_menus",
            "notifications", "anchor"}  # fmt: skip
    assert set(backend.caps) == keys
    assert isinstance(backend.name, str)


def test_every_icon_spec(backend):
    for spec in all_specs():
        backend.set_icon(spec)


def test_label_and_tooltip(backend):
    backend.set_label("↑3 ↓1 ✎2")
    backend.set_label("")
    snap = demo_snapshot()
    from repotray.core.tooltip import tooltip_text

    t = tooltip_text(
        snap,
        Config(),
        time.time(),
        markup=backend.caps["tooltip_markup"],
        max_chars=backend.caps["tooltip_max_chars"],
    )
    backend.set_tooltip(t)
    if backend.caps["tooltip_max_chars"]:
        assert len(t) <= backend.caps["tooltip_max_chars"]


def test_nested_menus_and_panel(backend):
    snap = demo_snapshot()
    now = time.time()
    fb = list(fallback_menu(snap, Config(), now, open_panel=True))
    assert any(i.children for i in fb)
    deep = MenuItem("Level 1", None, children=(MenuItem("Level 2", None, children=(
        MenuItem("Leaf", "about"),)),))  # fmt: skip
    backend.set_menus(list(control_menu(snap)), [*fb, deep])
    backend.set_menus(list(control_menu(snap)), None)
    backend.show_panel_model(panel_model(snap, Config(), now))


def _run_in_thread(backend):
    if NAME == "fake":
        t = threading.Thread(target=backend.run, daemon=True)
        t.start()
        return t, t
    return None, threading.main_thread()


def test_call_soon_runs_on_ui_thread_and_quit_returns(backend):
    seen = []
    done = threading.Event()
    t, ui_thread = _run_in_thread(backend)

    def from_worker():
        backend.call_soon(lambda: (seen.append(threading.current_thread()), done.set()))

    threading.Thread(target=from_worker).start()
    if t is None:  # GTK backends: the main loop runs on this (main) thread
        threading.Timer(1.0, lambda: backend.quit()).start()
        start = time.monotonic()
        backend.run()
        assert time.monotonic() - start < 3
    else:
        assert done.wait(2)
        start = time.monotonic()
        backend.quit()
        t.join(2)
        assert not t.is_alive() and time.monotonic() - start < 2
    # A backend may run callbacks on its own UI thread (pystray: a queue worker).
    ui_thread = getattr(backend, "ui_thread", None) or ui_thread
    assert seen and seen[0] is ui_thread


def test_registry_lists_backend():
    assert NAME in registry.available()
