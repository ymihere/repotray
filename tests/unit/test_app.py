"""Controller behaviour with the fake backend and the demo scheduler."""

import threading
import time

from repotray.app import Controller
from repotray.backends.base import caps
from repotray.backends.fake import FakeBackend
from repotray.core.config import ConfigWatcher
from repotray.core.demo import DemoScheduler


class StubPlatform:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.opened = []
        self.notes = []

    def cache_dir(self):
        return self.tmp / "cache"

    def open_file(self, path, template=""):
        self.opened.append((path, template))

    def notify(self, title, body):
        self.notes.append((title, body))
        return True

    def autostart_enabled(self):
        return False


def make(tmp_path, backend_caps=None, config=""):
    cfg = tmp_path / "c.toml"
    cfg.write_text(config)
    sched = DemoScheduler(ConfigWatcher(cfg))
    sched.watcher.load()
    plat = StubPlatform(tmp_path)

    def factory(platform, controller):
        return FakeBackend(platform, controller, backend_caps)

    ctl = Controller(plat, sched, factory, demo=True)
    ctl.render()
    return ctl, plat


def run_ui(ctl, until, timeout=3.0):
    t = threading.Thread(target=ctl.backend.run, daemon=True)
    t.start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not until():
        time.sleep(0.02)
    ctl.backend.quit()
    t.join(2)
    return until()


def website(ctl):
    return next(s for s in ctl.snapshot.repos if s.name == "website")


def test_incoming_without_dialog_opens_editor(tmp_path):
    ctl, plat = make(tmp_path, caps(tooltip=True), config='editor = "xed {path}"\n')
    ctl.dispatch("show_incoming", website(ctl).path)
    assert run_ui(ctl, lambda: plat.opened)
    path, template = plat.opened[0]
    assert template == "xed {path}" and path.name == "incoming-website.txt"
    text = path.read_text("utf-8")
    assert text.startswith("website (origin/main → main): 4 incoming commits")
    assert text.count("\ncommit ") + text.startswith("commit ") >= 3


def test_incoming_with_dialog_backend(tmp_path):
    shown = []

    class DialogBackend(FakeBackend):
        def show_commits(self, title, subtitle, log, on_open_editor, action=None, on_action=None):
            shown.append((title, subtitle, log, on_open_editor, action, on_action))

    cfg = tmp_path / "c.toml"
    cfg.write_text("")
    sched = DemoScheduler(ConfigWatcher(cfg))
    plat = StubPlatform(tmp_path)
    ctl = Controller(plat, sched, lambda p, c: DialogBackend(p, c), demo=True)
    ctl.render()
    ctl.dispatch("show_incoming", website(ctl).path)
    assert run_ui(ctl, lambda: shown)
    title, subtitle, log, open_editor, action, on_action = shown[0]
    assert title == "website: 4 incoming commits"
    assert subtitle == "origin/main → main, as of the last fetch"
    assert log.total == 4 and len(log.commits) == 4
    assert action.action.value == "pull" and action.enabled
    assert action.tooltip == "Pull 4 commits from origin/main (fast-forward)"
    open_editor()
    assert plat.opened and plat.opened[0][1] == ""  # no editor configured: desktop default


def test_incoming_action_is_sync_when_diverged(tmp_path):
    ctl, _ = make(tmp_path)
    by = {s.name: s for s in ctl.snapshot.repos}
    assert ctl.incoming_action(by["website"].path).action.value == "pull"
    sync = ctl.incoming_action(by["design-system"].path)
    assert sync.action.value == "sync" and sync.enabled
    assert ctl.incoming_action(by["api-gateway"].path) is None  # nothing to pull


def test_open_config_uses_editor_setting(tmp_path):
    ctl, plat = make(tmp_path, config='editor = "gedit {path}"\n')
    ctl.dispatch("open_config")
    assert plat.opened == [(tmp_path / "c.toml", "gedit {path}")]
