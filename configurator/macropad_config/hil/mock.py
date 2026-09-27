"""In-process mock macropad (Step 23) — fake ``hid`` module + firmware model.

The model mirrors ``firmware/src/config_protocol.c`` + ``storage.c`` +
``profile_blob.c`` / ``macro_blob.c`` / ``macros.c`` closely enough for the HIL
suite to run headless:

* frame validation order + NAK codes (magic/CRC → EBADMSG, version/length →
  EINVAL, frames with FLAG_RESPONSE ignored, unknown cmd → EINVAL,
  short OUT report → EBADMSG);
* profile / macro upload staging (one shared buffer, receive mask, EBUSY
  mutex, COMMIT auto-abort on incomplete / CRC / unpack errors);
* firmware blob canonicalisation (unpack → RAM → pack), so READ returns what
  real firmware would;
* 4 KiB storage-v2 flash image with a write counter, debounced SET_ACTIVE
  persist (4 s) incl. the Step 23 "skip if unchanged" rule;
* ``fw_minor < 23`` disables PROFILE_READ / MACRO_READ, the READBACK info bit
  and the debounce skip (behaves like a Step 22 device).

Plug it into the real host stack via ``ConfigDevice(hid_module=MockHidModule())``
so framing, report-id handling and chunking are the production code paths.
"""

from __future__ import annotations

import json
import struct
import time
from collections import deque
from pathlib import Path
from typing import Callable, Optional

from ..paths import resource_root
from ..protocol import frames as F
from ..protocol.device import USB_PID, USB_VID
from ..protocol.macro_blob import MACRO_BLOB_V1_SIZE, pack_macro
from ..protocol.profile_blob import PROFILE_BLOB_V1_SIZE, pack_profile_dict

PROFILE_SLOT_COUNT = 5
MACRO_COUNT = 5
MACRO_MAX_STEPS = 24
FLASH_SECTOR_SIZE = 4096
STORAGE_MAGIC = 0x4C46504D  # 'MPFL'
STORAGE_VERSION_2 = 2
STORAGE_ACTIVE_DEBOUNCE_S = 4.0
PRODUCT_TAG = b"MACROPAD"

UPLOAD_NONE, UPLOAD_PROFILE, UPLOAD_MACRO = 0, 1, 2

_REPO = resource_root()  # bundled defaults (repo root in a checkout)
_PROFILE_FILES = ("Default", "Gaming", "Coding", "Browser", "Photoshop")


# --------------------------------------------------------------------------
# Firmware blob canonicalisation (unpack → RAM struct → pack)
# --------------------------------------------------------------------------

def _fw_copy_name(field: bytes) -> bytes:
    """profile_blob.c / macro_blob.c copy_name(): force NUL at [15], zero tail."""
    b = bytearray(field[:16])
    b[15] = 0
    nul = b.find(0)
    b[nul:] = bytes(16 - nul)
    return bytes(b)


def fw_profile_canon(blob: bytes) -> Optional[bytes]:
    """What firmware stores for this PROFILE blob, or None if unpack fails."""
    if len(blob) < PROFILE_BLOB_V1_SIZE:
        return None
    if struct.unpack_from("<H", blob, 0)[0] != 1:  # PROFILE_SCHEMA_VERSION
        return None
    out = bytearray(blob[:PROFILE_BLOB_V1_SIZE])
    for off in (2, 18, 130):  # id, name, oled.title
        out[off:off + 16] = _fw_copy_name(blob[off:off + 16])
    out[147] = 0  # pad
    return bytes(out)


def fw_macro_canon(blob: bytes) -> Optional[bytes]:
    """macro_blob_unpack + macros_replace + macro_blob_pack, or None."""
    if len(blob) < MACRO_BLOB_V1_SIZE:
        return None
    name = _fw_copy_name(blob[0:16])
    count = blob[16]
    if count < 1 or count > MACRO_MAX_STEPS:
        return None
    steps = [list(blob[18 + i * 6: 24 + i * 6]) for i in range(MACRO_MAX_STEPS)]
    step_count = None
    for i in range(count):
        if steps[i][0] == 0:  # MACRO_END
            step_count = i + 1
            break
    if step_count is None:
        if count >= MACRO_MAX_STEPS:
            return None
        steps[count][0] = 0  # append END (other fields of that step kept, like fw)
        step_count = count + 1
    out = bytearray(MACRO_BLOB_V1_SIZE)
    out[0:16] = name
    out[16] = step_count
    out[17] = 0
    for i in range(step_count):
        s = steps[i]
        out[18 + i * 6: 24 + i * 6] = bytes([s[0], s[1], s[2], 0, s[4], s[5]])
    return bytes(out)


