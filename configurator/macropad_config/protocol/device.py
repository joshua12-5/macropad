"""Open the vendor-config HID interface and exchange framed packets.

Requires an optional hidapi binding. Both Python APIs are supported:

* ``pip install hidapi`` (cython-hidapi): ``hid.device().open_path(...)`` —
  pinned in ``requirements.txt`` (wheels embed native hidapi;
  on Linux the ``hidraw`` module of the same package is preferred);
* ``pip install hid`` (pyhidapi / ctypes): ``hid.Device(path=...)`` — needs a
  system libhidapi.

Without hardware or without the module, callers get a clear DeviceError — GUI
stays usable. Tests can inject any object exposing ``enumerate`` plus either
``device`` or ``Device`` via ``hid_module=`` (see ``macropad_config.hil.mock``).
"""

from __future__ import annotations

import struct
import sys
import time
from collections.abc import Callable, Iterable
from typing import Optional

from .frames import (
    CFG_ANIM_CHUNK_MAX,
    CFG_CMD_ANIM_ABORT,
    CFG_CMD_ANIM_BEGIN,
    CFG_CMD_ANIM_COMMIT,
    CFG_CMD_ANIM_DATA,
    CFG_CMD_ANIM_INFO,
    CFG_CMD_ANIM_PREVIEW,
    CFG_CMD_ANIM_READ,
    CFG_CMD_ANIM_SETTINGS_GET,
    CFG_CMD_ANIM_SETTINGS_SET,
    CFG_CMD_ECHO,
    CFG_CMD_GET_ACTIVE,
    CFG_CMD_GET_INFO,
    CFG_CMD_MACRO_ABORT,
    CFG_CMD_MACRO_BEGIN,
    CFG_CMD_MACRO_COMMIT,
    CFG_CMD_MACRO_DATA,
    CFG_CMD_MACRO_GET,
    CFG_CMD_MACRO_READ,
    CFG_CMD_NAK,
    CFG_CMD_PING,
    CFG_CMD_PROFILE_ABORT,
    CFG_CMD_PROFILE_BEGIN,
    CFG_CMD_PROFILE_COMMIT,
    CFG_CMD_PROFILE_DATA,
    CFG_CMD_PROFILE_GET,
    CFG_CMD_PROFILE_READ,
    CFG_CMD_SAVE_ALL,
    CFG_CMD_SET_ACTIVE,
    CFG_ERR_EBADMSG,
    CFG_ERR_EBUSY,
    CFG_ERR_EINVAL,
    CFG_ERR_ENOSYS,
    CFG_FLAG_RESPONSE,
    CFG_READ_CHUNK_MAX,
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
    iter_macro_data_chunks,
)
from .macro_blob import (
    blob_crc as macro_blob_crc,
)
from .profile_blob import (
    PROFILE_BLOB_V1_SIZE,
    PROFILE_DATA_MAX_CHUNK,
    iter_profile_data_chunks,
)
from .profile_blob import (
    blob_crc as profile_blob_crc,
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


class NakError(DeviceError):
    """Device answered with NAK; ``code`` is the CFG_ERR_* value."""

    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = int(code)


def err_name(code: int) -> str:
    return _ERR_NAMES.get(int(code), f"UNKNOWN({code})")


def _import_hid():
    """Return the hidapi binding module.

    Release builds ship cython-hidapi (``pip install hidapi``), whose
    wheels embed the native hidapi library. On Linux that package provides two
    modules — ``hid`` (libusb backend, needs /dev/bus/usb access and detaches
    kernel drivers) and ``hidraw`` (hidraw backend, works with the shipped
    udev rule and reports usage pages). Prefer ``hidraw`` there; everything
    else uses ``hid`` (either cython-hidapi or pyhidapi).
    """
    if sys.platform.startswith("linux"):
        try:
            import hidraw  # type: ignore

            if hasattr(hidraw, "enumerate") and hasattr(hidraw, "device"):
                return hidraw
        except ImportError:
            pass
    try:
        import hid  # type: ignore
    except ImportError as exc:
        detail = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        raise DeviceError(
            "Python module 'hid' (hidapi) is not available: "
            f"{detail}. pip install hidapi (bundles the native library) "
            "or pip install hid (needs the system hidapi library, "
            "e.g. apt install libhidapi-hidraw0 / brew install hidapi)"
        ) from exc
    return hid


def hid_binding_info(hid_module=None) -> dict:
    """Describe the active binding: module name, API flavour, version."""
    mod = hid_module if hid_module is not None else _import_hid()
    if hasattr(mod, "device"):
        api = "cython-hidapi"
    elif hasattr(mod, "Device"):
        api = "pyhidapi"
    else:
        api = "unknown"
    version = getattr(mod, "__version__", None) or getattr(mod, "version_str", None)
    if callable(version):
        try:
            version = version()
        except Exception:
            version = None
    return {"module": getattr(mod, "__name__", "?"), "api": api, "version": version}


class _HidHandle:
    """Uniform open/read/write over cython-hidapi and pyhidapi ``hid`` modules.

    cython-hidapi (``pip install hidapi``, what ``requirements.txt`` pins) exposes
    ``hid.device()``; pyhidapi (``pip install hid``) exposes ``hid.Device(path=...)``.
    Both are accepted so either binding works on real hardware.
    """

    def __init__(self, hid_module) -> None:
        self._mod = hid_module
        self._dev = None

    def open_path(self, path: bytes) -> None:
        try:
            if hasattr(self._mod, "device"):
                dev = self._mod.device()
                dev.open_path(path)
            elif hasattr(self._mod, "Device"):
                dev = self._mod.Device(path=path)
            else:
                raise DeviceError("hid module has neither device() nor Device()")
        except DeviceError:
            raise
        except Exception as exc:  # OSError / HIDException / IOError
            raise DeviceError(f"cannot open HID path {path!r}: {exc}") from exc
        self._dev = dev
        try:
            if hasattr(dev, "set_nonblocking"):
                dev.set_nonblocking(False)
            elif hasattr(dev, "nonblocking"):
                dev.nonblocking = False
        except Exception:
            pass

    def write(self, data: bytes) -> int:
        try:
            return int(self._dev.write(data))
        except Exception as exc:
            raise DeviceError(f"hid write failed: {exc}") from exc

    def read(self, size: int, timeout_ms: int) -> bytes:
        try:
            if hasattr(self._dev, "set_nonblocking"):  # cython-hidapi
                data = self._dev.read(size, timeout_ms)
            else:  # pyhidapi
                data = self._dev.read(size, timeout=timeout_ms)
        except Exception as exc:
            raise DeviceError(f"hid read failed: {exc}") from exc
        return bytes(data or b"")

    def close(self) -> None:
        if self._dev is not None:
            try:
                self._dev.close()
            finally:
                self._dev = None


def list_config_devices(vid: int = USB_VID, pid: int = USB_PID, *, hid_module=None) -> list[dict]:
    """Enumerate matching HID interfaces (usage page 0xFF00 preferred)."""
    hid = hid_module if hid_module is not None else _import_hid()
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

    def __init__(
        self,
        path: Optional[bytes] = None,
        *,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        hid_module=None,
    ):
        self._hid = hid_module if hid_module is not None else _import_hid()
        self._dev = _HidHandle(self._hid)
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
        self._opened = True

    def close(self) -> None:
        if self._opened:
            try:
                self._dev.close()
            finally:
                self._opened = False

    def __enter__(self) -> ConfigDevice:
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def timeout_ms(self) -> int:
        return self._timeout_ms

    @timeout_ms.setter
    def timeout_ms(self, value: int) -> None:
        self._timeout_ms = int(value)

    def _find_config_path(self) -> Optional[bytes]:
        devices = list_config_devices(hid_module=self._hid)
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

    def exchange_raw(self, frame_bytes: bytes, *, timeout_ms: Optional[int] = None) -> Frame:
        """Send an arbitrary (possibly malformed) 64-byte frame, parse the reply.

        Used by HIL tests for CRC / magic / version injection. The reply is
        still validated with ``unpack_frame``.
        """
        self.write_frame(frame_bytes)
        raw = self.read_frame(timeout_ms)
        try:
            return unpack_frame(raw)
        except FrameError as exc:
            raise DeviceError(f"bad response frame: {exc}") from exc

    def request(self, cmd: int, payload: bytes = b"") -> Frame:
        """``transact`` with an auto-incremented seq (NAKs returned, not raised)."""
        return self.transact(cmd, self._next_seq(), payload)

    def _raise_if_nak(self, resp: Frame, what: str) -> None:
        if resp.cmd == CFG_CMD_NAK:
            err = resp.payload[0] if resp.payload else 0
            name = err_name(err)
            raise NakError(
                f"{what} failed: device NAK {name} (code {err}). See docs/PROTOCOL.md error table.",
                err,
            )

    def ping(self, seq: int = 1) -> Frame:
        return self.transact(CFG_CMD_PING, seq)

    def echo(self, payload: bytes) -> bytes:
        """ECHO (0x03) → returns the echoed payload."""
        resp = self.request(CFG_CMD_ECHO, bytes(payload))
        self._raise_if_nak(resp, "ECHO")
        if resp.cmd != CFG_CMD_ECHO:
            raise DeviceError(f"ECHO unexpected cmd 0x{resp.cmd:02X}")
        return resp.payload

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
        chunk_iter: Callable[[bytes], Iterable[tuple[int, bytes]]],
        crc_fn: Callable[[bytes], int],
        timeout_ms: int = 2000,
    ) -> None:
        """Shared BEGIN/DATA/COMMIT/ABORT path for profile + macro blobs."""
        if not 0 <= int(slot_or_id) <= 4:
            raise DeviceError(f"{label} id/slot must be 0..4, got {slot_or_id}")
        if len(blob) != expected_size:
            raise DeviceError(f"{label} blob must be {expected_size} bytes, got {len(blob)}")

        old_timeout = self._timeout_ms
        self._timeout_ms = timeout_ms
        started = False
        committed = False
        try:
            crc = crc_fn(blob)
            begin_pl = struct.pack("<BHI", int(slot_or_id) & 0xFF, expected_size, crc)
            resp = self.transact(begin_cmd, self._next_seq(), begin_pl)
            self._raise_if_nak(resp, f"{label}_BEGIN")
            if resp.cmd != begin_cmd:
                raise DeviceError(f"{label}_BEGIN unexpected cmd 0x{resp.cmd:02X}")
            started = True

            for offset, chunk in chunk_iter(blob):
                data_pl = struct.pack("<H", offset) + chunk
                resp = self.transact(data_cmd, self._next_seq(), data_pl)
                self._raise_if_nak(resp, f"{label}_DATA@{offset}")
                if resp.cmd != data_cmd:
                    raise DeviceError(f"{label}_DATA unexpected cmd 0x{resp.cmd:02X}")

            resp = self.transact(commit_cmd, self._next_seq(), b"")
            self._raise_if_nak(resp, f"{label}_COMMIT")
            if resp.cmd != commit_cmd:
                raise DeviceError(f"{label}_COMMIT unexpected cmd 0x{resp.cmd:02X}")
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
        resp = self.transact(CFG_CMD_SET_ACTIVE, self._next_seq(), bytes([slot & 0xFF]))
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
        resp = self.transact(CFG_CMD_PROFILE_GET, self._next_seq(), bytes([int(slot) & 0xFF]))
        self._raise_if_nak(resp, "PROFILE_GET")
        if resp.cmd != CFG_CMD_PROFILE_GET or len(resp.payload) < 7:
            raise DeviceError("bad PROFILE_GET response")
        s, length, crc = struct.unpack_from("<BHI", resp.payload, 0)
        return {"slot": s, "len": length, "crc": crc}

    def _read_blob(self, cmd: int, label: str, slot_or_id: int, size: int) -> bytes:
        out = bytearray()
        while len(out) < size:
            offset = len(out)
            resp = self.request(cmd, struct.pack("<BH", int(slot_or_id) & 0xFF, offset))
            self._raise_if_nak(resp, f"{label}@{offset}")
            if resp.cmd != cmd or len(resp.payload) < 4:
                raise DeviceError(f"bad {label} response")
            rid, roff = struct.unpack_from("<BH", resp.payload, 0)
            chunk = resp.payload[3:]
            if rid != (int(slot_or_id) & 0xFF) or roff != offset:
                raise DeviceError(f"{label} echoed id/offset {rid}/{roff}, want {slot_or_id}/{offset}")
            if len(chunk) > CFG_READ_CHUNK_MAX:
                raise DeviceError(f"{label} chunk too long ({len(chunk)})")
            out += chunk
        if len(out) != size:
            raise DeviceError(f"{label} returned {len(out)} bytes, want {size}")
        return bytes(out)

    def profile_read(self, slot: int) -> bytes:
        """PROFILE_READ (0x15, fw 0.23+) → packed 148-byte profile blob from RAM."""
        return self._read_blob(CFG_CMD_PROFILE_READ, "PROFILE_READ", slot, PROFILE_BLOB_V1_SIZE)

    def macro_read(self, macro_id: int) -> bytes:
        """MACRO_READ (0x25, fw 0.23+) → packed 162-byte macro blob from RAM."""
        return self._read_blob(CFG_CMD_MACRO_READ, "MACRO_READ", macro_id, MACRO_BLOB_V1_SIZE)

    def macro_get_meta(self, macro_id: int) -> dict:
        """MACRO_GET → {id, len, crc}."""
        resp = self.transact(CFG_CMD_MACRO_GET, self._next_seq(), bytes([int(macro_id) & 0xFF]))
        self._raise_if_nak(resp, "MACRO_GET")
        if resp.cmd != CFG_CMD_MACRO_GET or len(resp.payload) < 7:
            raise DeviceError("bad MACRO_GET response")
        mid, length, crc = struct.unpack_from("<BHI", resp.payload, 0)
        return {"id": mid, "len": length, "crc": crc}

    # ---- OLED idle animation (fw 0.25+, GET_INFO flag bit3) ----

    def _anim_cmd(self, cmd: int, payload: bytes, label: str, timeout_ms: Optional[int] = None) -> Frame:
        old = self._timeout_ms
        if timeout_ms is not None:
            self._timeout_ms = timeout_ms
        try:
            resp = self.transact(cmd, self._next_seq(), payload)
        finally:
            self._timeout_ms = old
        self._raise_if_nak(resp, label)
        if resp.cmd != cmd:
            raise DeviceError(f"{label} unexpected cmd 0x{resp.cmd:02X}")
        return resp

    def anim_info(self) -> dict:
        """ANIM_INFO (0x44) → status dict (see animation.codec.parse_anim_info)."""
        from ..animation.codec import parse_anim_info

        return parse_anim_info(self._anim_cmd(CFG_CMD_ANIM_INFO, b"", "ANIM_INFO").payload)

    def anim_settings_get(self) -> dict:
        from ..animation.codec import unpack_settings

        return unpack_settings(self._anim_cmd(CFG_CMD_ANIM_SETTINGS_GET, b"", "ANIM_SETTINGS_GET").payload)

    def anim_settings_set(self, *, enabled: bool, idle_timeout_s: int, blank_timeout_s: int) -> dict:
        """ANIM_SETTINGS_SET (0x47): persisted immediately (MPFL v3 rewrite)."""
        from ..animation.codec import pack_settings, unpack_settings

        pl = pack_settings(enabled, idle_timeout_s, blank_timeout_s)
        resp = self._anim_cmd(CFG_CMD_ANIM_SETTINGS_SET, pl, "ANIM_SETTINGS_SET", timeout_ms=3000)
        return unpack_settings(resp.payload)

    def anim_preview(self, mode: int) -> None:
        """ANIM_PREVIEW (0x48): 0 stop, 1 play stored, 2 builtin, 3 blank."""
        self._anim_cmd(CFG_CMD_ANIM_PREVIEW, bytes([int(mode) & 0xFF]), "ANIM_PREVIEW")

    def anim_abort(self) -> None:
        self._anim_cmd(CFG_CMD_ANIM_ABORT, b"", "ANIM_ABORT", timeout_ms=3000)

    def anim_upload(
        self,
        blob: bytes,
        progress: Optional[Callable[[int, int], Optional[bool]]] = None,
        *,
        timeout_ms: int = 5000,
    ) -> None:
        """ANIM_BEGIN / DATA×N / COMMIT. ``progress(done, total)`` may return
        False to cancel (→ ANIM_ABORT, DeviceError). Sector erase/program runs
        inside DATA/COMMIT on the device, hence the long timeout."""
        from ..protocol.frames import crc32 as _crc32

        blob = bytes(blob)
        started = committed = False
        try:
            self._anim_cmd(
                CFG_CMD_ANIM_BEGIN,
                struct.pack("<II", len(blob), _crc32(blob)),
                "ANIM_BEGIN",
                timeout_ms=timeout_ms,
            )
            started = True
            off = 0
            while off < len(blob):
                chunk = blob[off : off + CFG_ANIM_CHUNK_MAX]
                self._anim_cmd(
                    CFG_CMD_ANIM_DATA,
                    struct.pack("<I", off) + chunk,
                    f"ANIM_DATA@{off}",
                    timeout_ms=timeout_ms,
                )
                off += len(chunk)
                if progress is not None and progress(off, len(blob)) is False:
                    raise DeviceError("animation upload cancelled")
            self._anim_cmd(CFG_CMD_ANIM_COMMIT, b"", "ANIM_COMMIT", timeout_ms=timeout_ms)
            committed = True
        except Exception:
            if started and not committed:
                try:
                    self.anim_abort()
                except Exception:
                    pass
            raise

    def anim_read(self, offset: int, length: int) -> bytes:
        """ANIM_READ (0x45) chunks from the flash region."""
        out = bytearray()
        while len(out) < length:
            off = int(offset) + len(out)
            resp = self._anim_cmd(CFG_CMD_ANIM_READ, struct.pack("<I", off), f"ANIM_READ@{off}")
            if len(resp.payload) < 5:
                raise DeviceError("short ANIM_READ response")
            (roff,) = struct.unpack_from("<I", resp.payload, 0)
            if roff != off:
                raise DeviceError(f"ANIM_READ echoed offset {roff}, want {off}")
            out += resp.payload[4:]
        return bytes(out[:length])

    def anim_download(self) -> Optional[bytes]:
        """Read back the stored blob (None when no valid animation is stored)."""
        info = self.anim_info()
        if not info["stored_valid"]:
            return None
        return self.anim_read(0, info["total_len"])


def connect_and_info(timeout_ms: int = DEFAULT_TIMEOUT_MS, *, hid_module=None) -> dict:
    """Open device, PING, GET_INFO. Raises DeviceError on failure."""
    with ConfigDevice(timeout_ms=timeout_ms, hid_module=hid_module) as dev:
        pong = dev.ping(seq=1)
        if pong.payload not in (b"PONG", b""):
            if pong.cmd != CFG_CMD_PING:
                raise DeviceError("PING failed")
        info = dev.get_info(seq=2)
        info["ping_payload"] = pong.payload.decode("ascii", errors="replace")
        return info
