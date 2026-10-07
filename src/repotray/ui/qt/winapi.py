"""The few Win32 calls Qt does not wrap. Every function is a no-op off Windows and never raises."""

from __future__ import annotations

import logging
import sys

log = logging.getLogger(__name__)

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2


def round_corners(hwnd: int) -> bool:
    """Ask Windows 11 to round a frameless window's corners like its own flyouts (and give it the
    flyout shadow). Windows 10 has no such attribute: the window simply stays square."""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    try:
        pref = ctypes.c_int(DWMWCP_ROUND)
        res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            ctypes.c_uint(DWMWA_WINDOW_CORNER_PREFERENCE),
            ctypes.byref(pref),
            ctypes.sizeof(pref),
        )
    except (AttributeError, OSError):
        log.debug("DwmSetWindowAttribute unavailable", exc_info=True)
        return False
    return res == 0


def force_foreground(hwnd: int) -> bool:
    """Bring our window to the foreground when Windows' foreground lock refused a plain
    activation: attach to the foreground window's input queue for the call, as Qt's own
    ``AlwaysActivateWindow`` behaviour does."""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        target = wintypes.HWND(hwnd)
        fg = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        me = kernel32.GetCurrentThreadId()
        attached = bool(
            fg_thread and fg_thread != me and user32.AttachThreadInput(me, fg_thread, True)
        )
        try:
            user32.BringWindowToTop(target)
            ok = bool(user32.SetForegroundWindow(target))
        finally:
            if attached:
                user32.AttachThreadInput(me, fg_thread, False)
    except (AttributeError, OSError):
        log.debug("foreground request failed", exc_info=True)
        return False
    return ok
