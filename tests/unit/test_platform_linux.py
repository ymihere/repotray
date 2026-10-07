import os
from pathlib import Path

import pytest

from repotray.platform.base import split_template
from repotray.platform.linux import LinuxPlatform, desktop_exec

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX only")


class Spawned:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, cwd=None):
        self.calls.append((argv, cwd))


def which_from(names, xte_target=None, tmp_path=None):
    def which(name):
        if name == "x-terminal-emulator" and xte_target:
            return xte_target
        return f"/usr/bin/{name}" if name in names else None

    return which


def test_xdg_dirs(isolated_env):
    p = LinuxPlatform()
    assert p.config_dir() == Path(os.environ["XDG_CONFIG_HOME"]) / "repotray"
    assert p.state_dir() == Path(os.environ["XDG_STATE_HOME"]) / "repotray"
    assert p.cache_dir() == Path(os.environ["XDG_CACHE_HOME"]) / "repotray"
    assert p.runtime_dir() == Path(os.environ["XDG_RUNTIME_DIR"]) / "repotray"
    assert p.config_path().name == "config.toml"


def test_split_template_substitutes_after_splitting():
    path = Path("/home/u/my repo")
    assert split_template("kitty --directory {path}", path) == ["kitty", "--directory", str(path)]
    assert split_template("terminator --working-directory={path}", path) == [
        "terminator",
        f"--working-directory={path}",
    ]
    assert split_template("sh -c 'echo {path}'", path) == ["sh", "-c", f"echo {path}"]


def no_gsettings(schema, key):
    return None


def plain_env(tmp_path, desktop=""):
    return {
        "XDG_CURRENT_DESKTOP": desktop,
        "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
        "XDG_CONFIG_DIRS": str(tmp_path / "etc"),
        "XDG_DATA_DIRS": str(tmp_path / "share"),
    }


def test_terminal_falls_back_to_x_terminal_emulator(tmp_path):
    target = tmp_path / "terminator"
    target.write_text("")
    link = tmp_path / "x-terminal-emulator"
    link.symlink_to(target)
    env = plain_env(tmp_path)
    p = LinuxPlatform(
        which=which_from({"gnome-terminal"}, str(link)), gsettings=no_gsettings, env=env
    )
    assert p.terminal_template("") == "terminator --working-directory={path}"
    p2 = LinuxPlatform(which=which_from({"konsole", "xterm"}), gsettings=no_gsettings, env=env)
    assert p2.terminal_template("") == "konsole --workdir {path}"
    assert p2.terminal_template("foot -D {path}") == "foot -D {path}"


def test_desktop_preferred_terminal_wins_over_x_terminal_emulator(tmp_path):
    """Mint: Preferred Applications says gnome-terminal, the Debian alternative terminator."""
    target = tmp_path / "terminator"
    target.write_text("")
    link = tmp_path / "x-terminal-emulator"
    link.symlink_to(target)
    which = which_from({"gnome-terminal", "terminator", "mate-terminal"}, str(link))
    settings = {
        ("org.cinnamon.desktop.default-applications.terminal", "exec"): "gnome-terminal",
        ("org.mate.applications-terminal", "exec"): "mate-terminal",
        ("org.gnome.desktop.default-applications.terminal", "exec"): "x-terminal-emulator",
    }

    def gs(schema, key):
        return settings.get((schema, key))

    def tmpl(desktop):
        env = plain_env(tmp_path, desktop)
        return LinuxPlatform(which=which, gsettings=gs, env=env).terminal_template("")

    assert tmpl("X-Cinnamon") == "gnome-terminal --working-directory={path}"
    assert tmpl("MATE") == "mate-terminal --working-directory={path}"
    # GNOME's setting names x-terminal-emulator: follow the alternative.
    assert tmpl("ubuntu:GNOME") == "terminator --working-directory={path}"
    assert tmpl("X-Cinnamon") != tmpl("")  # without a desktop: x-terminal-emulator


def test_xdg_terminals_list(tmp_path):
    env = plain_env(tmp_path, "KDE")
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg/xdg-terminals.list").write_text("# comment\nmy.Kitty.desktop\n")
    apps = tmp_path / "share/applications"
    apps.mkdir(parents=True)
    (apps / "my.Kitty.desktop").write_text("[Desktop Entry]\nExec=kitty --single-instance\n")
    p = LinuxPlatform(which=which_from({"kitty", "xterm"}), gsettings=no_gsettings, env=env)
    p.data_home = lambda: tmp_path / "nowhere"
    assert p.preferred_terminal() == "kitty"
    assert p.terminal_template("") == "kitty --directory {path}"


