"""The Controller: the only API a UI calls. Wires scheduler, presentation models and backend.

Headless: no toolkit imports here. Scheduler callbacks arrive on worker threads and are marshalled
to the UI thread through ``backend.call_soon``.
"""

from __future__ import annotations

import logging
import logging.handlers
import signal
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

from repotray import __version__
from repotray.core import config as cfgmod
from repotray.core.actions import BULK_NAMES
from repotray.core.indicator import icon_spec, label_text
from repotray.core.model import (
    UiState,
    control_menu,
    fallback_menu,
    panel_model,
    result_end,
    result_text,
)
from repotray.core.tooltip import tooltip_text
from repotray.core.types import ActionKind, ActionResult, RepoState, Snapshot

log = logging.getLogger("repotray")

PROJECT_URL = "https://github.com/ymihere/repotray"
NOTIFY_RATE = 3600.0
ICON_RELOAD_DELAY = 6.0


def about_info() -> dict[str, str]:
    return {
        "name": "repotray",
        "version": __version__,
        "comments": "Shows which of your local git clones have work to push or pull.",
        "website": PROJECT_URL,
        "license": "MIT",
        "copyright": "© 2026 Andreas Bonelli",
        "credits": "Tray icon: Octicons “repo” (MIT licence, © GitHub Inc.)",
    }


