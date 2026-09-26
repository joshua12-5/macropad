"""Open the vendor-config HID interface and exchange framed packets.

Requires the optional ``hid`` package (cython-hidapi). Without hardware or
without the module, callers get a clear DeviceError — GUI stays usable.
"""

from __future__ import annotations

import time
from typing import Optional

from .frames import (
    CFG_CMD_GET_INFO,
    CFG_CMD_PING,
    CFG_FLAG_RESPONSE,
    CFG_REPORT_SIZE,
    Frame,
    FrameError,
    pack_frame,
    parse_get_info,
    unpack_frame,
)

USB_VID = 0x2E8A
USB_PID = 0xC001
CFG_USAGE_PAGE = 0xFF00
CFG_USAGE = 0x01

DEFAULT_TIMEOUT_MS = 500


class DeviceError(RuntimeError):
    """No device, missing hid module, I/O failure, or protocol error."""


def _import_hid():
    try:
        import hid  # type: ignore
    except ImportError as exc:
        raise DeviceError(
            "Python module 'hid' (hidapi) is not installed. "
            "pip install hid  (or hidapi)"
        ) from exc
    return hid


def list_config_devices(
    vid: int = USB_VID, pid: int = USB_PID
) -> list[dict]:
    """Enumerate matching HID interfaces (usage page 0xFF00 preferred)."""
    hid = _import_hid()
    found: list[dict] = []
    for info in hid.enumerate(vid, pid):
        up = int(info.get("usage_page") or 0)
        usage = int(info.get("usage") or 0)
        entry = dict(info)
        entry["_match_config"] = up == CFG_USAGE_PAGE
        found.append(entry)
        _ = usage  # reserved for stricter filter later
    return found


class ConfigDevice:
    """Thin hidapi wrapper around the vendor config channel."""

    def __init__(self, path: Optional[bytes] = None, *, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        self._hid = _import_hid()
        self._dev = self._hid.device()
        self._timeout_ms = timeout_ms
        self._path = path
        self._opened = False

    def open(self) -> None:
        if self._opened:
            return
        if self._path is not None:
            self._dev.open_path(self._path)
        else:
            path = self._find_config_path()
            if path is None:
                raise DeviceError(
                    f"No macropad config HID found (VID={USB_VID:#06x} "
                    f"PID={USB_PID:#06x} usage_page={CFG_USAGE_PAGE:#06x})"
                )
            self._dev.open_path(path)
        try:
            self._dev.set_nonblocking(False)
        except Exception:
            pass
        self._opened = True

    def close(self) -> None:
        if self._opened:
            try:
                self._dev.close()
            finally:
                self._opened = False

    def __enter__(self) -> "ConfigDevice":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _find_config_path(self) -> Optional[bytes]:
        devices = list_config_devices()
        for d in devices:
            if d.get("_match_config"):
                return d["path"]
        # Fallback: first interface for this VID/PID (weak).
        if devices:
            return devices[0]["path"]
        return None

    def write_frame(self, frame_bytes: bytes) -> None:
        if len(frame_bytes) != CFG_REPORT_SIZE:
            raise DeviceError("frame must be 64 bytes")
        # hidapi: leading report id 0x00 when descriptor has no report IDs.
        written = self._dev.write(b"\x00" + frame_bytes)
        if written < 0:
            raise DeviceError("hid write failed")

    def read_frame(self, timeout_ms: Optional[int] = None) -> bytes:
        timeout = self._timeout_ms if timeout_ms is None else timeout_ms
        deadline = time.monotonic() + (timeout / 1000.0)
        while time.monotonic() < deadline:
            remaining = max(1, int((deadline - time.monotonic()) * 1000))
            data = self._dev.read(CFG_REPORT_SIZE + 1, remaining)
            if not data:
                continue
            raw = bytes(data)
            if len(raw) == CFG_REPORT_SIZE + 1 and raw[0] == 0x00:
                return raw[1:]
            if len(raw) == CFG_REPORT_SIZE:
                return raw
            if len(raw) > CFG_REPORT_SIZE:
                # Unexpected prefix — try strip one byte.
                return raw[-CFG_REPORT_SIZE:]
        raise DeviceError("timeout waiting for device response")

    def transact(self, cmd: int, seq: int, payload: bytes = b"", *, flags: int = 0) -> Frame:
        req = pack_frame(cmd, seq, payload, flags=flags)
        self.write_frame(req)
        raw = self.read_frame()
        try:
            resp = unpack_frame(raw)
        except FrameError as exc:
            raise DeviceError(f"bad response frame: {exc}") from exc
        if not (resp.flags & CFG_FLAG_RESPONSE):
            raise DeviceError("response missing FLAG_RESPONSE")
        if resp.seq != (seq & 0xFF):
            raise DeviceError(f"seq mismatch: sent {seq & 0xFF} got {resp.seq}")
        return resp

    def ping(self, seq: int = 1) -> Frame:
        return self.transact(CFG_CMD_PING, seq)

    def get_info(self, seq: int = 2) -> dict:
        resp = self.transact(CFG_CMD_GET_INFO, seq)
        if resp.cmd != CFG_CMD_GET_INFO:
            raise DeviceError(f"unexpected cmd 0x{resp.cmd:02X}")
        return parse_get_info(resp.payload)


def connect_and_info(timeout_ms: int = DEFAULT_TIMEOUT_MS) -> dict:
    """Open device, PING, GET_INFO. Raises DeviceError on failure."""
    with ConfigDevice(timeout_ms=timeout_ms) as dev:
        pong = dev.ping(seq=1)
        if pong.payload not in (b"PONG", b""):
            # Accept empty OK or PONG
            if pong.cmd != CFG_CMD_PING:
                raise DeviceError("PING failed")
        info = dev.get_info(seq=2)
        info["ping_payload"] = pong.payload.decode("ascii", errors="replace")
        return info
