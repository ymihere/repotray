"""The Platform protocol and helpers shared by the implementations."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Protocol, runtime_checkable

from repotray.core.gitrun import default_kill_tree, default_popen_kwargs


class InstanceLock:
    """A held single-instance lock. ``release()`` frees it; the OS frees it on exit anyway."""

    def __init__(self, path: Path, handle, release_fn) -> None:
        self.path = path
        self._handle = handle
        self._release = release_fn

    def release(self) -> None:
        if self._handle is not None:
            self._release(self._handle)
            self._handle = None


@runtime_checkable
class Platform(Protocol):
    name: str

    def config_dir(self) -> Path: ...
    def state_dir(self) -> Path: ...
    def cache_dir(self) -> Path: ...
    def runtime_dir(self) -> Path: ...
    def git_env(self) -> dict[str, str]: ...
    def popen_kwargs(self) -> dict: ...
    def kill_tree(self, proc: subprocess.Popen) -> None: ...
    def acquire_instance_lock(self, path: Path) -> InstanceLock | None: ...
    def read_lock_pid(self, path: Path) -> int | None: ...
    def open_terminal(self, path: Path, template: str) -> None: ...
    def open_folder(self, path: Path, template: str) -> None: ...
    def open_file(self, path: Path) -> None: ...
    def notify(self, title: str, body: str) -> bool: ...
    def autostart_enable(self, argv: list[str]) -> str: ...
    def autostart_disable(self) -> None: ...
    def autostart_enabled(self) -> bool: ...
    def install_icons(self, src: Path) -> list[Path]: ...
    def uninstall_icons(self) -> list[Path]: ...
    def icons_installed(self) -> str: ...
    def desktop_info(self) -> dict[str, str]: ...
    def prefers_dark_panel(self) -> bool | None: ...


def split_template(template: str, path: Path, posix: bool = True) -> list[str]:
    """Split a command template, then substitute {path} inside each argument (no shell)."""
    parts = shlex.split(template) if posix else template.split()
    return [p.replace("{path}", str(path)) for p in parts]


def spawn(argv: list[str], cwd: Path | None = None) -> None:
    """Start a detached GUI helper; never wait for it."""
    kwargs = default_popen_kwargs()
    subprocess.Popen(
        argv,
        cwd=str(cwd) if cwd else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        **kwargs,
    )


class BasePlatform:
    """Defaults shared by every platform; subclasses override what differs."""

    name = "generic"
    app = "repotray"

    def git_env(self) -> dict[str, str]:
        return {}

    def popen_kwargs(self) -> dict:
        return default_popen_kwargs()

    def kill_tree(self, proc: subprocess.Popen) -> None:
        default_kill_tree(proc)

    def runtime_dir(self) -> Path:
        return self.state_dir()

    def lock_path(self) -> Path:
        return self.runtime_dir() / "repotray.lock"

    def config_path(self) -> Path:
        return self.config_dir() / "config.toml"

    def log_path(self) -> Path:
        return self.state_dir() / "repotray.log"

    def install_icons(self, src: Path) -> list[Path]:
        return []

    def uninstall_icons(self) -> list[Path]:
        return []

    def icons_installed(self) -> str:
        return "not needed on this platform"

    def prefers_dark_panel(self) -> bool | None:
        return None

    def read_lock_pid(self, path: Path) -> int | None:
        try:
            text = path.read_text("utf-8").strip()
        except OSError:
            return None
        return int(text) if text.isdigit() else None

    def desktop_info(self) -> dict[str, str]:
        return {"platform": self.name}


def env_path(var: str, default: Path) -> Path:
    v = os.environ.get(var)
    return Path(v) if v and os.path.isabs(v) else default