class Controller:
    def __init__(self, platform, scheduler, backend_factory, *, demo: bool = False) -> None:
        self.platform = platform
        self.scheduler = scheduler
        self.demo = demo
        self.ui = UiState(autostart=self._autostart_state())
        self.snapshot: Snapshot = scheduler.snapshot()
        self.panel_visible = False
        self._prev: dict[Path, RepoState] = {}
        self._notified: dict[tuple[Path, str], float] = {}
        self._quitting = False
        self.backend = backend_factory(platform, self)
        scheduler.on_snapshot(self._on_snapshot)
        scheduler.on_result(self._on_result)

    @property
    def config(self) -> cfgmod.Config:
        return self.scheduler.config

    def _autostart_state(self) -> bool:
        try:
            return self.platform.autostart_enabled()
        except Exception:  # noqa: BLE001
            return False

    # --- snapshot → UI -----------------------------------------------------------------------

    def _on_snapshot(self, snap: Snapshot) -> None:
        self.backend.call_soon(lambda: self.render(snap))

    def render(self, snap: Snapshot | None = None) -> None:
        """Push icon, label, tooltip, menus and panel model to the backend (UI thread)."""
        if snap is not None:
            self._maybe_notify(snap)
            self.snapshot = snap
        snap = self.snapshot
        cfg = self.config
        now = time.time()
        caps = self.backend.caps
        self.backend.set_icon(icon_spec(snap, cfg))
        if caps["label"]:
            self.backend.set_label(label_text(snap, cfg))
        if caps["tooltip"]:
            self.backend.set_tooltip(
                tooltip_text(
                    snap,
                    cfg,
                    now,
                    markup=caps["tooltip_markup"],
                    max_chars=caps["tooltip_max_chars"],
                )
            )
        fallback = None
        if not caps["panel"] or getattr(self.backend, "wants_fallback_menu", False):
            fallback = list(
                fallback_menu(
                    snap, cfg, now, self.ui, open_panel=getattr(self.backend, "has_panel", False)
                )
            )
        self.backend.set_menus(list(control_menu(snap, self.ui)), fallback)
        if caps["panel"]:
            self.backend.show_panel_model(panel_model(snap, cfg, now, self.ui))

    def refresh(self) -> None:
        """Re-render from the last snapshot (relative times, banner expiry)."""
        self.render()

    # --- notifications -----------------------------------------------------------------------

    def _rate_ok(self, path: Path, kind: str, now: float) -> bool:
        last = self._notified.get((path, kind))
        if last is not None and now - last < NOTIFY_RATE:
            return False
        self._notified[(path, kind)] = now
        return True

    def _maybe_notify(self, snap: Snapshot) -> None:
        prev, self._prev = self._prev, {s.path: s for s in snap.repos}
        if not self.config.notifications or not prev:
            return
        now = time.time()
        for s in snap.repos:
            p = prev.get(s.path)
            if p is None:
                continue
            if s.behind > 0 and p.behind == 0 and self._rate_ok(s.path, "behind", now):
                n = s.behind
                title = f"{s.name}: {n} new commit{'s' if n != 1 else ''} to pull"
                self.notify(title, s.upstream or "")
            if (
                s.fetch_error
                and not p.fetch_error
                and p.fetched_at is not None
                and self._rate_ok(s.path, "fetch", now)
            ):
                self.notify(f"Fetch failed: {s.name}", s.fetch_error)

    def _on_result(self, res: ActionResult) -> None:
        # Individual results of a running Push/Pull/Sync all are summarised by its final result.
        if res.name not in BULK_NAMES.values() and getattr(self.scheduler, "bulk_progress", None):
            return
        self.backend.call_soon(lambda: self._report(res))

    def _report(self, res: ActionResult) -> None:
        if self.panel_visible and self.backend.caps["panel"]:
            return  # the panel shows it (banner + row marker)
        title = ("✓ " if res.ok else "⚠ ") + result_text(res)
        body = "" if res.ok or res.name in BULK_NAMES.values() else "Open the panel for details"
        self.notify(title, body)

    def notify(self, title: str, body: str) -> None:
        if self.backend.caps["notifications"]:
            self.backend.notify(title, body)
        else:
            try:
                self.platform.notify(title, body)
            except Exception:  # noqa: BLE001
                log.exception("notification failed")

    # --- commands (UI thread) ----------------------------------------------------------------

    def dispatch(self, action: str, path: Path | None = None) -> None:
        handlers = {
            "fetch_all": lambda: self.fetch_all(),
            "toggle_pause": lambda: self.set_paused(not self._paused()),
            "rescan": lambda: self.rescan(),
            "open_config": lambda: self.open_config(),
            "toggle_autostart": lambda: self.set_autostart(not self.autostart_enabled()),
            "about": lambda: self.about(),
            "quit": lambda: self.quit(),
            "sync_all": lambda: self.sync_all(),
            "push_all": lambda: self.push_all(),
            "pull_all": lambda: self.pull_all(),
            "ack_banner": lambda: self.acknowledge_banner(),
            "open_panel": lambda: getattr(self.backend, "open_panel", lambda: None)(),
            "push": lambda: self.push(path),
            "pull": lambda: self.pull(path),
            "sync": lambda: self.sync(path),
            "fetch": lambda: self.fetch(path),
            "open_terminal": lambda: self.open_terminal(path),
            "open_folder": lambda: self.open_folder(path),
            "copy_path": lambda: self.copy_path(path),
            "show_incoming": lambda: self.show_incoming(path),
        }
        fn = handlers.get(action)
        if fn is None:
            log.warning("unknown action %r", action)
            return
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - never crash the tray from a click
            log.exception("action %s failed", action)
            self.notify("repotray", f"{action} failed: {exc}")

    def _paused(self) -> bool:
        return self.snapshot.fetch_mode.value == "paused"

    def fetch_all(self) -> None:
        self.scheduler.fetch_now()

    def fetch(self, path: Path) -> None:
        self.scheduler.fetch_now(path)

    def push(self, path: Path) -> None:
        self.scheduler.run_action(ActionKind.PUSH, path)

    def pull(self, path: Path) -> None:
        self.scheduler.run_action(ActionKind.PULL, path)

    def sync(self, path: Path) -> None:
        self.scheduler.run_action(ActionKind.SYNC, path)

    def sync_all(self) -> None:
        self.scheduler.sync_all()

    def push_all(self) -> None:
        self.scheduler.push_all()

    def pull_all(self) -> None:
        self.scheduler.pull_all()

    def set_paused(self, paused: bool) -> None:
        self.scheduler.pause_fetching(paused)

    def rescan(self) -> None:
        self.scheduler.rescan_now()

    def config_file(self) -> Path:
        return self.scheduler.watcher.path

    def open_config(self) -> None:
        path = self.config_file()
        cfgmod.ensure_exists(path)
        self.platform.open_file(path, self.config.editor)

    def _check_repo(self, path: Path) -> None:
        if not path.is_dir():
            suffix = " (demo repository)" if self.demo else ""
            raise RuntimeError(f"{path} does not exist{suffix}")

    def open_terminal(self, path: Path) -> None:
        self._check_repo(path)
        self.platform.open_terminal(path, self.config.terminal)

    def open_folder(self, path: Path) -> None:
        self._check_repo(path)
        self.platform.open_folder(path, self.config.file_manager)

    def _repo(self, path: Path):
        return next((s for s in self.snapshot.repos if s.path == path), None)

    def show_incoming(self, path: Path) -> None:
        """Show the commits a pull would bring; read off the UI thread, shown on it."""
        st = self._repo(path)
        name = st.name if st else path.name

        def work() -> None:
            log = self.scheduler.incoming(path)
            self.backend.call_soon(lambda: self._present_incoming(path, name, st, log))

        threading.Thread(target=work, name="repotray-log", daemon=True).start()

    def _present_incoming(self, path: Path, name: str, st, log) -> None:
        if log.error:
            self.notify(f"{name}: cannot list incoming commits", log.error)
            return
        show = getattr(self.backend, "show_commits", None)
        if show is None:
            self.open_incoming_in_editor(name, st, log)
            return
        title = f"{name}: {log.total} incoming commit{'s' if log.total != 1 else ''}"
        if st is not None and st.branch and st.upstream:
            subtitle = f"{st.upstream} → {st.branch}, as of the last fetch"
        else:
            subtitle = "as of the last fetch"
        show(title, subtitle, log, lambda: self.open_incoming_in_editor(name, st, log))

    def open_incoming_in_editor(self, name: str, st, log) -> Path:
        """Write the full log to a text file and open it in the editor (config `editor`)."""
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
        out = self.platform.cache_dir() / f"incoming-{safe}.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        where = f" ({st.upstream} → {st.branch})" if st is not None and st.upstream else ""
        header = f"{name}{where}: {log.total} incoming commit{'s' if log.total != 1 else ''}"
        out.write_text(f"{header}\n{'=' * len(header)}\n\n{log.text}", "utf-8")
        self.platform.open_file(out, self.config.editor)
        return out

    def copy_path(self, path: Path) -> None:
        self.backend.copy_to_clipboard(str(path))

    def autostart_enabled(self) -> bool:
        return self._autostart_state()

    def set_autostart(self, enabled: bool) -> None:
        from repotray.cli import tray_argv

        if enabled:
            self.platform.autostart_enable(tray_argv())
        else:
            self.platform.autostart_disable()
        self.ui = replace(self.ui, autostart=self._autostart_state())
        self.render()

    def about(self) -> None:
        show = getattr(self.backend, "show_about", None)
        info = about_info()
        if show:
            show(info)
        else:
            self.notify(f"repotray {info['version']}", f"{info['website']}\n{info['credits']}")

    def acknowledge_banner(self) -> None:
        ends = [result_end(r) for r in self.snapshot.recent_results]
        self.ui = replace(self.ui, banner_ack=max([time.time(), *ends]))
        self.render()

    def panel_opened(self) -> None:
        self.panel_visible = True
        self.render()

    def panel_closed(self) -> None:
        self.panel_visible = False
        self.acknowledge_banner()  # failures persist until the panel is closed

    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        threading.Thread(target=self.scheduler.stop, daemon=True).start()
        self.backend.quit()


