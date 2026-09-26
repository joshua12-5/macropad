"""Open the vendor-config HID interface and exchange framed packets.

Requires the optional ``hid`` package (cython-hidapi). Without hardware or
without the module, callers get a clear DeviceError — GUI stays usable.
"""

from __future__ import annotations

import struct
import time
from typing import Callable, Iterable, Optional, Tuple

from .frames import (
    CFG_CMD_GET_INFO,
    CFG_CMD_MACRO_ABORT,
    CFG_CMD_MACRO_BEGIN,
    CFG_CMD_MACRO_COMMIT,
    CFG_CMD_MACRO_DATA,
    CFG_CMD_MACRO_GET,
    CFG_CMD_NAK,
    CFG_CMD_GET_ACTIVE,
    CFG_CMD_PING,
    CFG_CMD_PROFILE_ABORT,
    CFG_CMD_SAVE_ALL,
    CFG_CMD_SET_ACTIVE,
    CFG_CMD_PROFILE_BEGIN,
    CFG_CMD_PROFILE_COMMIT,
    CFG_CMD_PROFILE_DATA,
    CFG_CMD_PROFILE_GET,
    CFG_ERR_EBADMSG,
    CFG_ERR_EBUSY,
    CFG_ERR_EINVAL,
    CFG_ERR_ENOSYS,
    CFG_FLAG_RESPONSE,
    CFG_REPORT_SIZE,
    Frame,
    FrameError,
    pack_frame,
    parse_get_info,
    unpack_frame,
)
from .macro_blob import (
    MACRO_BLOB_V1_SIZE,
    MACRO_DATA_MAX_CHUNK,
    blob_crc as macro_blob_crc,
    iter_macro_data_chunks,
)
from .profile_blob import (
    PROFILE_BLOB_V1_SIZE,
    PROFILE_DATA_MAX_CHUNK,
    blob_crc as profile_blob_crc,
    iter_profile_data_chunks,
)

USB_VID = 0x2E8A
USB_PID = 0xC001
CFG_USAGE_PAGE = 0xFF00
CFG_USAGE = 0x01

DEFAULT_TIMEOUT_MS = 500

_ERR_NAMES = {
    CFG_ERR_EINVAL: "EINVAL",
    CFG_ERR_EBADMSG: "EBADMSG",
    CFG_ERR_ENOSYS: "ENOSYS",
    CFG_ERR_EBUSY: "EBUSY",
}


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


def iter_blob_data_chunks(
    blob: bytes, chunk_size: int = PROFILE_DATA_MAX_CHUNK
) -> Iterable[Tuple[int, bytes]]:
    """Shared chunker for profile/macro DATA framing (offset + bytes)."""
    if chunk_size < 1 or chunk_size > 50:
        raise DeviceError(f"bad chunk_size {chunk_size}")
    offset = 0
    while offset < len(blob):
        piece = blob[offset : offset + chunk_size]
        yield offset, piece
        offset += len(piece)


