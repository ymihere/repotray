"""Windows. Written to the same standard as Linux, unit-tested with mocks; untested on Windows."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from repotray.platform.base import BasePlatform, InstanceLock, spawn, split_template

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
PERSONALIZE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
VALUE_NAME = "repotray"


def _winreg():
    import winreg  # noqa: PLC0415 - Windows only

    return winreg


def quote_argv(argv: list[str]) -> str:
    return subprocess.list2cmdline(argv)


class WindowsPlatform(BasePlatform):
    name = "windows"

    def __init__(self, which=shutil.which, run_spawn=spawn, winreg=None, env=None) -> None:
        self.which = which
        self.spawn = run_spawn
        self._winreg = winreg
        self.env = os.environ if env is None else env

    @property
    def winreg(self):
        if self._winreg is None:
            self._winreg = _winreg()
        return self._winreg

    def _appdata(self) -> Path:
        return Path(self.env.get("APPDATA") or Path.home() / "AppData" / "Roaming")

    def _localappdata(self) -> Path:
        return Path(self.env.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")

    def config_dir(self) -> Path:
        return self._appdata() / self.app

    def state_dir(self) -> Path:
        return self._localappdata() / self.app

    def cache_dir(self) -> Path:
        return self._localappdata() / self.app / "cache"

    def runtime_dir(self) -> Path:
        return self._localappdata() / self.app

    def acquire_instance_lock(self, path: Path) -> InstanceLock | None:
        import msvcrt  # noqa: PLC0415 - Windows only

        path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(path, "a+")  # noqa: SIM115 - held for the process lifetime
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            fh.close()
            return None
        fh.seek(0)
        fh.truncate()
        fh.write(f"{os.getpid()}\n")
        fh.flush()

        def release(handle) -> None:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                handle.close()

        return InstanceLock(path, fh, release)

    def terminal_argv(self, path: Path, template: str) -> list[str]:
        if template:
            return split_template(template, path, posix=False)
        if self.which("wt"):
            return ["wt", "-d", str(path)]
        return ["cmd", "/K", "cd", "/d", str(path)]

    def open_terminal(self, path: Path, template: str) -> None:
        self.spawn(self.terminal_argv(path, template), cwd=path)

    def open_folder(self, path: Path, template: str) -> None:
        argv = split_template(template, path, posix=False) if template else ["explorer", str(path)]
        self.spawn(argv, cwd=path)

    def open_file(self, path: Path, template: str = "") -> None:
        if template:
            self.spawn(split_template(template, path, posix=False))
        else:
            os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606

    def notify(self, title: str, body: str) -> bool:
        return False  # pystray's own notify is used; there is no stdlib fallback

    def autostart_argv(self) -> list[str]:
        exe = Path(sys.executable)
        pythonw = exe.with_name("pythonw.exe")
        return [str(pythonw if pythonw.exists() else exe), "-m", "repotray"]

    def autostart_enable(self, argv: list[str]) -> str:
        wr = self.winreg
        with wr.CreateKey(wr.HKEY_CURRENT_USER, RUN_KEY) as key:
            wr.SetValueEx(key, VALUE_NAME, 0, wr.REG_SZ, quote_argv(argv))
        return rf"HKCU\{RUN_KEY}\{VALUE_NAME}"

    def autostart_disable(self) -> None:
        wr = self.winreg
        try:
            with wr.OpenKey(wr.HKEY_CURRENT_USER, RUN_KEY, 0, wr.KEY_SET_VALUE) as key:
                wr.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass

    def autostart_enabled(self) -> bool:
        wr = self.winreg
        try:
            with wr.OpenKey(wr.HKEY_CURRENT_USER, RUN_KEY) as key:
                wr.QueryValueEx(key, VALUE_NAME)
                return True
        except FileNotFoundError:
            return False

    def prefers_dark_panel(self) -> bool | None:
        wr = self.winreg
        try:
            with wr.OpenKey(wr.HKEY_CURRENT_USER, PERSONALIZE_KEY) as key:
                value, _ = wr.QueryValueEx(key, "SystemUsesLightTheme")
                return not bool(value)
        except (FileNotFoundError, OSError):
            return None

    def desktop_info(self) -> dict[str, str]:
        dark = self.prefers_dark_panel()
        taskbar = "unknown" if dark is None else ("dark" if dark else "light")
        return {"platform": self.name, "taskbar": taskbar}
