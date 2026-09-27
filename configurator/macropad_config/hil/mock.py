"""In-process mock macropad — fake ``hid`` module + firmware model.

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
  persist (4 s) incl. the fw 0.23 "skip if unchanged" rule;
* ``fw_minor < 23`` disables PROFILE_READ / MACRO_READ, the READBACK info bit
  and the debounce skip (behaves like a fw 0.22 device);
* fw 0.25+ (``fw_minor >= 25``): OLED idle-animation commands 0x40-0x48 over a
  128 KiB flash region (sequential DATA, per-sector erase+program counter,
  COMMIT CRC + structural validation via ``animation.codec``, ABORT/failed
  COMMIT invalidate sector 0), idle settings persisted in an MPFL v3 image,
  EBUSY across profile/macro/animation uploads, ANIM_PREVIEW state.

Plug it into the real host stack via ``ConfigDevice(hid_module=MockHidModule())``
so framing, report-id handling and chunking are the production code paths.
"""

from __future__ import annotations

import json
import struct
import time
from collections import deque
from collections.abc import Callable
from typing import Optional

from ..animation import codec as A
from ..paths import resource_root
from ..protocol import frames as F
from ..protocol.device import USB_PID, USB_VID
from ..protocol.macro_blob import MACRO_BLOB_V1_SIZE, pack_macro
from ..protocol.profile_blob import PROFILE_BLOB_V1_SIZE, pack_profile_dict
from ..version import FW_VERSION_MINOR_CURRENT

PROFILE_SLOT_COUNT = 5
MACRO_COUNT = 5
MACRO_MAX_STEPS = 24
FLASH_SECTOR_SIZE = 4096
STORAGE_MAGIC = 0x4C46504D  # 'MPFL'
STORAGE_VERSION_2 = 2
STORAGE_VERSION_3 = 3  # + 8-byte idle-animation settings block
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
        out[off : off + 16] = _fw_copy_name(blob[off : off + 16])
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
    steps = [list(blob[18 + i * 6 : 24 + i * 6]) for i in range(MACRO_MAX_STEPS)]
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
        out[18 + i * 6 : 24 + i * 6] = bytes([s[0], s[1], s[2], 0, s[4], s[5]])
    return bytes(out)