def test_unknown_preferred_terminal_runs_in_cwd(tmp_path):
    env = plain_env(tmp_path, "X-Cinnamon")

    def gs(schema, key):
        return "cool-retro-term"

    p = LinuxPlatform(which=which_from({"cool-retro-term"}), gsettings=gs, env=env)
    assert p.terminal_template("") == "cool-retro-term"


def test_open_file_with_editor_template(tmp_path):
    sp = Spawned()
    p = LinuxPlatform(run_spawn=sp)
    f = tmp_path / "log file.txt"
    p.open_file(f)
    p.open_file(f, "xed --new-window {path}")
    assert sp.calls[0][0] == ["xdg-open", str(f)]
    assert sp.calls[1][0] == ["xed", "--new-window", str(f)]


def test_open_terminal_and_folder(tmp_path):
    sp = Spawned()
    p = LinuxPlatform(which=which_from({"tilix"}), run_spawn=sp)
    p.open_terminal(tmp_path, "")
    p.open_folder(tmp_path, "")
    p.open_folder(tmp_path, "nemo {path}")
    assert sp.calls == [
        (["tilix", "-w", str(tmp_path)], tmp_path),
        (["xdg-open", str(tmp_path)], tmp_path),
        (["nemo", str(tmp_path)], tmp_path),
    ]
    with pytest.raises(RuntimeError):
        LinuxPlatform(which=which_from(set()), run_spawn=sp).open_terminal(tmp_path, "")


def test_notify_fallback():
    sp = Spawned()
    assert LinuxPlatform(which=which_from({"notify-send"}), run_spawn=sp).notify("T", "B")
    assert sp.calls[0][0][-2:] == ["T", "B"] and sp.calls[0][0][0] == "notify-send"
    assert not LinuxPlatform(which=which_from(set()), run_spawn=sp).notify("T", "B")


def test_autostart_roundtrip():
    p = LinuxPlatform()
    assert not p.autostart_enabled()
    where = p.autostart_enable(["/home/u/.local/bin/repotray", "tray"])
    text = Path(where).read_text()
    assert "Exec=/home/u/.local/bin/repotray tray" in text
    assert "X-GNOME-Autostart-enabled=true" in text and "NoDisplay=true" in text
    assert p.autostart_enabled()
    p.autostart_disable()
    assert not p.autostart_enabled()


def test_desktop_exec_quoting():
    assert desktop_exec(["/usr/bin/python3", "-m", "repotray"]) == "/usr/bin/python3 -m repotray"
    assert desktop_exec(["/opt/my app/x", "50%"]) == '"/opt/my app/x" 50%%'


def test_instance_lock(tmp_path):
    p = LinuxPlatform()
    lock = tmp_path / "rt/repotray.lock"
    held = p.acquire_instance_lock(lock)
    assert held is not None
    assert p.read_lock_pid(lock) == os.getpid()
    assert p.acquire_instance_lock(lock) is None
    held.release()
    again = p.acquire_instance_lock(lock)
    assert again is not None
    again.release()


def test_icon_install_uninstall(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "repotray-symbolic.svg").write_text("<svg/>")
    (src / "repotray-top-success-symbolic.svg").write_text("<svg id='2'/>")
    p = LinuxPlatform()
    if Path("/usr/share/icons/hicolor/scalable/status/repotray-symbolic.svg").exists():
        pytest.skip("system-wide icons installed")
    copied = p.install_icons(src)
    assert len(copied) == 2
    assert p.install_icons(src) == []  # unchanged → nothing copied
    (src / "repotray-symbolic.svg").write_text("<svg changed/>")
    assert [c.name for c in p.install_icons(src)] == ["repotray-symbolic.svg"]
    assert "user" in p.icons_installed()
    other = p.icon_dir() / "someone-else.svg"
    other.write_text("x")
    removed = p.uninstall_icons()
    assert len(removed) == 2 and other.exists()
    assert not p.icon_manifest().exists()


def test_prefers_dark_panel():
    def gs(values):
        return lambda schema, key: values.get((schema, key))

    p = LinuxPlatform(gsettings=gs({("org.cinnamon.theme", "name"): "Mint-Y-Dark-Aqua"}))
    assert p.prefers_dark_panel() is True
    p = LinuxPlatform(gsettings=gs({("org.cinnamon.theme", "name"): "Mint-Y"}))
    assert p.prefers_dark_panel() is False
    p = LinuxPlatform(
        gsettings=gs({("org.gnome.desktop.interface", "color-scheme"): "prefer-dark"})
    )
    assert p.prefers_dark_panel() is True
    assert LinuxPlatform(gsettings=gs({})).prefers_dark_panel() is None