def _default_profiles() -> list[bytes]:
    blobs: list[bytes] = []
    for i, name in enumerate(_PROFILE_FILES):
        path = _REPO / "profiles" / f"{name}.json"
        try:
            blob = pack_profile_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            blob = pack_profile_dict(
                {"schema_version": 1, "id": name.lower(), "name": name.upper()}
            )
        canon = fw_profile_canon(blob)
        assert canon is not None
        blobs.append(canon)
    return blobs


def _default_macros() -> list[bytes]:
    lib = {}
    try:
        lib = json.loads((_REPO / "macros" / "library.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    by_id = {int(m.get("id", -1)): m for m in lib.get("macros", [])}
    blobs: list[bytes] = []
    for i in range(MACRO_COUNT):
        m = by_id.get(i) or {"name": f"m{i}", "steps": [{"op": "END"}]}
        canon = fw_macro_canon(pack_macro(m))
        assert canon is not None
        blobs.append(canon)
    return blobs


# --------------------------------------------------------------------------
# Firmware model
# --------------------------------------------------------------------------

class MockFirmware:
    """Python port of the config protocol + storage state machine."""

    def __init__(
        self,
        *,
        fw_major: int = 0,
        fw_minor: int = 23,
        blank_flash: bool = False,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self.fw_major = int(fw_major)
        self.fw_minor = int(fw_minor)
        self._clock_fn = clock or time.monotonic
        self._clock_offset = 0.0
        self.profiles = _default_profiles()
        self.macros = _default_macros()
        self.active = 2  # profiles_init(): Coding
        self.flash = bytes([0xFF]) * FLASH_SECTOR_SIZE
        self.flash_writes = 0
        self.fail_flash = False
        self.flash_in_sync = False
        self.loaded_from_flash = False
        self.upload_kind = UPLOAD_NONE
        self.upload_slot = 0
        self.upload_len = 0
        self.upload_crc = 0
        self.upload_buf = bytearray(MACRO_BLOB_V1_SIZE)
        self.upload_mask = [False] * MACRO_BLOB_V1_SIZE
        self.persist_pending = False
        self.persist_deadline = 0.0
        self.log: list[str] = []
        if not blank_flash:
            # Device that has been saved once: flash == RAM defaults.
            self.flash = self._build_image()
            self.flash_in_sync = True
            self.loaded_from_flash = True

    # -- time -------------------------------------------------------------
    def now(self) -> float:
        return self._clock_fn() + self._clock_offset

    def advance(self, seconds: float) -> None:
        """Fast-forward the mock clock (debounce tests) and run the persist task."""
        self._clock_offset += float(seconds)
        self.persist_task()

    @property
    def has_readback(self) -> bool:
        return (self.fw_major, self.fw_minor) >= (0, 23)

    # -- storage ------------------------------------------------------------
    def _build_image(self) -> bytes:
        body = bytearray()
        body += struct.pack("<IHBB", STORAGE_MAGIC, STORAGE_VERSION_2, self.active, 0)
        for p in self.profiles:
            body += p
        for m in self.macros:
            body += m
        body += struct.pack("<I", F.crc32(bytes(body)))
        return bytes(body) + bytes([0xFF]) * (FLASH_SECTOR_SIZE - len(body))

    def flash_image_valid_v2(self) -> bool:
        body_len = 8 + PROFILE_SLOT_COUNT * PROFILE_BLOB_V1_SIZE + MACRO_COUNT * MACRO_BLOB_V1_SIZE
        img = self.flash
        magic, ver, active, _flags = struct.unpack_from("<IHBB", img, 0)
        if magic != STORAGE_MAGIC or ver != STORAGE_VERSION_2 or active >= PROFILE_SLOT_COUNT:
            return False
        return F.crc32(img[:body_len]) == struct.unpack_from("<I", img, body_len)[0]

    def save_all(self) -> bool:
        self.persist_pending = False
        if self.fail_flash:
            self.flash_in_sync = False
            self.log.append("stor save fail")
            return False
        self.flash = self._build_image()
        self.flash_writes += 1
        self.loaded_from_flash = True
        self.flash_in_sync = True
        self.log.append("stor save ok")
        return True

    def schedule_persist(self) -> None:
        self.persist_pending = True
        self.persist_deadline = self.now() + STORAGE_ACTIVE_DEBOUNCE_S

    def persist_task(self) -> None:
        if not self.persist_pending or self.now() < self.persist_deadline:
            return
        self.persist_pending = False
        if self.upload_kind != UPLOAD_NONE:
            self.schedule_persist()
            return
        if (
            self.has_readback
            and self.flash_in_sync
            and self.flash_image_valid_v2()
            and self.flash[6] == self.active
        ):
            self.log.append("stor debounce skip (unchanged)")
            return
        self.log.append("stor debounce save")
        self.save_all()

    # -- upload staging (storage.c) -------------------------------------------
    def _upload_begin(self, kind: int, slot: int, total: int, crc: int) -> bool:
        if self.upload_kind != UPLOAD_NONE:
            return False
        if kind == UPLOAD_PROFILE:
            if slot >= PROFILE_SLOT_COUNT or total != PROFILE_BLOB_V1_SIZE:
                return False
        else:
            if slot >= MACRO_COUNT or total != MACRO_BLOB_V1_SIZE:
                return False
        self.upload_kind = kind
        self.upload_slot = slot
        self.upload_len = total
        self.upload_crc = crc
        self.upload_buf = bytearray(MACRO_BLOB_V1_SIZE)
        self.upload_mask = [False] * MACRO_BLOB_V1_SIZE
        return True

    def _upload_data(self, offset: int, data: bytes) -> bool:
        if offset + len(data) > self.upload_len:
            return False
        self.upload_buf[offset:offset + len(data)] = data
        for i in range(offset, offset + len(data)):
            self.upload_mask[i] = True
        return True

    def _upload_got(self) -> int:
        return sum(1 for i in range(self.upload_len) if self.upload_mask[i])

    def _upload_abort(self, kind: int) -> None:
        if self.upload_kind == kind:
            self.upload_kind = UPLOAD_NONE

    def _upload_commit(self, kind: int) -> int:
        if self.upload_kind != kind:
            return F.CFG_ERR_EINVAL
        if self._upload_got() != self.upload_len:
            self._upload_abort(kind)
            return F.CFG_ERR_EINVAL
        blob = bytes(self.upload_buf[: self.upload_len])
        if F.crc32(blob) != self.upload_crc:
            self._upload_abort(kind)
            return F.CFG_ERR_EBADMSG
        if kind == UPLOAD_PROFILE:
            canon = fw_profile_canon(blob)
            if canon is None:
                self._upload_abort(kind)
                return F.CFG_ERR_EINVAL
            self.upload_kind = UPLOAD_NONE
            self.profiles[self.upload_slot] = canon
        else:
            canon = fw_macro_canon(blob)
            if canon is None:
                self._upload_abort(kind)
                return F.CFG_ERR_EINVAL
            self.upload_kind = UPLOAD_NONE
            self.macros[self.upload_slot] = canon
        if not self.save_all():
            return F.CFG_ERR_EBUSY
        return F.CFG_ERR_OK

    # -- protocol (config_protocol.c) ---------------------------------------
    @staticmethod
    def _resp(cmd: int, seq: int, payload: bytes = b"") -> bytes:
        return F.pack_frame(cmd, seq, payload[: F.CFG_PAYLOAD_MAX], flags=F.CFG_FLAG_RESPONSE)

    def _nak(self, seq: int, err: int) -> bytes:
        self.log.append(f"cfg nak err={err}")
        return self._resp(F.CFG_CMD_NAK, seq, bytes([err]))

    def _validate(self, buf: bytes) -> int:
        magic = struct.unpack_from("<H", buf, 0)[0]
        if magic != F.CFG_MAGIC:
            return F.CFG_ERR_EBADMSG
        if buf[2] != F.CFG_PROTO_VERSION:
            return F.CFG_ERR_EINVAL
        if struct.unpack_from("<H", buf, 6)[0] > F.CFG_PAYLOAD_MAX:
            return F.CFG_ERR_EINVAL
        if F.crc32(buf[:60]) != struct.unpack_from("<I", buf, 60)[0]:
            return F.CFG_ERR_EBADMSG
        return F.CFG_ERR_OK

    def on_host_report(self, report: bytes) -> Optional[bytes]:
        """config_protocol_on_host_report(): returns the response frame or None."""
        self.persist_task()
        if len(report) < F.CFG_REPORT_SIZE:
            if len(report) >= 6:
                return self._nak(report[5], F.CFG_ERR_EBADMSG)
            return None
        return self.handle(bytes(report[: F.CFG_REPORT_SIZE]))

    def handle(self, req: bytes) -> Optional[bytes]:
        verr = self._validate(req)
        seq = req[5]
        if verr != F.CFG_ERR_OK:
            return self._nak(seq, verr)
        if req[3] & F.CFG_FLAG_RESPONSE:
            return None
        cmd = req[4]
        length = struct.unpack_from("<H", req, 6)[0]
        pl = req[8: 8 + length]
        raw_pl = req[8:60]  # firmware reads payload[] past length (zero padded)

        if cmd == F.CFG_CMD_PING:
            return self._resp(cmd, seq, b"PONG")
        if cmd == F.CFG_CMD_GET_INFO:
            flags = F.CFG_INFO_FLAG_STORAGE | F.CFG_INFO_FLAG_MACRO_BANK
            if self.has_readback:
                flags |= F.CFG_INFO_FLAG_READBACK
            info = bytes([self.fw_major, self.fw_minor, F.CFG_PROTO_VERSION,
                          self.active, PROFILE_SLOT_COUNT, flags]) + PRODUCT_TAG
            return self._resp(cmd, seq, info)
        if cmd == F.CFG_CMD_ECHO:
            return self._resp(cmd, seq, pl)

        if cmd in (F.CFG_CMD_PROFILE_BEGIN, F.CFG_CMD_MACRO_BEGIN):
            if length < 7:
                return self._nak(seq, F.CFG_ERR_EINVAL)
            if self.upload_kind != UPLOAD_NONE:
                return self._nak(seq, F.CFG_ERR_EBUSY)
            slot, total, crc = struct.unpack_from("<BHI", raw_pl, 0)
            kind = UPLOAD_PROFILE if cmd == F.CFG_CMD_PROFILE_BEGIN else UPLOAD_MACRO
            if not self._upload_begin(kind, slot, total, crc):
                return self._nak(seq, F.CFG_ERR_EINVAL)
            return self._resp(cmd, seq)

        if cmd in (F.CFG_CMD_PROFILE_DATA, F.CFG_CMD_MACRO_DATA):
            kind = UPLOAD_PROFILE if cmd == F.CFG_CMD_PROFILE_DATA else UPLOAD_MACRO
            if length < 2 or self.upload_kind != kind:
                return self._nak(seq, F.CFG_ERR_EINVAL)
            offset = struct.unpack_from("<H", raw_pl, 0)[0]
            if not self._upload_data(offset, bytes(raw_pl[2:length])):
                return self._nak(seq, F.CFG_ERR_EINVAL)
            return self._resp(cmd, seq)

        if cmd in (F.CFG_CMD_PROFILE_COMMIT, F.CFG_CMD_MACRO_COMMIT):
            kind = UPLOAD_PROFILE if cmd == F.CFG_CMD_PROFILE_COMMIT else UPLOAD_MACRO
            err = self._upload_commit(kind)
            if err != F.CFG_ERR_OK:
                return self._nak(seq, err)
            return self._resp(cmd, seq)

        if cmd in (F.CFG_CMD_PROFILE_ABORT, F.CFG_CMD_MACRO_ABORT):
            self._upload_abort(UPLOAD_PROFILE if cmd == F.CFG_CMD_PROFILE_ABORT else UPLOAD_MACRO)
            return self._resp(cmd, seq)

        if cmd in (F.CFG_CMD_PROFILE_GET, F.CFG_CMD_MACRO_GET):
            if length < 1:
                return self._nak(seq, F.CFG_ERR_EINVAL)
            idx = raw_pl[0]
            table = self.profiles if cmd == F.CFG_CMD_PROFILE_GET else self.macros
            if idx >= len(table):
                return self._nak(seq, F.CFG_ERR_EINVAL)
            blob = table[idx]
            return self._resp(cmd, seq, struct.pack("<BHI", idx, len(blob), F.crc32(blob)))

        if cmd in (F.CFG_CMD_PROFILE_READ, F.CFG_CMD_MACRO_READ) and self.has_readback:
            if length < 3:
                return self._nak(seq, F.CFG_ERR_EINVAL)
            idx, offset = struct.unpack_from("<BH", raw_pl, 0)
            table = self.profiles if cmd == F.CFG_CMD_PROFILE_READ else self.macros
            if idx >= len(table) or offset >= len(table[idx]):
                return self._nak(seq, F.CFG_ERR_EINVAL)
            chunk = table[idx][offset: offset + F.CFG_READ_CHUNK_MAX]
            return self._resp(cmd, seq, struct.pack("<BH", idx, offset) + chunk)

        if cmd == F.CFG_CMD_SET_ACTIVE:
            if length < 1 or raw_pl[0] >= PROFILE_SLOT_COUNT:
                return self._nak(seq, F.CFG_ERR_EINVAL)
            self.active = raw_pl[0]
            self.schedule_persist()
            return self._resp(cmd, seq)

        if cmd == F.CFG_CMD_GET_ACTIVE:
            return self._resp(cmd, seq, bytes([self.active]))

        if cmd == F.CFG_CMD_SAVE_ALL:
            if self.upload_kind != UPLOAD_NONE:
                return self._nak(seq, F.CFG_ERR_EBUSY)
            self.persist_pending = False
            if not self.save_all():
                return self._nak(seq, F.CFG_ERR_EBUSY)
            return self._resp(cmd, seq)

        return self._nak(seq, F.CFG_ERR_EINVAL)


# --------------------------------------------------------------------------
# Fake ``hid`` module (cython-hidapi or pyhidapi flavour)
# --------------------------------------------------------------------------

CONFIG_PATH = b"mock:if1-config"
KEYBOARD_PATH = b"mock:if0-keyboard"


class _MockHandle:
    def __init__(self, fw: MockFirmware) -> None:
        self._fw = fw
        self._rx: deque[bytes] = deque()
        self._open = False
        self.writes = 0

    def _open_path(self, path: bytes) -> None:
        if path != CONFIG_PATH:
            raise OSError(f"mock: cannot open {path!r} (only the config interface is emulated)")
        self._open = True

    def write(self, data) -> int:
        if not self._open:
            raise OSError("mock: device not open")
        data = bytes(data)
        self.writes += 1
        report = data[1:] if data[:1] == b"\x00" else data  # hidapi report-id byte
        resp = self._fw.on_host_report(report)
        if resp is not None:
            self._rx.append(resp)
        return len(data)

    def _read(self, size: int, timeout_ms: Optional[int]) -> bytes:
        if not self._open:
            raise OSError("mock: device not open")
        self._fw.persist_task()
        if self._rx:
            return self._rx.popleft()[:size]  # IF1 has no report id → 64 bytes
        if timeout_ms:
            time.sleep(min(int(timeout_ms), 5) / 1000.0)
        return b""

    def close(self) -> None:
        self._open = False


class MockCythonDevice(_MockHandle):
    """cython-hidapi flavour: hid.device(); open_path(); read(n, timeout_ms)."""

    def open_path(self, path: bytes) -> None:
        self._open_path(path)

    def set_nonblocking(self, flag) -> int:
        return 0

    def read(self, size: int, timeout_ms: int = 0):
        return list(self._read(size, timeout_ms))


class MockPyHidDevice(_MockHandle):
    """pyhidapi flavour: hid.Device(path=...); read(size, timeout=None)."""

    def __init__(self, fw: MockFirmware, path: bytes) -> None:
        super().__init__(fw)
        self._open_path(path)
        self.nonblocking = 0

    def read(self, size: int, timeout: Optional[int] = None) -> bytes:
        return self._read(size, timeout)


class MockHidModule:
    """Stand-in for ``import hid`` exposing one mock macropad."""

    def __init__(self, firmware: Optional[MockFirmware] = None, *, api: str = "cython",
                 present: bool = True) -> None:
        self.firmware = firmware or MockFirmware()
        self.api = api
        self.present = present
        if api == "cython":
            self.device = lambda: MockCythonDevice(self.firmware)
        elif api == "pyhidapi":
            self.Device = self._make_pyhid
        else:
            raise ValueError(f"unknown mock hid api {api!r}")

    def _make_pyhid(self, vid=None, pid=None, serial=None, path=None):
        return MockPyHidDevice(self.firmware, path)

    def enumerate(self, vid: int = 0, pid: int = 0) -> list[dict]:
        if not self.present:
            return []
        if (vid and vid != USB_VID) or (pid and pid != USB_PID):
            return []
        bcd = 0x0100 + self.firmware.fw_minor
        common = {
            "vendor_id": USB_VID,
            "product_id": USB_PID,
            "serial_number": "20400001",
            "release_number": bcd,
            "manufacturer_string": "Macropad",
            "product_string": "RP2040 Macropad (mock)",
        }
        return [
            dict(common, path=KEYBOARD_PATH, usage_page=0x0001, usage=0x0006, interface_number=0),
            dict(common, path=CONFIG_PATH, usage_page=0xFF00, usage=0x0001, interface_number=1),
        ]


__all__ = [
    "MockFirmware",
    "MockHidModule",
    "fw_macro_canon",
    "fw_profile_canon",
]
