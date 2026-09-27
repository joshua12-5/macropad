"""Best-effort foreground process + window title (never raises to callers)."""

from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ForegroundInfo:
    process: Optional[str]
    title: Optional[str]


def get_foreground() -> Optional[ForegroundInfo]:
    """Return foreground app info, or None on any failure."""
    try:
        system = platform.system()
        if system == "Windows":
            return _windows()
        if system == "Linux":
            return _linux()
        if system == "Darwin":
            return _darwin()
    except Exception:
        return None
    return None


def _windows() -> Optional[ForegroundInfo]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None

    # Title
    length = user32.GetWindowTextLengthW(hwnd)
    title = None
    if length > 0:
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value or None

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ForegroundInfo(process=None, title=title)

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ForegroundInfo(process=None, title=title)
    try:
        size = wintypes.DWORD(260)
        buf = ctypes.create_unicode_buffer(260)
        # QueryFullProcessImageNameW
        QueryFullProcessImageNameW = kernel32.QueryFullProcessImageNameW
        QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        QueryFullProcessImageNameW.restype = wintypes.BOOL
        ok = QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
        if not ok:
            return ForegroundInfo(process=None, title=title)
        path = buf.value
        name = os.path.basename(path) if path else None
        return ForegroundInfo(process=name, title=title)
    finally:
        kernel32.CloseHandle(handle)


def _linux() -> Optional[ForegroundInfo]:
    # Prefer xdotool when available (X11). Wayland often cannot query focus.
    try:
        wid = (
            subprocess.check_output(
                ["xdotool", "getactivewindow"],
                stderr=subprocess.DEVNULL,
                timeout=1.0,
            )
            .decode("utf-8", errors="replace")
            .strip()
        )
    except Exception:
        return None
    if not wid:
        return None

    title = None
    try:
        title = (
            subprocess.check_output(
                ["xdotool", "getwindowname", wid],
                stderr=subprocess.DEVNULL,
                timeout=1.0,
            )
            .decode("utf-8", errors="replace")
            .strip()
            or None
        )
    except Exception:
        title = None

    pid = None
    try:
        pid_s = (
            subprocess.check_output(
                ["xdotool", "getwindowpid", wid],
                stderr=subprocess.DEVNULL,
                timeout=1.0,
            )
            .decode("utf-8", errors="replace")
            .strip()
        )
        pid = int(pid_s)
    except Exception:
        return ForegroundInfo(process=None, title=title)

    process = None
    try:
        cmdline = Path_read(f"/proc/{pid}/comm")
        process = cmdline.strip() or None
    except Exception:
        try:
            exe = os.readlink(f"/proc/{pid}/exe")
            process = os.path.basename(exe) if exe else None
        except Exception:
            process = None

    return ForegroundInfo(process=process, title=title)


def Path_read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _darwin() -> Optional[ForegroundInfo]:
    # App name + front window title are queried separately for robustness.
    try:
        name = (
            subprocess.check_output(
                [
                    "osascript",
                    "-e",
                    'tell application "System Events" to get name of '
                    "first application process whose frontmost is true",
                ],
                stderr=subprocess.DEVNULL,
                timeout=2.0,
            )
            .decode("utf-8", errors="replace")
            .strip()
            or None
        )
    except Exception:
        return None

    title = None
    try:
        title = (
            subprocess.check_output(
                [
                    "osascript",
                    "-e",
                    'tell application "System Events" to get title of '
                    "first window of (first application process whose frontmost is true)",
                ],
                stderr=subprocess.DEVNULL,
                timeout=2.0,
            )
            .decode("utf-8", errors="replace")
            .strip()
            or None
        )
    except Exception:
        title = None

    return ForegroundInfo(process=name, title=title)