def _default_profiles() -> list[bytes]:
    blobs: list[bytes] = []
    for name in _PROFILE_FILES:
        path = _REPO / "profiles" / f"{name}.json"
        try:
            blob = pack_profile_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            blob = pack_profile_dict({"schema_version": 1, "id": name.lower(), "name": name.upper()})
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
        fw_minor: int = FW_VERSION_MINOR_CURRENT,
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
        # OLED idle-animation model (fw 0.25+)
        self.anim_settings = {
            "enabled": True,
            "idle_timeout_s": A.DEFAULT_IDLE_S,
            "blank_timeout_s": A.DEFAULT_BLANK_S,
        }
        self.anim_region = bytearray(b"\xff" * A.REGION_SIZE)
        self.anim_sector_writes = 0
        self.anim_up_active = False
        self.anim_up_total = 0
        self.anim_up_crc = 0
        self.anim_up_got = 0
        self.anim_up_sectors = 0
        self.anim_up_stage = bytearray(b"\xff" * FLASH_SECTOR_SIZE)
        self.anim_stored: Optional[dict] = None
        self.anim_state = "active"  # active / playing / blank
        self.anim_preview_mode = 0
        self.anim_builtin_playing = False
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

    @property
    def has_anim(self) -> bool:
        return (self.fw_major, self.fw_minor) >= (0, 25)

    @property
    def storage_version(self) -> int:
        return STORAGE_VERSION_3 if self.has_anim else STORAGE_VERSION_2

    def _body_len(self, version: int) -> int:
        n = 8 + PROFILE_SLOT_COUNT * PROFILE_BLOB_V1_SIZE + MACRO_COUNT * MACRO_BLOB_V1_SIZE
        return n + (A.SETTINGS_SIZE if version >= STORAGE_VERSION_3 else 0)

    # -- storage ------------------------------------------------------------
    def _build_image(self) -> bytes:
        body = bytearray()
        body += struct.pack("<IHBB", STORAGE_MAGIC, self.storage_version, self.active, 0)
        for p in self.profiles:
            body += p
        for m in self.macros:
            body += m
        if self.storage_version >= STORAGE_VERSION_3:
            st = self.anim_settings
            body += A.pack_settings(st["enabled"], st["idle_timeout_s"], st["blank_timeout_s"])
        body += struct.pack("<I", F.crc32(bytes(body)))
        return bytes(body) + bytes([0xFF]) * (FLASH_SECTOR_SIZE - len(body))

    def flash_image_valid(self) -> bool:
        """Flash holds a valid image of the version this firmware writes (v2/v3)."""
        ver_want = self.storage_version
        body_len = self._body_len(ver_want)
        img = self.flash
        magic, ver, active, _flags = struct.unpack_from("<IHBB", img, 0)
        if magic != STORAGE_MAGIC or ver != ver_want or active >= PROFILE_SLOT_COUNT:
            return False
        return F.crc32(img[:body_len]) == struct.unpack_from("<I", img, body_len)[0]

    # Older name kept for existing smokes/tests.
    flash_image_valid_v2 = flash_image_valid

    def flash_anim_settings(self) -> Optional[dict]:
        """Idle settings stored in the MPFL v3 image (None for v2 / invalid)."""
        if not self.has_anim or not self.flash_image_valid():
            return None
        off = self._body_len(STORAGE_VERSION_2)
        return A.unpack_settings(self.flash[off : off + A.SETTINGS_SIZE])

    # -- animation (anim.c) ---------------------------------------------------
    def _anim_upload_busy_other(self) -> bool:
        return self.upload_kind != UPLOAD_NONE

    def _anim_flash_sector(self, index: int, data: Optional[bytes]) -> bool:
        if self.fail_flash:
            return False
        off = index * FLASH_SECTOR_SIZE
        self.anim_region[off : off + FLASH_SECTOR_SIZE] = (
            data if data is not None else b"\xff" * FLASH_SECTOR_SIZE
        )
        self.anim_sector_writes += 1
        return True

    def _anim_load_stored(self) -> None:
        self.anim_stored = None
        try:
            hdr = A.parse_header(bytes(self.anim_region[: A.HEADER_SIZE]))
            total = A.HEADER_SIZE + hdr["data_len"]
            if total > A.REGION_SIZE:
                return
            blob = bytes(self.anim_region[:total])
            A.parse_blob(blob)
        except A.AnimFormatError:
            return
        self.anim_stored = dict(hdr, total_len=total, crc=F.crc32(blob))

    def _anim_invalidate(self) -> None:
        self.anim_stored = None
        self._anim_flash_sector(0, None)

    def _anim_flush_stage(self) -> bool:
        if not self._anim_flash_sector(self.anim_up_sectors, bytes(self.anim_up_stage)):
            return False
        if self.anim_up_sectors == 0:
            self.anim_stored = None
        self.anim_up_sectors += 1
        self.anim_up_stage = bytearray(b"\xff" * FLASH_SECTOR_SIZE)
        return True

    def anim_abort(self) -> None:
        if not self.anim_up_active:
            return
        self.anim_up_active = False
        if self.anim_up_sectors > 0:
            self._anim_invalidate()
        self.anim_up_got = 0

    def _anim_release_screen(self) -> None:
        self.anim_state = "active"
        self.anim_preview_mode = 0
        self.anim_builtin_playing = False

    def _anim_info(self) -> bytes:
        st = 0x40  # region usable
        if self.anim_stored:
            st |= 0x01
        if self.anim_up_active:
            st |= 0x02
        if self.anim_state == "playing":
            st |= 0x04
            if self.anim_builtin_playing:
                st |= 0x10
        if self.anim_state == "blank":
            st |= 0x08
        if self.anim_preview_mode:
            st |= 0x20
        out = bytearray(A.INFO_SIZE)
        out[0] = st
        out[1] = A.VERSION
        if self.anim_stored:
            s = self.anim_stored
            struct.pack_into("<HBB", out, 2, s["frame_count"], s["fps"], s["flags"])
            struct.pack_into("<II", out, 6, s["total_len"], s["crc"])
            out[32:40] = s["name"].encode("ascii", "replace")[:8].ljust(8, b"\x00")
        struct.pack_into("<IH", out, 14, A.REGION_SIZE, A.MAX_FRAMES_RAW)
        struct.pack_into("<II", out, 20, 26100, 33000)  # plausible 400 kHz timings
        struct.pack_into("<I", out, 28, self.anim_up_got if self.anim_up_active else 0)
        return bytes(out)

    def _handle_anim(self, cmd: int, seq: int, length: int, raw_pl: bytes) -> bytes:
        if cmd == F.CFG_CMD_ANIM_BEGIN:
            if length < 8:
                return self._nak(seq, F.CFG_ERR_EINVAL)
            if self._anim_upload_busy_other() or self.anim_up_active:
                return self._nak(seq, F.CFG_ERR_EBUSY)
            total, crc = struct.unpack_from("<II", raw_pl, 0)
            if total < A.HEADER_SIZE + A.REC_HDR_SIZE or total > A.REGION_SIZE:
                return self._nak(seq, F.CFG_ERR_EINVAL)
            self._anim_release_screen()
            self.anim_up_active = True
            self.anim_up_total, self.anim_up_crc = total, crc
            self.anim_up_got = self.anim_up_sectors = 0
            self.anim_up_stage = bytearray(b"\xff" * FLASH_SECTOR_SIZE)
            return self._resp(cmd, seq)
        if cmd == F.CFG_CMD_ANIM_DATA:
            if length < 5 or length > 4 + F.CFG_ANIM_CHUNK_MAX or not self.anim_up_active:
                return self._nak(seq, F.CFG_ERR_EINVAL)
            (off,) = struct.unpack_from("<I", raw_pl, 0)
            data = bytes(raw_pl[4:length])
            if off != self.anim_up_got or off + len(data) > self.anim_up_total:
                return self._nak(seq, F.CFG_ERR_EINVAL)
            for b in data:
                self.anim_up_stage[self.anim_up_got % FLASH_SECTOR_SIZE] = b
                self.anim_up_got += 1
                if self.anim_up_got % FLASH_SECTOR_SIZE == 0 and not self._anim_flush_stage():
                    self.anim_abort()
                    return self._nak(seq, F.CFG_ERR_EBUSY)
            return self._resp(cmd, seq)
        if cmd == F.CFG_CMD_ANIM_COMMIT:
            if not self.anim_up_active:
                return self._nak(seq, F.CFG_ERR_EINVAL)
            if self.anim_up_got != self.anim_up_total:
                self.anim_abort()
                return self._nak(seq, F.CFG_ERR_EINVAL)
            if self.anim_up_got % FLASH_SECTOR_SIZE and not self._anim_flush_stage():
                self.anim_abort()
                return self._nak(seq, F.CFG_ERR_EBUSY)
            self.anim_up_active = False
            blob = bytes(self.anim_region[: self.anim_up_total])
            ok = F.crc32(blob) == self.anim_up_crc
            if ok:
                try:
                    parsed = A.parse_blob(blob)
                    ok = parsed.total_len == self.anim_up_total
                except A.AnimFormatError:
                    ok = False
            if not ok:
                self._anim_invalidate()
                return self._nak(seq, F.CFG_ERR_EBADMSG)
            self._anim_load_stored()
            return self._resp(cmd, seq)
        if cmd == F.CFG_CMD_ANIM_ABORT:
            self.anim_abort()
            return self._resp(cmd, seq)
        if cmd == F.CFG_CMD_ANIM_INFO:
            return self._resp(cmd, seq, self._anim_info())
        if cmd == F.CFG_CMD_ANIM_READ:
            if length < 4:
                return self._nak(seq, F.CFG_ERR_EINVAL)
            if self.anim_up_active:
                return self._nak(seq, F.CFG_ERR_EBUSY)
            (off,) = struct.unpack_from("<I", raw_pl, 0)
            if off >= A.REGION_SIZE:
                return self._nak(seq, F.CFG_ERR_EINVAL)
            chunk = bytes(self.anim_region[off : off + F.CFG_ANIM_CHUNK_MAX])
            return self._resp(cmd, seq, struct.pack("<I", off) + chunk)
        if cmd == F.CFG_CMD_ANIM_SETTINGS_GET:
            st = self.anim_settings
            return self._resp(
                cmd, seq, A.pack_settings(st["enabled"], st["idle_timeout_s"], st["blank_timeout_s"])
            )
        if cmd == F.CFG_CMD_ANIM_SETTINGS_SET:
            if length < A.SETTINGS_SIZE:
                return self._nak(seq, F.CFG_ERR_EINVAL)
            if self._anim_upload_busy_other() or self.anim_up_active:
                return self._nak(seq, F.CFG_ERR_EBUSY)
            if raw_pl[0] > 1:
                return self._nak(seq, F.CFG_ERR_EINVAL)
            self.anim_settings = A.unpack_settings(bytes(raw_pl[: A.SETTINGS_SIZE]))
            self.persist_pending = False
            if not self.save_all():
                return self._nak(seq, F.CFG_ERR_EBUSY)
            st = self.anim_settings
            return self._resp(
                cmd, seq, A.pack_settings(st["enabled"], st["idle_timeout_s"], st["blank_timeout_s"])
            )
        if cmd == F.CFG_CMD_ANIM_PREVIEW:
            if length < 1:
                return self._nak(seq, F.CFG_ERR_EINVAL)
            if self.anim_up_active:
                return self._nak(seq, F.CFG_ERR_EBUSY)
            mode = raw_pl[0]
            if mode == A.PREVIEW_STOP:
                self._anim_release_screen()
            elif mode in (A.PREVIEW_PLAY, A.PREVIEW_BUILTIN):
                self.anim_state = "playing"
                self.anim_preview_mode = mode
                self.anim_builtin_playing = mode == A.PREVIEW_BUILTIN or not self.anim_stored
            elif mode == A.PREVIEW_BLANK:
                self.anim_state = "blank"
                self.anim_preview_mode = 0
                self.anim_builtin_playing = False
            else:
                return self._nak(seq, F.CFG_ERR_EINVAL)
            return self._resp(cmd, seq, bytes([mode]))
        return self._nak(seq, F.CFG_ERR_EINVAL)

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
        self.upload_buf[offset : offset + len(data)] = data
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
        pl = req[8 : 8 + length]
        raw_pl = req[8:60]  # firmware reads payload[] past length (zero padded)

        if cmd == F.CFG_CMD_PING:
            return self._resp(cmd, seq, b"PONG")
        if cmd == F.CFG_CMD_GET_INFO:
            flags = F.CFG_INFO_FLAG_STORAGE | F.CFG_INFO_FLAG_MACRO_BANK
            if self.has_readback:
                flags |= F.CFG_INFO_FLAG_READBACK
            if self.has_anim:
                flags |= F.CFG_INFO_FLAG_ANIM
            info = (
                bytes(
                    [
                        self.fw_major,
                        self.fw_minor,
                        F.CFG_PROTO_VERSION,
                        self.active,
                        PROFILE_SLOT_COUNT,
                        flags,
                    ]
                )
                + PRODUCT_TAG
            )
            return self._resp(cmd, seq, info)
        if cmd == F.CFG_CMD_ECHO:
            return self._resp(cmd, seq, pl)

        if cmd in (F.CFG_CMD_PROFILE_BEGIN, F.CFG_CMD_MACRO_BEGIN):
            if length < 7:
                return self._nak(seq, F.CFG_ERR_EINVAL)
            if self.upload_kind != UPLOAD_NONE or self.anim_up_active:
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
            chunk = table[idx][offset : offset + F.CFG_READ_CHUNK_MAX]
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
            if self.upload_kind != UPLOAD_NONE or self.anim_up_active:
                return self._nak(seq, F.CFG_ERR_EBUSY)
            self.persist_pending = False
            if not self.save_all():
                return self._nak(seq, F.CFG_ERR_EBUSY)
            return self._resp(cmd, seq)

        if F.CFG_CMD_ANIM_BEGIN <= cmd <= F.CFG_CMD_ANIM_PREVIEW and self.has_anim:
            return self._handle_anim(cmd, seq, length, raw_pl)

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

    def __init__(
        self, firmware: Optional[MockFirmware] = None, *, api: str = "cython", present: bool = True
    ) -> None:
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
