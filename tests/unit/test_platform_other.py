"""macOS and Windows platform modules, exercised with mocks on any OS."""

import plistlib
from pathlib import Path

import pytest

from repotray.platform import for_name
from repotray.platform.macos import MacPlatform
from repotray.platform.windows import RUN_KEY, WindowsPlatform, quote_argv


class Spawned:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, cwd=None):
        self.calls.append((argv, cwd))


def test_for_name():
    assert for_name("macos").name == "macos"
    assert for_name("windows").name == "windows"
    assert for_name("linux").name == "linux"


# --- macOS ---------------------------------------------------------------------------------------


def test_mac_paths(tmp_path):
    p = MacPlatform(home=tmp_path)
    assert p.config_path() == tmp_path / "Library/Application Support/repotray/config.toml"
    assert p.cache_dir() == tmp_path / "Library/Caches/repotray"
    assert p.state_dir() == tmp_path / "Library/Logs/repotray"
    assert p.install_icons(tmp_path) == []


def test_mac_open_and_notify(tmp_path):
    sp = Spawned()
    p = MacPlatform(run_spawn=sp, home=tmp_path)
    p.open_terminal(tmp_path, "")
    p.open_folder(tmp_path, "")
    p.open_terminal(tmp_path, "open -a iTerm {path}")
    assert sp.calls[0] == (["open", "-a", "Terminal", str(tmp_path)], tmp_path)
    assert sp.calls[1] == (["open", str(tmp_path)], tmp_path)
    assert sp.calls[2][0] == ["open", "-a", "iTerm", str(tmp_path)]
    argv = p.notify_argv('Pushed "x"', "back\\slash")
    assert argv[:2] == ["osascript", "-e"]
    assert argv[2] == 'display notification "back\\\\slash" with title "Pushed \\"x\\""'


def test_mac_autostart(tmp_path):
    p = MacPlatform(home=tmp_path)
    assert not p.autostart_enabled()
    where = Path(p.autostart_enable(["/usr/local/bin/repotray", "tray"]))
    data = plistlib.loads(where.read_bytes())
    assert data["Label"] == "io.github.repotray"
    assert data["ProgramArguments"] == ["/usr/local/bin/repotray", "tray"]
    assert data["RunAtLoad"] is True
    assert p.autostart_enabled()
    p.autostart_disable()
    assert not p.autostart_enabled()


# --- Windows -------------------------------------------------------------------------------------


class FakeKey:
    def __init__(self, store, path):
        self.store, self.path = store, path

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        self.values: dict[tuple[str, str], object] = {}
        self.keys: set[str] = set()

    def CreateKey(self, root, path):  # noqa: N802
        self.keys.add(path)
        return FakeKey(self, path)

    def OpenKey(self, root, path, reserved=0, access=0):  # noqa: N802
        if path not in self.keys:
            raise FileNotFoundError(path)
        return FakeKey(self, path)

    def SetValueEx(self, key, name, reserved, kind, value):  # noqa: N802
        self.values[(key.path, name)] = value

    def QueryValueEx(self, key, name):  # noqa: N802
        if (key.path, name) not in self.values:
            raise FileNotFoundError(name)
        return self.values[(key.path, name)], 1

    def DeleteValue(self, key, name):  # noqa: N802
        if (key.path, name) not in self.values:
            raise FileNotFoundError(name)
        del self.values[(key.path, name)]


def test_windows_paths():
    env = {"APPDATA": r"C:\Users\u\AppData\Roaming", "LOCALAPPDATA": r"C:\Users\u\AppData\Local"}
    p = WindowsPlatform(env=env, winreg=FakeWinreg())
    assert str(p.config_dir()).endswith("repotray")
    assert str(p.config_dir()).startswith(env["APPDATA"])
    assert str(p.state_dir()).startswith(env["LOCALAPPDATA"])


def test_windows_terminal_argv(tmp_path):
    with_wt = WindowsPlatform(
        which=lambda n: "C:/wt.exe" if n == "wt" else None, winreg=FakeWinreg()
    )
    assert with_wt.terminal_argv(tmp_path, "") == ["wt", "-d", str(tmp_path)]
    plain = WindowsPlatform(which=lambda n: None, winreg=FakeWinreg())
    assert plain.terminal_argv(tmp_path, "") == ["cmd", "/K", "cd", "/d", str(tmp_path)]
    assert plain.terminal_argv(tmp_path, "pwsh -wd {path}") == ["pwsh", "-wd", str(tmp_path)]


def test_windows_autostart_registry():
    reg = FakeWinreg()
    p = WindowsPlatform(winreg=reg)
    assert not p.autostart_enabled()
    where = p.autostart_enable([r"C:\Python\pythonw.exe", "-m", "repotray"])
    assert where.endswith(r"Run\repotray")
    assert reg.values[(RUN_KEY, "repotray")] == r"C:\Python\pythonw.exe -m repotray"
    assert p.autostart_enabled()
    p.autostart_disable()
    assert not p.autostart_enabled()
    p.autostart_disable()  # idempotent


@pytest.mark.parametrize(("light", "dark"), [(1, False), (0, True)])
def test_windows_taskbar_theme(light, dark):
    reg = FakeWinreg()
    from repotray.platform.windows import PERSONALIZE_KEY

    reg.keys.add(PERSONALIZE_KEY)
    reg.values[(PERSONALIZE_KEY, "SystemUsesLightTheme")] = light
    assert WindowsPlatform(winreg=reg).prefers_dark_panel() is dark
    assert WindowsPlatform(winreg=FakeWinreg()).prefers_dark_panel() is None


def test_quote_argv():
    assert quote_argv([r"C:\Program Files\py\pythonw.exe", "-m", "repotray"]) == (
        r'"C:\Program Files\py\pythonw.exe" -m repotray'
    )