class ConfigDevice:
    """Thin hidapi wrapper around the vendor config channel."""

    def __init__(self, path: Optional[bytes] = None, *, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        self._hid = _import_hid()
        self._dev = self._hid.device()
        self._timeout_ms = timeout_ms
        self._path = path
        self._opened = False
        self._seq = 1

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
        if devices:
            return devices[0]["path"]
        return None

    def _next_seq(self) -> int:
        seq = self._seq & 0xFF
        self._seq = (self._seq + 1) & 0xFF
        if self._seq == 0:
            self._seq = 1
        return seq

    def write_frame(self, frame_bytes: bytes) -> None:
        if len(frame_bytes) != CFG_REPORT_SIZE:
            raise DeviceError("frame must be 64 bytes")
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

    def _raise_if_nak(self, resp: Frame, what: str) -> None:
        if resp.cmd == CFG_CMD_NAK:
            err = resp.payload[0] if resp.payload else 0
            name = _ERR_NAMES.get(err, f"UNKNOWN({err})")
            raise DeviceError(
                f"{what} failed: device NAK {name} (code {err}). "
                f"See protocol/PROTOCOL.md error table."
            )

    def ping(self, seq: int = 1) -> Frame:
        return self.transact(CFG_CMD_PING, seq)

    def get_info(self, seq: int = 2) -> dict:
        resp = self.transact(CFG_CMD_GET_INFO, seq)
        self._raise_if_nak(resp, "GET_INFO")
        if resp.cmd != CFG_CMD_GET_INFO:
            raise DeviceError(f"unexpected cmd 0x{resp.cmd:02X}")
        return parse_get_info(resp.payload)

    def _chunked_upload(
        self,
        *,
        slot_or_id: int,
        blob: bytes,
        expected_size: int,
        begin_cmd: int,
        data_cmd: int,
        commit_cmd: int,
        abort_cmd: int,
        label: str,
        chunk_iter: Callable[[bytes], Iterable[Tuple[int, bytes]]],
        crc_fn: Callable[[bytes], int],
        timeout_ms: int = 2000,
    ) -> None:
        """Shared BEGIN/DATA/COMMIT/ABORT path for profile + macro blobs."""
        if not 0 <= int(slot_or_id) <= 4:
            raise DeviceError(f"{label} id/slot must be 0..4, got {slot_or_id}")
        if len(blob) != expected_size:
            raise DeviceError(
                f"{label} blob must be {expected_size} bytes, got {len(blob)}"
            )

        old_timeout = self._timeout_ms
        self._timeout_ms = timeout_ms
        started = False
        committed = False
        try:
            crc = crc_fn(blob)
            begin_pl = struct.pack(
                "<BHI", int(slot_or_id) & 0xFF, expected_size, crc
            )
            resp = self.transact(begin_cmd, self._next_seq(), begin_pl)
            self._raise_if_nak(resp, f"{label}_BEGIN")
            if resp.cmd != begin_cmd:
                raise DeviceError(
                    f"{label}_BEGIN unexpected cmd 0x{resp.cmd:02X}"
                )
            started = True

            for offset, chunk in chunk_iter(blob):
                data_pl = struct.pack("<H", offset) + chunk
                resp = self.transact(data_cmd, self._next_seq(), data_pl)
                self._raise_if_nak(resp, f"{label}_DATA@{offset}")
                if resp.cmd != data_cmd:
                    raise DeviceError(
                        f"{label}_DATA unexpected cmd 0x{resp.cmd:02X}"
                    )

            resp = self.transact(commit_cmd, self._next_seq(), b"")
            self._raise_if_nak(resp, f"{label}_COMMIT")
            if resp.cmd != commit_cmd:
                raise DeviceError(
                    f"{label}_COMMIT unexpected cmd 0x{resp.cmd:02X}"
                )
            committed = True
        except Exception:
            if started and not committed:
                try:
                    self.transact(abort_cmd, self._next_seq(), b"")
                except Exception:
                    pass
            raise
        finally:
            self._timeout_ms = old_timeout

    def upload_profile(self, slot: int, blob_bytes: bytes, *, timeout_ms: int = 2000) -> None:
        """Upload a packed profile_blob_v1 into device slot 0..4 (chunked)."""
        self._chunked_upload(
            slot_or_id=slot,
            blob=blob_bytes,
            expected_size=PROFILE_BLOB_V1_SIZE,
            begin_cmd=CFG_CMD_PROFILE_BEGIN,
            data_cmd=CFG_CMD_PROFILE_DATA,
            commit_cmd=CFG_CMD_PROFILE_COMMIT,
            abort_cmd=CFG_CMD_PROFILE_ABORT,
            label="PROFILE",
            chunk_iter=lambda b: iter_profile_data_chunks(b, PROFILE_DATA_MAX_CHUNK),
            crc_fn=profile_blob_crc,
            timeout_ms=timeout_ms,
        )

    def upload_macro(self, macro_id: int, blob_bytes: bytes, *, timeout_ms: int = 2000) -> None:
        """Upload a packed macro_blob_v1 into device macro id 0..4 (chunked)."""
        self._chunked_upload(
            slot_or_id=macro_id,
            blob=blob_bytes,
            expected_size=MACRO_BLOB_V1_SIZE,
            begin_cmd=CFG_CMD_MACRO_BEGIN,
            data_cmd=CFG_CMD_MACRO_DATA,
            commit_cmd=CFG_CMD_MACRO_COMMIT,
            abort_cmd=CFG_CMD_MACRO_ABORT,
            label="MACRO",
            chunk_iter=lambda b: iter_macro_data_chunks(b, MACRO_DATA_MAX_CHUNK),
            crc_fn=macro_blob_crc,
            timeout_ms=timeout_ms,
        )


    def set_active_slot(self, slot: int) -> None:
        """SET_ACTIVE (0x30) — switch RAM profile + OLED; no flash write."""
        slot = int(slot)
        if not 0 <= slot <= 4:
            raise DeviceError(f"slot must be 0..4, got {slot}")
        resp = self.transact(
            CFG_CMD_SET_ACTIVE, self._next_seq(), bytes([slot & 0xFF])
        )
        self._raise_if_nak(resp, "SET_ACTIVE")
        if resp.cmd != CFG_CMD_SET_ACTIVE:
            raise DeviceError(f"SET_ACTIVE unexpected cmd 0x{resp.cmd:02X}")

    def get_active_slot(self) -> int:
        """GET_ACTIVE (0x31) → slot u8 (optional; GET_INFO also has active_slot)."""
        resp = self.transact(CFG_CMD_GET_ACTIVE, self._next_seq(), b"")
        self._raise_if_nak(resp, "GET_ACTIVE")
        if resp.cmd != CFG_CMD_GET_ACTIVE or not resp.payload:
            raise DeviceError("bad GET_ACTIVE response")
        return int(resp.payload[0])

    def save_all(self) -> None:
        """SAVE_ALL (0x32) — immediate flash rewrite of profiles+macros+active_slot."""
        resp = self.transact(CFG_CMD_SAVE_ALL, self._next_seq(), b"")
        self._raise_if_nak(resp, "SAVE_ALL")
        if resp.cmd != CFG_CMD_SAVE_ALL:
            raise DeviceError(f"SAVE_ALL unexpected cmd 0x{resp.cmd:02X}")

    def profile_get_meta(self, slot: int) -> dict:
        """PROFILE_GET → {slot, len, crc}."""
        resp = self.transact(
            CFG_CMD_PROFILE_GET, self._next_seq(), bytes([int(slot) & 0xFF])
        )
        self._raise_if_nak(resp, "PROFILE_GET")
        if resp.cmd != CFG_CMD_PROFILE_GET or len(resp.payload) < 7:
            raise DeviceError("bad PROFILE_GET response")
        s, length, crc = struct.unpack_from("<BHI", resp.payload, 0)
        return {"slot": s, "len": length, "crc": crc}

    def macro_get_meta(self, macro_id: int) -> dict:
        """MACRO_GET → {id, len, crc}."""
        resp = self.transact(
            CFG_CMD_MACRO_GET, self._next_seq(), bytes([int(macro_id) & 0xFF])
        )
        self._raise_if_nak(resp, "MACRO_GET")
        if resp.cmd != CFG_CMD_MACRO_GET or len(resp.payload) < 7:
            raise DeviceError("bad MACRO_GET response")
        mid, length, crc = struct.unpack_from("<BHI", resp.payload, 0)
        return {"id": mid, "len": length, "crc": crc}


def connect_and_info(timeout_ms: int = DEFAULT_TIMEOUT_MS) -> dict:
    """Open device, PING, GET_INFO. Raises DeviceError on failure."""
    with ConfigDevice(timeout_ms=timeout_ms) as dev:
        pong = dev.ping(seq=1)
        if pong.payload not in (b"PONG", b""):
            if pong.cmd != CFG_CMD_PING:
                raise DeviceError("PING failed")
        info = dev.get_info(seq=2)
        info["ping_payload"] = pong.payload.decode("ascii", errors="replace")
        return info
