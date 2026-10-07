"""core/, platform/, the CLI and the pure UI helpers must import without any GUI toolkit."""

import importlib
import pkgutil
import re
import sys
from pathlib import Path

import repotray

SRC = Path(repotray.__file__).parent
BLOCKED = ("gi", "pystray", "PIL", "PySide6")
HEADLESS = [
    "repotray.cli",
    "repotray.app",
    "repotray.icons.names",
    "repotray.icons.svg",
    "repotray.ui.placement",
    "repotray.ui.text",
    "repotray.backends.registry",
    "repotray.backends.base",
]


def headless_modules() -> list[str]:
    mods = []
    for pkg in ("core", "platform"):
        path = SRC / pkg
        mods += [f"repotray.{pkg}.{m.name}" for m in pkgutil.iter_modules([str(path)])]
    # M1: modules of later milestones are checked once they exist.
    return mods + [
        m for m in HEADLESS if SRC.joinpath(*m.split(".")[1:]).with_suffix(".py").exists()
    ]


def test_headless_imports_without_toolkits(monkeypatch):
    for name in list(sys.modules):
        if name == "repotray" or name.startswith("repotray."):
            monkeypatch.delitem(sys.modules, name)
    for blocked in BLOCKED:
        monkeypatch.setitem(sys.modules, blocked, None)
    for mod in headless_modules():
        importlib.import_module(mod)


def test_no_toolkit_import_statements():
    pattern = re.compile(r"^\s*(import|from)\s+(gi|pystray|PIL|PySide6)\b", re.M)
    for mod in headless_modules():
        path = SRC.joinpath(*mod.split(".")[1:]).with_suffix(".py")
        assert not pattern.search(path.read_text("utf-8")), f"{path} imports a GUI toolkit"
