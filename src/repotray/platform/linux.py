"""Linux (and other freedesktop systems)."""

from __future__ import annotations

import contextlib
import filecmp
import os
import shutil
import subprocess
from pathlib import Path

from repotray.platform.base import BasePlatform, InstanceLock, env_path, spawn, split_template

SYSTEM_ICON = Path("/usr/share/icons/hicolor/scalable/status/repotray-symbolic.svg")

# (binary, template). The first entry whose binary exists wins; cwd is always set too.
TERMINALS: tuple[tuple[str, str], ...] = (
    ("gnome-terminal", "gnome-terminal --working-directory={path}"),
    ("terminator", "terminator --working-directory={path}"),
    ("xfce4-terminal", "xfce4-terminal --working-directory={path}"),
    ("mate-terminal", "mate-terminal --working-directory={path}"),
    ("konsole", "konsole --workdir {path}"),
    ("tilix", "tilix -w {path}"),
    ("kitty", "kitty --directory {path}"),
    ("alacritty", "alacritty --working-directory {path}"),
    ("wezterm", "wezterm start --cwd {path}"),
    ("foot", "foot -D {path}"),
    ("xterm", "xterm"),
)


def desktop_exec(argv: list[str]) -> str:
    """Quote argv for a .desktop Exec= line (freedesktop Desktop Entry spec)."""
    out = []
    for a in argv:
        if a and not any(c in a for c in " \t\n\"'\\><~|&;$*?#()`"):
            out.append(a.replace("%", "%%"))
        else:
            esc = a.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`")
            esc = esc.replace("$", "\\$").replace("%", "%%")
            out.append(f'"{esc}"')
    return " ".join(out)


def _gsettings(schema: str, key: str) -> str | None:
    if not shutil.which("gsettings"):
        return None
    try:
        cp = subprocess.run(
            ["gsettings", "get", schema, key],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if cp.returncode != 0:
        return None
    return cp.stdout.strip().strip("'")


class LinuxPlatform(BasePlatform):
    name = "linux"

    def __init__(self, which=shutil.which, run_spawn=spawn, gsettings=_gsettings) -> None:
        self.which = which
        self.spawn = run_spawn
        self.gsettings = gsettings

    # --- directories ---
    def config_dir(self) -> Path:
        return env_path("XDG_CONFIG_HOME", Path.home() / ".config") / self.app

    def state_dir(self) -> Path:
        return env_path("XDG_STATE_HOME", Path.home() / ".local" / "state") / self.app

    def cache_dir(self) -> Path:
        return env_path("XDG_CACHE_HOME", Path.home() / ".cache") / self.app

    def data_home(self) -> Path:
        return env_path("XDG_DATA_HOME", Path.home() / ".local" / "share")

    def runtime_dir(self) -> Path:
        rt = os.environ.get("XDG_RUNTIME_DIR")
        if rt and os.path.isdir(rt):
            return Path(rt) / self.app
        return self.state_dir()

    def autostart_file(self) -> Path:
        return (
            env_path("XDG_CONFIG_HOME", Path.home() / ".config") / "autostart" / "repotray.desktop"
        )

    def icon_dir(self) -> Path:
        return self.data_home() / "icons" / "hicolor" / "scalable" / "status"

    def icon_manifest(self) -> Path:
        return self.data_home() / self.app / "icons.manifest"

    # --- instance lock ---
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
        os.fsync(fd)

        def release(handle: int) -> None:
            try:
                fcntl.flock(handle, fcntl.LOCK_UN)
            finally:
                os.close(handle)

        return InstanceLock(path, fd, release)

    # --- opening things ---
    def terminal_template(self, configured: str) -> str:
        if configured:
            return configured
        known = dict(TERMINALS)
        xte = self.which("x-terminal-emulator")
        if xte:
            target = os.path.basename(os.path.realpath(xte))
            for name in known:
                if target == name or target.startswith(name + "."):
                    return known[name]
        for binary, template in TERMINALS:
            if self.which(binary):
                return template
        return "x-terminal-emulator" if xte else ""

    def open_terminal(self, path: Path, template: str) -> None:
        tmpl = self.terminal_template(template)
        if not tmpl:
            raise RuntimeError("no terminal emulator found; set 'terminal' in the config")
        self.spawn(split_template(tmpl, path), cwd=path)

    def open_folder(self, path: Path, template: str) -> None:
        argv = split_template(template, path) if template else ["xdg-open", str(path)]
        self.spawn(argv, cwd=path)

    def open_file(self, path: Path) -> None:
        self.spawn(["xdg-open", str(path)])

    def notify(self, title: str, body: str) -> bool:
        if not self.which("notify-send"):
            return False
        self.spawn(["notify-send", "-a", "repotray", "-i", "repotray-symbolic", title, body])
        return True

    # --- autostart ---
    def autostart_enable(self, argv: list[str]) -> str:
        f = self.autostart_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=repotray\n"
            "Comment=Tray indicator for the state of your git clones\n"
            f"Exec={desktop_exec(argv)}\n"
            "Icon=repotray-symbolic\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
            "NoDisplay=true\n",
            "utf-8",
        )
        return str(f)

    def autostart_disable(self) -> None:
        self.autostart_file().unlink(missing_ok=True)

    def autostart_enabled(self) -> bool:
        f = self.autostart_file()
        if not f.exists():
            return False
        text = f.read_text("utf-8", errors="replace")
        return "X-GNOME-Autostart-enabled=false" not in text and "Hidden=true" not in text

    # --- icons ---
    def install_icons(self, src: Path) -> list[Path]:
        """Copy missing or outdated symbolic icons into the user icon theme."""
        if SYSTEM_ICON.exists():
            return []
        dest = self.icon_dir()
        dest.mkdir(parents=True, exist_ok=True)
        manifest = self.icon_manifest()
        recorded = set(manifest.read_text("utf-8").splitlines()) if manifest.exists() else set()
        copied: list[Path] = []
        for svg in sorted(src.glob("*.svg")):
            target = dest / svg.name
            if not target.exists() or not filecmp.cmp(svg, target, shallow=False):
                shutil.copyfile(svg, target)
                copied.append(target)
            recorded.add(str(target))
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("".join(f"{p}\n" for p in sorted(recorded)), "utf-8")
        if copied:
            # Bump the theme directory's mtime so running GTK processes rescan it.
            os.utime(dest.parent.parent, None)
        return copied

    def uninstall_icons(self) -> list[Path]:
        manifest = self.icon_manifest()
        if not manifest.exists():
            return []
        removed: list[Path] = []
        for line in manifest.read_text("utf-8").splitlines():
            p = Path(line)
            if p.name.startswith("repotray") and p.exists():
                p.unlink()
                removed.append(p)
        manifest.unlink()
        with contextlib.suppress(OSError):
            manifest.parent.rmdir()
        return removed

    def icons_installed(self) -> str:
        if SYSTEM_ICON.exists():
            return f"system ({SYSTEM_ICON.parent})"
        if (self.icon_dir() / "repotray-symbolic.svg").exists():
            n = len(list(self.icon_dir().glob("repotray*-symbolic.svg")))
            return f"user ({self.icon_dir()}, {n} files)"
        return "not installed (the tray installs them at startup)"

    # --- desktop ---
    def desktop_info(self) -> dict[str, str]:
        info = {
            "platform": self.name,
            "desktop": os.environ.get("XDG_CURRENT_DESKTOP", "unknown"),
            "session": os.environ.get("XDG_SESSION_TYPE", "unknown"),
        }
        for label, schema, key in (
            ("cinnamon theme", "org.cinnamon.theme", "name"),
            ("gtk theme", "org.cinnamon.desktop.interface", "gtk-theme"),
            ("icon theme", "org.cinnamon.desktop.interface", "icon-theme"),
        ):
            v = self.gsettings(schema, key)
            if v:
                info[label] = v
        return info

    def prefers_dark_panel(self) -> bool | None:
        theme = self.gsettings("org.cinnamon.theme", "name")
        if theme:
            return "dark" in theme.lower()
        scheme = self.gsettings("org.gnome.desktop.interface", "color-scheme")
        if scheme:
            return "dark" in scheme.lower()
        return None
