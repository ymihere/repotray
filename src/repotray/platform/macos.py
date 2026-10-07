"""macOS. Written to the same standard as Linux, unit-tested with mocks; untested on real Macs."""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
from pathlib import Path

from repotray.platform.base import BasePlatform, InstanceLock, spawn, split_template

LAUNCH_AGENT_LABEL = "io.github.repotray"


def _applescript_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


class MacPlatform(BasePlatform):
    name = "macos"

    def __init__(self, which=shutil.which, run_spawn=spawn, home: Path | None = None) -> None:
        self.which = which
        self.spawn = run_spawn
        self.home = home or Path.home()

    def config_dir(self) -> Path:
        return self.home / "Library" / "Application Support" / self.app

    def state_dir(self) -> Path:
        return self.home / "Library" / "Logs" / self.app

    def cache_dir(self) -> Path:
        return self.home / "Library" / "Caches" / self.app

    def runtime_dir(self) -> Path:
        return self.config_dir()

    def launch_agent(self) -> Path:
        return self.home / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"

    def acquire_instance_lock(self, path: Path) -> InstanceLock | None:
        import fcntl

        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return None
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())

        def release(handle: int) -> None:
            fcntl.flock(handle, fcntl.LOCK_UN)
            os.close(handle)

        return InstanceLock(path, fd, release)

    def open_terminal(self, path: Path, template: str) -> None:
        argv = split_template(template, path) if template else ["open", "-a", "Terminal", str(path)]
        self.spawn(argv, cwd=path)

    def open_folder(self, path: Path, template: str) -> None:
        argv = split_template(template, path) if template else ["open", str(path)]
        self.spawn(argv, cwd=path)

    def open_file(self, path: Path) -> None:
        self.spawn(["open", "-t", str(path)])

    def notify_argv(self, title: str, body: str) -> list[str]:
        script = (
            f"display notification {_applescript_string(body)} "
            f"with title {_applescript_string(title)}"
        )
        return ["osascript", "-e", script]

    def notify(self, title: str, body: str) -> bool:
        self.spawn(self.notify_argv(title, body))
        return True

    def autostart_enable(self, argv: list[str]) -> str:
        f = self.launch_agent()
        f.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "Label": LAUNCH_AGENT_LABEL,
            "ProgramArguments": list(argv),
            "RunAtLoad": True,
            "ProcessType": "Interactive",
        }
        with f.open("wb") as fh:
            plistlib.dump(data, fh)
        return str(f)

    def autostart_disable(self) -> None:
        self.launch_agent().unlink(missing_ok=True)

    def autostart_enabled(self) -> bool:
        return self.launch_agent().exists()

    def desktop_info(self) -> dict[str, str]:
        info = {"platform": self.name}
        dark = self.prefers_dark_panel()
        info["menu bar"] = "dark" if dark else "light"
        return info

    def prefers_dark_panel(self) -> bool | None:
        try:
            cp = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return cp.returncode == 0 and "dark" in cp.stdout.lower()
