"""OS services behind one protocol. ``current()`` returns the platform we run on."""

from __future__ import annotations

import sys
from functools import cache

from repotray.platform.base import BasePlatform, InstanceLock, Platform

__all__ = ["BasePlatform", "InstanceLock", "Platform", "current", "for_name"]


def for_name(name: str) -> BasePlatform:
    if name == "macos":
        from repotray.platform.macos import MacPlatform

        return MacPlatform()
    if name == "windows":
        from repotray.platform.windows import WindowsPlatform

        return WindowsPlatform()
    from repotray.platform.linux import LinuxPlatform

    return LinuxPlatform()


@cache
def current() -> BasePlatform:
    if sys.platform == "darwin":
        return for_name("macos")
    if sys.platform == "win32":
        return for_name("windows")
    return for_name("linux")