# --- tray startup ---------------------------------------------------------------------------------


def setup_logging(platform, level: str, verbose: bool) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        log_path = platform.log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError as exc:
        print(f"repotray: cannot write log file: {exc}", file=sys.stderr)
    if verbose:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        root.addHandler(sh)
    root.setLevel(logging.DEBUG if verbose else getattr(logging, level.upper(), logging.INFO))


def _excepthook(exc_type, exc, tb) -> None:
    log.error("unhandled exception", exc_info=(exc_type, exc, tb))


def run_tray(
    config_file: Path,
    demo: bool = False,
    backend: str | None = None,
    verbose: bool = False,
    platform=None,
) -> int:
    from repotray.backends import registry
    from repotray.core.config import ConfigWatcher
    from repotray.core.gitrun import GitRunner
    from repotray.icons import symbolic_dir
    from repotray.platform import current

    platform = platform or current()
    lock = platform.acquire_instance_lock(platform.lock_path())
    if lock is None:
        pid = platform.read_lock_pid(platform.lock_path())
        print(f"repotray is already running (pid {pid})", file=sys.stderr)
        return 0
    try:
        if not demo:
            try:
                cfgmod.ensure_exists(config_file)
            except OSError as exc:
                print(f"repotray: cannot write {config_file}: {exc}", file=sys.stderr)
        watcher = ConfigWatcher(config_file)
        cfg = watcher.load()
        setup_logging(platform, cfg.log_level, verbose)
        sys.excepthook = _excepthook
        threading.excepthook = lambda a: log.error(
            "unhandled exception in %s",
            a.thread,
            exc_info=(a.exc_type, a.exc_value, a.exc_traceback),
        )
        copied: list = []
        try:
            copied = platform.install_icons(symbolic_dir())
        except OSError as exc:
            log.warning("installing icons failed: %s", exc)
        try:
            name, backend_cls = registry.select(platform, cfg.backend, backend)
        except registry.BackendError as exc:
            print(f"repotray: {exc}", file=sys.stderr)
            return 1
        log.info("repotray %s starting, backend %s%s", __version__, name, " (demo)" if demo else "")
        if demo:
            from repotray.core.demo import DemoScheduler

            scheduler = DemoScheduler(watcher)
        else:
            from repotray.core.scheduler import Scheduler

            runner = GitRunner(
                extra_env=platform.git_env(),
                popen_kwargs=platform.popen_kwargs,
                kill_tree=platform.kill_tree,
            )
            scheduler = Scheduler(watcher, runner)
        controller = Controller(platform, scheduler, backend_cls, demo=demo)
        be = controller.backend
        install = getattr(be, "install_signal_handlers", None)
        if install:
            install(controller.quit)
        else:
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, lambda *_: be.call_soon(controller.quit))
        controller.render()
        reload_icon = getattr(be, "reload_icon", None)
        if copied and reload_icon:
            # The panel may look up a just-installed icon before its icon theme has rescanned
            # (GTK rescans at most every few seconds) and show nothing; set it again later.
            timer = threading.Timer(ICON_RELOAD_DELAY, lambda: be.call_soon(reload_icon))
            timer.daemon = True
            timer.start()
        scheduler.start()
        be.run()
        scheduler.stop()
        log.info("repotray stopped")
        return 0
    finally:
        lock.release()  # the file stays: unlinking it could race a starting instance
