"""Hardware-in-the-loop test suite for the vendor config HID channel (Step 23;
OLED idle-animation tests added in Step 24b).

Talks to a flashed macropad (or ``hil.mock``) through the production host
stack: ``protocol.device.ConfigDevice`` + ``protocol.frames``. No framing is
duplicated here — malformed frames are built by mutating ``pack_frame`` output.

Flash wear policy: every PROFILE/MACRO COMMIT and SAVE_ALL erases + programs
the 4 KiB storage sector. Those steps only run with ``allow_flash_write``;
everything else (NAK paths, ABORT, EBUSY, bad-CRC / bad-blob COMMITs, which
the firmware rejects *before* touching flash) is flash-free. SET_ACTIVE
schedules a debounced flash rewrite; on fw 0.23+ that rewrite is skipped when
the original slot is restored, so the active-slot test is flash-free there and
needs ``allow_flash_write`` on older firmware.

Step 24b animation tests: ANIM_INFO / PREVIEW / protocol error paths / EBUSY
are flash-free (uploads are aborted before the first 4 KiB sector fills).
ANIM_SETTINGS_SET rewrites the MPFL sector and a completed or bad-CRC
ANIM_COMMIT programs the animation region, so the settings and round-trip
tests need ``allow_flash_write``; both restore the original state.
"""

from __future__ import annotations

import random
import struct
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .. import version as ver
from ..paths import resource_root
from ..protocol import frames as F
from ..protocol.device import (
    CFG_USAGE_PAGE,
    USB_PID,
    USB_VID,
    ConfigDevice,
    DeviceError,
    err_name,
    list_config_devices,
)
from ..animation import codec as A
from ..protocol.macro_blob import MACRO_BLOB_V1_SIZE, pack_macro
from ..protocol.profile_blob import (
    PROFILE_BLOB_V1_SIZE,
    pack_profile_dict,
    unpack_profile_dict,
)

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
_REPO = resource_root()  # bundled defaults (repo root in a checkout)
HARDWARE_TEST_DOC = "docs/HARDWARE_TEST.md"


class Skip(Exception):
    """Raise inside a test to mark it SKIP with a reason."""


class Fail(AssertionError):
    """Raise inside a test to mark it FAIL."""


@dataclass
class TestResult:
    id: str
    title: str
    status: str
    detail: str = ""
    notes: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    duration_ms: float = 0.0


@dataclass
class HilOptions:
    pings: int = 20
    seed: int = 23
    allow_flash_write: bool = False
    profile_slot: Optional[int] = None   # default: (active + 1) % 5
    macro_id: int = 4
    strict_version: bool = False
    interactive: bool = False
    timeout_ms: int = 500
    only: Optional[list[str]] = None
    skip: Optional[list[str]] = None
    short_report: Optional[bool] = None  # None → auto (Linux or mock)
    path: Optional[bytes] = None


# --------------------------------------------------------------------------
# Test data
# --------------------------------------------------------------------------

def test_profile_blob() -> bytes:
    return pack_profile_dict({
        "schema_version": 1,
        "id": "hil-test",
        "name": "HIL TEST",
        "oled": {"title": "HIL TEST", "animation": "scroll"},
        "keys": {
            "1": {"type": "KEY", "key": "H"},
            "2": {"type": "SHORTCUT", "mods": ["CTRL", "SHIFT"], "key": "I"},
            "3": {"type": "MEDIA", "code": "PLAY_PAUSE"},
            "4": {"type": "VOLUME", "dir": "mute"},
            "5": {"type": "MACRO", "macro_id": 3},
            "6": {"type": "PROFILE", "slot": 1},
        },
        "encoder": {
            "cw": {"type": "VOLUME", "dir": "up"},
            "ccw": {"type": "VOLUME", "dir": "down"},
            "press": {"type": "KEY", "key": "ENTER"},
        },
    })


def test_macro_blob() -> bytes:
    return pack_macro({
        "name": "hil-test",
        "steps": [
            {"op": "TAP", "mods": ["SHIFT"], "key": "H"},
            {"op": "DELAY_MS", "arg": 20},
            {"op": "TAP", "mods": [], "key": "I"},
            {"op": "END"},
        ],
    })


def _repo_profile_candidates() -> list[bytes]:
    """Known-good profile blobs used to restore a slot when fw lacks readback."""
    import json

    out = []
    for path in sorted((_REPO / "profiles").glob("*.json")):
        try:
            out.append(pack_profile_dict(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    return out


def _repo_macro_candidates() -> list[bytes]:
    import json

    try:
        lib = json.loads((_REPO / "macros" / "library.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for m in lib.get("macros", []):
        try:
            out.append(pack_macro(m))
        except Exception:
            continue
    return out


# --------------------------------------------------------------------------
# Context
# --------------------------------------------------------------------------

class HilContext:
    def __init__(self, opts: HilOptions, *, hid_module=None, mock: bool = False,
                 prompt: Optional[Callable[[str], str]] = None,
                 log: Optional[Callable[[str], None]] = None) -> None:
        self.opts = opts
        self.hid_module = hid_module
        self.mock = mock
        self.prompt = prompt or input
        self.log = log or (lambda _msg: None)
        self.dev: Optional[ConfigDevice] = None
        self.devices: list[dict] = []
        self.info: dict = {}
        self.readback = False
        self.orig_active: Optional[int] = None
        self.orig_profile_crc: dict[int, int] = {}
        self.orig_macro_crc: dict[int, int] = {}
        self.rng = random.Random(opts.seed)
        self.notes: list[str] = []
        # Step 24b
        self.anim = False
        self.orig_anim_info: Optional[dict] = None
        self.orig_anim_settings: Optional[dict] = None
        self.orig_anim_blob: Optional[bytes] = None

    # -- helpers ------------------------------------------------------------
    def req(self, cmd: int, payload: bytes = b"", *, timeout_ms: Optional[int] = None) -> F.Frame:
        assert self.dev is not None
        if timeout_ms is None:
            return self.dev.request(cmd, payload)
        old = self.dev.timeout_ms
        self.dev.timeout_ms = timeout_ms
        try:
            return self.dev.request(cmd, payload)
        finally:
            self.dev.timeout_ms = old

    def expect_ok(self, resp: F.Frame, cmd: int, what: str) -> F.Frame:
        if resp.cmd == F.CFG_CMD_NAK:
            code = resp.payload[0] if resp.payload else -1
            raise Fail(f"{what}: expected OK, got NAK {err_name(code)} ({code})")
        if resp.cmd != cmd:
            raise Fail(f"{what}: expected cmd 0x{cmd:02X}, got 0x{resp.cmd:02X}")
        return resp

    def expect_nak(self, resp: F.Frame, code: int, what: str) -> None:
        if resp.cmd != F.CFG_CMD_NAK:
            raise Fail(f"{what}: expected NAK {err_name(code)}, got OK cmd 0x{resp.cmd:02X}")
        got = resp.payload[0] if resp.payload else -1
        if got != code:
            raise Fail(f"{what}: expected NAK {err_name(code)} ({code}), got {err_name(got)} ({got})")

    def check(self, cond: bool, msg: str) -> None:
        if not cond:
            raise Fail(msg)

    def need_device(self) -> None:
        if self.dev is None:
            raise Skip("no device open")

    def meta(self, kind: str, idx: int) -> dict:
        assert self.dev is not None
        return self.dev.profile_get_meta(idx) if kind == "profile" else self.dev.macro_get_meta(idx)

    def abort_uploads(self) -> None:
        if self.dev is None:
            return
        cmds = [F.CFG_CMD_PROFILE_ABORT, F.CFG_CMD_MACRO_ABORT]
        if self.anim:
            cmds.append(F.CFG_CMD_ANIM_ABORT)
        for cmd in cmds:
            try:
                self.dev.request(cmd)
            except DeviceError:
                pass


def _crc(b: bytes) -> int:
    return F.crc32(b)


def _mutate(frame: bytes, *, at: int, value: int, fix_crc: bool) -> bytes:
    b = bytearray(frame)
    b[at] = value & 0xFF
    if fix_crc:
        b[60:64] = struct.pack("<I", F.crc32(bytes(b[:60])))
    return bytes(b)


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

def t_enumerate(ctx: HilContext, res: TestResult) -> None:
    devices = list_config_devices(USB_VID, USB_PID, hid_module=ctx.hid_module)
    ctx.devices = devices
    res.metrics["interfaces"] = len(devices)
    if not devices:
        raise Fail(f"no HID interfaces with VID={USB_VID:#06x} PID={USB_PID:#06x}")
    cfg = [d for d in devices if d.get("_match_config")]
    for d in devices:
        vid, pid = int(d.get("vendor_id", 0)), int(d.get("product_id", 0))
        ctx.check((vid, pid) == (USB_VID, USB_PID), f"enumerate returned foreign {vid:#06x}:{pid:#06x}")
    if not cfg:
        raise Fail(f"device present but no interface with usage page {CFG_USAGE_PAGE:#06x}")
    target = cfg[0]
    path = ctx.opts.path or target["path"]
    bcd = target.get("release_number")
    if bcd is not None:
        res.metrics["bcdDevice"] = f"0x{int(bcd):04X}"
    res.metrics["path"] = path.decode("latin-1") if isinstance(path, bytes) else str(path)
    dev = ConfigDevice(path=path, timeout_ms=ctx.opts.timeout_ms, hid_module=ctx.hid_module)
    dev.open()
    ctx.dev = dev
    res.detail = f"{len(devices)} interface(s); config IF opened ({res.metrics['path']})"


def t_ping(ctx: HilContext, res: TestResult) -> None:
    ctx.need_device()
    n = max(1, int(ctx.opts.pings))
    lat = []
    for _ in range(n):
        t0 = time.perf_counter()
        resp = ctx.req(F.CFG_CMD_PING)
        lat.append((time.perf_counter() - t0) * 1000.0)
        ctx.expect_ok(resp, F.CFG_CMD_PING, "PING")
        ctx.check(resp.payload == b"PONG", f"PING payload {resp.payload!r} != b'PONG'")
    res.metrics.update(
        count=n,
        min_ms=round(min(lat), 3),
        avg_ms=round(sum(lat) / n, 3),
        max_ms=round(max(lat), 3),
    )
    res.detail = (f"{n} pings  min/avg/max = {res.metrics['min_ms']:.2f}/"
                  f"{res.metrics['avg_ms']:.2f}/{res.metrics['max_ms']:.2f} ms")


def t_info(ctx: HilContext, res: TestResult) -> None:
    ctx.need_device()
    assert ctx.dev is not None
    info = ctx.dev.get_info(seq=0x42)
    ctx.info = info
    res.metrics.update(info)
    ok, msg = ver.check_proto_ver(info.get("proto_ver"))
    if not ok:
        raise Fail(msg)
    major, minor = info["fw_major"], info["fw_minor"]
    if major != ver.FW_VERSION_MAJOR_EXPECTED:
        raise Fail(f"fw major {major} != expected {ver.FW_VERSION_MAJOR_EXPECTED}")
    if minor != ver.FW_VERSION_MINOR_CURRENT:
        msg = (f"fw {major}.{minor} != host-expected {major}.{ver.FW_VERSION_MINOR_CURRENT} "
               f"(host {ver.HOST_APP_VERSION})")
        if ctx.opts.strict_version:
            raise Fail(msg + " [--strict-version]")
        res.notes.append("WARN " + msg)
    ctx.check(info["product_tag"] == "MACROPAD", f"product tag {info['product_tag']!r}")
    ctx.check(info["slot_count"] == 5, f"slot_count {info['slot_count']} != 5")
    ctx.check(info["active_slot"] < info["slot_count"], f"active_slot {info['active_slot']} out of range")
    flags = info["flags"]
    ctx.check(bool(flags & F.CFG_INFO_FLAG_STORAGE), "flags: storage bit0 missing")
    ctx.check(bool(flags & F.CFG_INFO_FLAG_MACRO_BANK), "flags: macro bank bit1 missing")
    ctx.readback = bool(flags & F.CFG_INFO_FLAG_READBACK)
    if ctx.readback != ver.fw_supports_readback(major, minor):
        res.notes.append(f"WARN readback flag={ctx.readback} but fw {major}.{minor} "
                         f"{'≥' if ver.fw_supports_readback(major, minor) else '<'} 0.{ver.MIN_FW_MINOR_READBACK}")
    gates = {
        "upload": ver.fw_supports_upload(major, minor),
        "macro_upload": ver.fw_supports_macro_upload(major, minor),
        "autoswitch": ver.fw_supports_autoswitch(major, minor),
        "save_all": ver.fw_supports_save_all(major, minor),
        "readback": ctx.readback,
        "anim": bool(flags & F.CFG_INFO_FLAG_ANIM),
    }
    ctx.anim = bool(flags & F.CFG_INFO_FLAG_ANIM)
    if ctx.anim != ver.fw_supports_anim(major, minor):
        res.notes.append(f"WARN anim flag={ctx.anim} but fw {major}.{minor}")
    res.metrics["features"] = gates
    ctx.orig_active = info["active_slot"]
    # Snapshot for restore_check.
    for i in range(5):
        ctx.orig_profile_crc[i] = ctx.meta("profile", i)["crc"]
        ctx.orig_macro_crc[i] = ctx.meta("macro", i)["crc"]
    res.detail = (f"fw {major}.{minor} proto v{info['proto_ver']} tag {info['product_tag']} "
                  f"active {info['active_slot']}/{info['slot_count']} flags 0x{flags:02X} "
                  f"({'readback' if ctx.readback else 'no readback'}) — {ver.compat_summary(info)}")


def t_echo(ctx: HilContext, res: TestResult) -> None:
    ctx.need_device()
    assert ctx.dev is not None
    lengths = [0, 1, 2, 7, 16, 31, 51, F.CFG_PAYLOAD_MAX]
    lengths += [ctx.rng.randint(0, F.CFG_PAYLOAD_MAX) for _ in range(8)]
    for n in lengths:
        payload = bytes(ctx.rng.getrandbits(8) for _ in range(n))
        got = ctx.dev.echo(payload)
        ctx.check(got == payload, f"ECHO len {n}: mismatch {got.hex()} != {payload.hex()}")
    res.metrics["payloads"] = len(lengths)
    res.metrics["max_len"] = F.CFG_PAYLOAD_MAX
    # CRC error injection.
    base = F.pack_frame(F.CFG_CMD_ECHO, 0x5A, b"crc-injection")
    bad_crc = _mutate(base, at=61, value=base[61] ^ 0xFF, fix_crc=False)
    resp = ctx.dev.exchange_raw(bad_crc)
    ctx.expect_nak(resp, F.CFG_ERR_EBADMSG, "ECHO with corrupted CRC")
    ctx.check(resp.seq == 0x5A, f"NAK seq {resp.seq} != 0x5A")
    bad_pl = _mutate(base, at=9, value=base[9] ^ 0x01, fix_crc=False)
    ctx.expect_nak(ctx.dev.exchange_raw(bad_pl), F.CFG_ERR_EBADMSG, "ECHO with flipped payload bit")
    res.detail = f"{len(lengths)} random payloads (0..{F.CFG_PAYLOAD_MAX} B) echoed; CRC/payload corruption → NAK EBADMSG"


def t_malformed(ctx: HilContext, res: TestResult) -> None:
    ctx.need_device()
    assert ctx.dev is not None
    dev = ctx.dev
    checks = 0
    # Unknown commands → EINVAL (firmware never emits ENOSYS).
    unknown = [0x00, 0x04, 0x0F, 0x16, 0x26, 0x33, 0x55, 0x7E, F.CFG_CMD_NAK]
    if not ctx.readback:
        unknown += [F.CFG_CMD_PROFILE_READ, F.CFG_CMD_MACRO_READ]
    for cmd in unknown:
        ctx.expect_nak(ctx.req(cmd), F.CFG_ERR_EINVAL, f"unknown cmd 0x{cmd:02X}")
        checks += 1
    ping = F.pack_frame(F.CFG_CMD_PING, 0x33)
    # Bad magic (with and without a matching CRC) → EBADMSG, seq echoed.
    for fix in (False, True):
        resp = dev.exchange_raw(_mutate(ping, at=0, value=0x00, fix_crc=fix))
        ctx.expect_nak(resp, F.CFG_ERR_EBADMSG, f"bad magic (crc {'fixed' if fix else 'stale'})")
        ctx.check(resp.seq == 0x33, f"bad-magic NAK seq {resp.seq} != 0x33")
        checks += 1
    # Bad protocol version → EINVAL.
    ctx.expect_nak(dev.exchange_raw(F.pack_frame(F.CFG_CMD_PING, 0x34, version=2)),
                   F.CFG_ERR_EINVAL, "bad version 2")
    checks += 1
    # length > 52 → EINVAL.
    ctx.expect_nak(dev.exchange_raw(_mutate(ping, at=6, value=F.CFG_PAYLOAD_MAX + 1, fix_crc=True)),
                   F.CFG_ERR_EINVAL, "length 53")
    checks += 1
    # seq: firmware has no sequence validation — it echoes whatever the host sends.
    for seq in (0x00, 0x7F, 0x80, 0xFF):
        resp = dev.transact(F.CFG_CMD_PING, seq)
        ctx.expect_ok(resp, F.CFG_CMD_PING, f"PING seq {seq}")
        checks += 1
    res.notes.append("seq is echo-only (no device-side 'bad seq' NAK); host transact() rejects mismatches")
    # Host frame with FLAG_RESPONSE → silently ignored (no reply), device still alive.
    dev.write_frame(F.pack_frame(F.CFG_CMD_PING, 0x35, flags=F.CFG_FLAG_RESPONSE))
    try:
        stray = dev.read_frame(timeout_ms=200)
        raise Fail(f"frame with FLAG_RESPONSE got a reply: {stray[:8].hex()}")
    except DeviceError:
        pass
    ctx.expect_ok(ctx.req(F.CFG_CMD_PING), F.CFG_CMD_PING, "PING after ignored frame")
    checks += 1
    # Short OUT report (<64 B) → EBADMSG. Only reliable on Linux hidraw / mock.
    short = ctx.opts.short_report
    if short is None:
        short = ctx.mock or sys.platform.startswith("linux")
    if short:
        raw = ping[:32]
        dev._dev.write(b"\x00" + raw)  # bypass write_frame's 64-byte guard on purpose
        resp = F.unpack_frame(dev.read_frame())
        ctx.expect_nak(resp, F.CFG_ERR_EBADMSG, "short 32-byte OUT report")
        checks += 1
    else:
        res.notes.append("short-report check skipped (non-Linux hidapi pads/rejects short writes)")
    res.metrics["checks"] = checks
    res.detail = (f"{checks} checks: unknown cmd→EINVAL, bad magic→EBADMSG, bad version→EINVAL, "
                  f"len>52→EINVAL, seq echo, FLAG_RESPONSE ignored"
                  + (", short report→EBADMSG" if short else ""))


def _upload_protocol_checks(ctx: HilContext, kind: str, idx: int) -> int:
    """Flash-free BEGIN/DATA/COMMIT/ABORT error paths for one kind."""
    P = kind == "profile"
    size = PROFILE_BLOB_V1_SIZE if P else MACRO_BLOB_V1_SIZE
    BEGIN = F.CFG_CMD_PROFILE_BEGIN if P else F.CFG_CMD_MACRO_BEGIN
    DATA = F.CFG_CMD_PROFILE_DATA if P else F.CFG_CMD_MACRO_DATA
    COMMIT = F.CFG_CMD_PROFILE_COMMIT if P else F.CFG_CMD_MACRO_COMMIT
    ABORT = F.CFG_CMD_PROFILE_ABORT if P else F.CFG_CMD_MACRO_ABORT
    GET = F.CFG_CMD_PROFILE_GET if P else F.CFG_CMD_MACRO_GET
    READ = F.CFG_CMD_PROFILE_READ if P else F.CFG_CMD_MACRO_READ
    L = kind.upper()
    blob = test_profile_blob() if P else test_macro_blob()
    crc = _crc(blob)
    n = 0

    def begin(i=idx, total=size, c=crc):
        return ctx.req(BEGIN, struct.pack("<BHI", i, total, c))

    def data(off, chunk):
        return ctx.req(DATA, struct.pack("<H", off) + chunk)

    def send_all(b):
        for off in range(0, size, 50):
            ctx.expect_ok(data(off, b[off:off + 50]), DATA, f"{L}_DATA@{off}")

    before = ctx.meta(kind, idx)
    ctx.check(before["len"] == size, f"{L}_GET len {before['len']} != {size}")
    for i in range(5):
        m = ctx.meta(kind, i)
        ctx.check(m["len"] == size, f"{L}_GET[{i}] len {m['len']}")
        n += 1
    ctx.expect_nak(ctx.req(GET, bytes([5])), F.CFG_ERR_EINVAL, f"{L}_GET id 5"); n += 1
    ctx.expect_nak(ctx.req(GET, b""), F.CFG_ERR_EINVAL, f"{L}_GET empty payload"); n += 1
    if ctx.readback:
        assert ctx.dev is not None
        cur = ctx.dev.profile_read(idx) if P else ctx.dev.macro_read(idx)
        ctx.check(_crc(cur) == before["crc"],
                  f"{L}_READ crc 0x{_crc(cur):08X} != {L}_GET crc 0x{before['crc']:08X}")
        ctx.expect_nak(ctx.req(READ, struct.pack("<BH", idx, size)), F.CFG_ERR_EINVAL, f"{L}_READ offset {size}")
        ctx.expect_nak(ctx.req(READ, struct.pack("<BH", 5, 0)), F.CFG_ERR_EINVAL, f"{L}_READ id 5")
        ctx.expect_nak(ctx.req(READ, bytes([idx])), F.CFG_ERR_EINVAL, f"{L}_READ short payload")
        n += 4
    # BEGIN validation.
    ctx.expect_nak(begin(i=5), F.CFG_ERR_EINVAL, f"{L}_BEGIN id 5")
    ctx.expect_nak(begin(total=size - 1), F.CFG_ERR_EINVAL, f"{L}_BEGIN len {size - 1}")
    ctx.expect_nak(ctx.req(BEGIN, struct.pack("<BHI", idx, size, crc)[:6]), F.CFG_ERR_EINVAL, f"{L}_BEGIN 6-byte payload")
    # No upload open.
    ctx.expect_nak(data(0, blob[:10]), F.CFG_ERR_EINVAL, f"{L}_DATA without BEGIN")
    ctx.expect_nak(ctx.req(COMMIT), F.CFG_ERR_EINVAL, f"{L}_COMMIT without BEGIN")
    ctx.expect_ok(ctx.req(ABORT), ABORT, f"{L}_ABORT when idle")
    n += 6
    # ABORT mid-upload.
    ctx.expect_ok(begin(), BEGIN, f"{L}_BEGIN")
    ctx.expect_nak(begin(), F.CFG_ERR_EBUSY, f"second {L}_BEGIN")
    ctx.expect_ok(data(0, blob[:50]), DATA, f"{L}_DATA@0")
    ctx.expect_nak(data(size - 10, blob[:20]), F.CFG_ERR_EINVAL, f"{L}_DATA past end")
    ctx.expect_nak(ctx.req(DATA, b"\x00"), F.CFG_ERR_EINVAL, f"{L}_DATA 1-byte payload")
    ctx.expect_ok(ctx.req(ABORT), ABORT, f"{L}_ABORT mid-upload")
    ctx.expect_nak(data(50, blob[50:100]), F.CFG_ERR_EINVAL, f"{L}_DATA after ABORT")
    n += 7
    # Incomplete COMMIT → EINVAL and staging auto-aborted.
    ctx.expect_ok(begin(), BEGIN, f"{L}_BEGIN")
    ctx.expect_ok(data(0, blob[:50]), DATA, f"{L}_DATA@0")
    ctx.expect_nak(ctx.req(COMMIT), F.CFG_ERR_EINVAL, f"{L}_COMMIT incomplete")
    ctx.expect_nak(data(50, blob[50:100]), F.CFG_ERR_EINVAL, f"{L}_DATA after failed COMMIT (auto-abort)")
    n += 2
    # Wrong declared CRC → EBADMSG (checked before any flash write).
    ctx.expect_ok(begin(c=crc ^ 0xDEADBEEF), BEGIN, f"{L}_BEGIN wrong crc")
    send_all(blob)
    ctx.expect_nak(ctx.req(COMMIT), F.CFG_ERR_EBADMSG, f"{L}_COMMIT crc mismatch")
    n += 1
    # CRC-valid but un-unpackable blob → EINVAL (still before flash).
    bad = bytearray(blob)
    if P:
        bad[0:2] = struct.pack("<H", 2)      # schema_version 2
    else:
        bad[16] = 0                          # step_count 0
    bad = bytes(bad)
    ctx.expect_ok(begin(c=_crc(bad)), BEGIN, f"{L}_BEGIN bad blob")
    send_all(bad)
    ctx.expect_nak(ctx.req(COMMIT), F.CFG_ERR_EINVAL, f"{L}_COMMIT {'schema 2' if P else 'step_count 0'}")
    n += 1
    # Nothing changed.
    after = ctx.meta(kind, idx)
    ctx.check(after == before, f"{L} slot {idx} changed by flash-free checks: {before} → {after}")
    return n


def _find_restore_blob(ctx: HilContext, kind: str, idx: int, want_crc: int) -> tuple[Optional[bytes], str]:
    assert ctx.dev is not None
    if ctx.readback:
        blob = ctx.dev.profile_read(idx) if kind == "profile" else ctx.dev.macro_read(idx)
        return blob, "readback"
    cands = _repo_profile_candidates() if kind == "profile" else _repo_macro_candidates()
    for b in cands:
        if _crc(b) == want_crc:
            return b, "repo match"
    return None, "none"


def _roundtrip(ctx: HilContext, res: TestResult, kind: str, idx: int) -> None:
    ctx.need_device()
    assert ctx.dev is not None
    if not ctx.opts.allow_flash_write:
        raise Skip("COMMIT writes flash — rerun with --allow-flash-write")
    P = kind == "profile"
    L = kind.upper()
    orig = ctx.meta(kind, idx)
    backup, how = _find_restore_blob(ctx, kind, idx, orig["crc"])
    if backup is None:
        raise Skip(f"cannot back up {kind} {idx} (fw lacks readback, no repo blob matches "
                   f"crc 0x{orig['crc']:08X}) — refusing to overwrite")
    ctx.check(_crc(backup) == orig["crc"], f"backup crc mismatch ({how})")
    blob = test_profile_blob() if P else test_macro_blob()
    ctx.check(_crc(blob) != orig["crc"], f"test blob identical to slot {idx}; pick another slot")
    upload = ctx.dev.upload_profile if P else ctx.dev.upload_macro
    try:
        upload(idx, blob)
        got = ctx.meta(kind, idx)
        ctx.check(got["crc"] == _crc(blob),
                  f"{L}_GET crc 0x{got['crc']:08X} != uploaded 0x{_crc(blob):08X} "
                  "(host/firmware canonicalisation divergence?)")
        if ctx.readback:
            rb = ctx.dev.profile_read(idx) if P else ctx.dev.macro_read(idx)
            if rb != blob:
                diff = [i for i in range(len(blob)) if rb[i] != blob[i]]
                raise Fail(f"{L}_READ differs from uploaded blob at bytes {diff[:12]}")
            res.notes.append(f"readback byte-compare OK ({len(blob)} B)")
        else:
            res.notes.append("byte-compare via CRC only (fw < 0.23, no readback)")
    finally:
        # Always try to restore, even after a failure above.
        upload(idx, backup)
    restored = ctx.meta(kind, idx)
    ctx.check(restored["crc"] == orig["crc"],
              f"restore failed: crc 0x{restored['crc']:08X} != original 0x{orig['crc']:08X}")
    res.metrics.update(slot=idx, backup=how, flash_writes=2,
                       test_crc=f"0x{_crc(blob):08X}", orig_crc=f"0x{orig['crc']:08X}")
    res.detail = (f"{L} {idx}: backup ({how}) → upload test blob → verify → restore original "
                  f"(2 flash writes)")


def _profile_slot(ctx: HilContext) -> int:
    if ctx.opts.profile_slot is not None:
        return int(ctx.opts.profile_slot)
    return ((ctx.orig_active or 0) + 1) % 5


def t_profile_protocol(ctx: HilContext, res: TestResult) -> None:
    ctx.need_device()
    slot = _profile_slot(ctx)
    n = _upload_protocol_checks(ctx, "profile", slot)
    res.metrics.update(slot=slot, checks=n)
    res.detail = (f"slot {slot}: GET meta ×5, {'READ, ' if ctx.readback else ''}BEGIN/DATA validation, "
                  f"ABORT mid-upload, incomplete/bad-CRC/bad-schema COMMIT rejected; slot unchanged "
                  f"({n} checks, no flash writes)")


def t_profile_roundtrip(ctx: HilContext, res: TestResult) -> None:
    _roundtrip(ctx, res, "profile", _profile_slot(ctx))


def t_macro_protocol(ctx: HilContext, res: TestResult) -> None:
    ctx.need_device()
    mid = int(ctx.opts.macro_id)
    pslot = _profile_slot(ctx)
    n = _upload_protocol_checks(ctx, "macro", mid)
    blob_p = test_profile_blob()
    blob_m = test_macro_blob()
    pbegin = struct.pack("<BHI", pslot, PROFILE_BLOB_V1_SIZE, _crc(blob_p))
    mbegin = struct.pack("<BHI", mid, MACRO_BLOB_V1_SIZE, _crc(blob_m))
    try:
        # Profile upload open → macro BEGIN / SAVE_ALL busy.
        ctx.expect_ok(ctx.req(F.CFG_CMD_PROFILE_BEGIN, pbegin), F.CFG_CMD_PROFILE_BEGIN, "PROFILE_BEGIN")
        ctx.expect_nak(ctx.req(F.CFG_CMD_MACRO_BEGIN, mbegin), F.CFG_ERR_EBUSY, "MACRO_BEGIN while profile open")
        ctx.expect_nak(ctx.req(F.CFG_CMD_SAVE_ALL), F.CFG_ERR_EBUSY, "SAVE_ALL while profile open")
        ctx.expect_nak(ctx.req(F.CFG_CMD_MACRO_COMMIT), F.CFG_ERR_EINVAL, "MACRO_COMMIT while profile open")
        ctx.expect_ok(ctx.req(F.CFG_CMD_MACRO_ABORT), F.CFG_CMD_MACRO_ABORT, "MACRO_ABORT (no-op) while profile open")
        ctx.expect_nak(ctx.req(F.CFG_CMD_MACRO_BEGIN, mbegin), F.CFG_ERR_EBUSY, "profile upload survives MACRO_ABORT")
        if ctx.readback or ctx.opts.allow_flash_write:
            # SET_ACTIVE stays OK during uploads (RAM only). Same slot → no net change.
            ctx.expect_ok(ctx.req(F.CFG_CMD_SET_ACTIVE, bytes([ctx.orig_active or 0])),
                          F.CFG_CMD_SET_ACTIVE, "SET_ACTIVE during upload")
            n += 1
        ctx.expect_ok(ctx.req(F.CFG_CMD_PROFILE_ABORT), F.CFG_CMD_PROFILE_ABORT, "PROFILE_ABORT")
        # Macro upload open → profile BEGIN / SAVE_ALL busy.
        ctx.expect_ok(ctx.req(F.CFG_CMD_MACRO_BEGIN, mbegin), F.CFG_CMD_MACRO_BEGIN, "MACRO_BEGIN")
        ctx.expect_nak(ctx.req(F.CFG_CMD_PROFILE_BEGIN, pbegin), F.CFG_ERR_EBUSY, "PROFILE_BEGIN while macro open")
        ctx.expect_nak(ctx.req(F.CFG_CMD_SAVE_ALL), F.CFG_ERR_EBUSY, "SAVE_ALL while macro open")
        ctx.expect_nak(ctx.req(F.CFG_CMD_PROFILE_COMMIT), F.CFG_ERR_EINVAL, "PROFILE_COMMIT while macro open")
        ctx.expect_nak(ctx.req(F.CFG_CMD_PROFILE_DATA, b"\x00\x00" + blob_p[:8]), F.CFG_ERR_EINVAL,
                       "PROFILE_DATA while macro open")
        ctx.expect_ok(ctx.req(F.CFG_CMD_MACRO_ABORT), F.CFG_CMD_MACRO_ABORT, "MACRO_ABORT")
        n += 12
    finally:
        ctx.abort_uploads()
    res.metrics.update(macro_id=mid, checks=n)
    res.detail = (f"macro {mid}: same error paths as profile + EBUSY mutex both ways, SAVE_ALL EBUSY "
                  f"while uploading, cross-kind COMMIT/DATA → EINVAL ({n} checks, no flash writes)")


def t_macro_roundtrip(ctx: HilContext, res: TestResult) -> None:
    _roundtrip(ctx, res, "macro", int(ctx.opts.macro_id))


def t_active(ctx: HilContext, res: TestResult) -> None:
    ctx.need_device()
    assert ctx.dev is not None
    if not ctx.readback and not ctx.opts.allow_flash_write:
        raise Skip("fw < 0.23 persists every SET_ACTIVE to flash (debounced) — rerun with --allow-flash-write")
    orig = ctx.dev.get_active_slot()
    ctx.check(orig == ctx.orig_active, f"GET_ACTIVE {orig} != GET_INFO active {ctx.orig_active}")
    order = [(orig + k) % 5 for k in range(1, 6)]  # ends on orig
    try:
        for slot in order:
            ctx.dev.set_active_slot(slot)
            got = ctx.dev.get_active_slot()
            ctx.check(got == slot, f"GET_ACTIVE {got} after SET_ACTIVE {slot}")
            info_slot = ctx.dev.get_info(seq=0x50 + slot)["active_slot"]
            ctx.check(info_slot == slot, f"GET_INFO.active_slot {info_slot} after SET_ACTIVE {slot}")
        ctx.expect_nak(ctx.req(F.CFG_CMD_SET_ACTIVE, bytes([5])), F.CFG_ERR_EINVAL, "SET_ACTIVE 5")
        ctx.expect_nak(ctx.req(F.CFG_CMD_SET_ACTIVE, b""), F.CFG_ERR_EINVAL, "SET_ACTIVE empty")
    finally:
        ctx.dev.set_active_slot(orig)
    ctx.check(ctx.dev.get_active_slot() == orig, "active slot not restored")
    res.metrics.update(original=orig, cycled=order)
    if ctx.readback:
        res.notes.append("fw 0.23+: debounced persist is skipped when flash already holds this slot")
    else:
        res.notes.append("fw < 0.23: one debounced flash rewrite ~4 s after the last SET_ACTIVE")
    res.detail = f"cycled {order} (GET_ACTIVE + GET_INFO agree), bad slot/empty → EINVAL, restored {orig}"


def t_save_all(ctx: HilContext, res: TestResult) -> None:
    ctx.need_device()
    if not ctx.opts.allow_flash_write:
        raise Skip("SAVE_ALL erases/programs the storage sector — rerun with --allow-flash-write")
    before = {i: ctx.meta("profile", i)["crc"] for i in range(5)}
    t0 = time.perf_counter()
    resp = ctx.req(F.CFG_CMD_SAVE_ALL, timeout_ms=3000)
    ms = (time.perf_counter() - t0) * 1000.0
    ctx.expect_ok(resp, F.CFG_CMD_SAVE_ALL, "SAVE_ALL")
    after = {i: ctx.meta("profile", i)["crc"] for i in range(5)}
    ctx.check(before == after, "profile CRCs changed across SAVE_ALL")
    ctx.expect_ok(ctx.req(F.CFG_CMD_PING), F.CFG_CMD_PING, "PING after SAVE_ALL")
    res.metrics.update(save_ms=round(ms, 1), flash_writes=1)
    res.detail = f"SAVE_ALL OK in {ms:.1f} ms; RAM state unchanged (1 flash write)"


_KEY_ORDER = [str(i) for i in range(1, 13)]


def _describe_action(a: dict) -> str:
    t = a.get("type", "DISABLED")
    extra = {k: v for k, v in a.items() if k != "type" and v not in (None, "", [], 0)}
    return t + (f" {extra}" if extra else "")


def t_interactive(ctx: HilContext, res: TestResult) -> None:
    if not ctx.opts.interactive:
        raise Skip(f"manual checks: run with --interactive, then follow {HARDWARE_TEST_DOC}")
    ctx.need_device()
    assert ctx.dev is not None
    # Keyboard/consumer reports on IF0 are not reliably host-readable (Windows and
    # macOS grab keyboard HID interfaces), so this is a guided checklist: the tool
    # shows what each control should do (from device readback) and the tester
    # answers y / n / s(kip) / q(uit).
    active = ctx.dev.get_active_slot()
    prof = None
    if ctx.readback:
        try:
            prof = unpack_profile_dict(ctx.dev.profile_read(active))
        except Exception as exc:  # unknown action values etc.
            res.notes.append(f"could not decode active profile: {exc}")
    items: list[tuple[str, str]] = []
    for k in _KEY_ORDER:
        exp = _describe_action(prof["keys"][k]) if prof else "see active profile"
        items.append((f"key {k}", exp))
    for e in ("cw", "ccw", "press"):
        exp = _describe_action(prof["encoder"][e]) if prof else "see active profile"
        items.append((f"encoder {e}", exp))
    passed, failed, skipped = [], [], []
    title = prof["name"] if prof else f"slot {active}"
    ctx.log(f"Interactive: active profile {title!r}. Focus a scratch text editor, "
            "press each control, answer y/n/s/q.")
    for name, exp in items:
        try:
            ans = (ctx.prompt(f"  {name:<12} expect {exp} — OK? [y/n/s/q] ") or "").strip().lower()
        except EOFError:  # stdin closed → treat as quit
            ans = "q"
        if ans.startswith("q"):
            skipped += [n for n, _ in items[len(passed) + len(failed) + len(skipped):]]
            break
        (passed if ans.startswith("y") else failed if ans.startswith("n") else skipped).append(name)
    res.metrics.update(passed=len(passed), failed=failed, skipped=len(skipped))
    res.notes.append(f"remaining manual checks (OLED, reconnect, flash persistence): {HARDWARE_TEST_DOC}")
    if failed:
        raise Fail(f"tester reported failures: {', '.join(failed)}")
    if not passed:
        raise Skip("no controls confirmed")
    res.detail = f"{len(passed)} controls confirmed, {len(skipped)} skipped (profile {title!r})"


def t_restore_check(ctx: HilContext, res: TestResult) -> None:
    ctx.need_device()
    assert ctx.dev is not None
    if ctx.orig_active is None:
        raise Skip("no baseline (info test did not run)")
    ctx.abort_uploads()
    active = ctx.dev.get_active_slot()
    if active != ctx.orig_active:
        ctx.dev.set_active_slot(ctx.orig_active)
        res.notes.append(f"active slot was {active}; re-set to {ctx.orig_active}")
        active = ctx.dev.get_active_slot()
    ctx.check(active == ctx.orig_active, f"active slot {active} != original {ctx.orig_active}")
    diffs = []
    for i in range(5):
        if ctx.meta("profile", i)["crc"] != ctx.orig_profile_crc.get(i):
            diffs.append(f"profile {i}")
        if ctx.meta("macro", i)["crc"] != ctx.orig_macro_crc.get(i):
            diffs.append(f"macro {i}")
    anim_note = ""
    if ctx.anim and ctx.orig_anim_info is not None:
        ai = ctx.dev.anim_info()
        o = ctx.orig_anim_info
        if (ai["stored_valid"], ai["crc"] if ai["stored_valid"] else 0) != \
                (o["stored_valid"], o["crc"] if o["stored_valid"] else 0):
            diffs.append("stored animation")
        if ai["uploading"]:
            diffs.append("animation upload still open")
        if ctx.orig_anim_settings is not None and ctx.dev.anim_settings_get() != ctx.orig_anim_settings:
            diffs.append("idle settings")
        anim_note = "; animation + idle settings identical"
    if diffs:
        raise Fail(f"device state differs from start: {', '.join(diffs)}")
    res.detail = (f"active slot {active}, 5 profile + 5 macro CRCs identical to start{anim_note}; "
                  "no upload open")


# --------------------------------------------------------------------------
# Step 24b — OLED idle animation
# --------------------------------------------------------------------------

def _need_anim(ctx: HilContext) -> None:
    ctx.need_device()
    if not ctx.anim:
        raise Skip(f"firmware lacks OLED idle animation (GET_INFO flag bit3, fw 0.{ver.MIN_FW_MINOR_ANIM}+)")


def hil_anim_blob(frames: int = 12) -> bytes:
    """Small deterministic test animation (bouncing 'HIL' text)."""
    from ..animation import presets as P

    fr, _fps = P.bouncing_text("HIL", frames=frames, scale=2)
    return A.build_blob(fr, 10, loop=True, name="hiltest")


def t_anim_info(ctx: HilContext, res: TestResult) -> None:
    _need_anim(ctx)
    assert ctx.dev is not None
    info = ctx.dev.anim_info()
    ctx.orig_anim_info = info
    ctx.orig_anim_settings = ctx.dev.anim_settings_get()
    ctx.check(info["region_size"] == A.REGION_SIZE, f"region_size {info['region_size']} != {A.REGION_SIZE}")
    ctx.check(info["max_frames_raw"] == A.MAX_FRAMES_RAW, f"max_frames_raw {info['max_frames_raw']}")
    ctx.check(info["format_version"] == A.VERSION, f"format version {info['format_version']}")
    ctx.check(not info["uploading"], "an animation upload is already open")
    ctx.check(info["region_ok"], "firmware reports the animation region overlaps the image")
    if info["stored_valid"]:
        blob = ctx.dev.anim_download()
        ctx.check(blob is not None and len(blob) == info["total_len"], "ANIM_READ length mismatch")
        ctx.check(F.crc32(blob) == info["crc"], "ANIM_READ CRC != ANIM_INFO crc")
        parsed = A.parse_blob(blob)
        ctx.check(len(parsed.frames) == info["frame_count"], "frame_count mismatch")
        ctx.orig_anim_blob = blob
    res.metrics.update(info=info, settings=ctx.orig_anim_settings)
    stored = (f"stored '{info['name']}' {info['frame_count']} frames @ {info['fps']} fps "
              f"{info['total_len']} B (read back + parsed)" if info["stored_valid"] else "no stored animation")
    t = ""
    if info["last_frame_bus_us"]:
        t = f"; last OLED frame {info['last_frame_bus_us']} us bus / {info['last_frame_wall_us']} us wall"
    s = ctx.orig_anim_settings
    res.detail = (f"{stored}; settings enabled={s['enabled']} idle={s['idle_timeout_s']} s "
                  f"blank={s['blank_timeout_s']} s{t}")


def t_anim_protocol(ctx: HilContext, res: TestResult) -> None:
    _need_anim(ctx)
    assert ctx.dev is not None
    blob = hil_anim_blob()
    crc = F.crc32(blob)
    n = 0

    def begin(total=len(blob), c=crc):
        return ctx.req(F.CFG_CMD_ANIM_BEGIN, struct.pack("<II", total, c))

    def data(off, chunk):
        return ctx.req(F.CFG_CMD_ANIM_DATA, struct.pack("<I", off) + chunk)

    try:
        ctx.expect_nak(begin(total=8), F.CFG_ERR_EINVAL, "ANIM_BEGIN len 8")
        ctx.expect_nak(begin(total=A.REGION_SIZE + 1), F.CFG_ERR_EINVAL, "ANIM_BEGIN len > region")
        ctx.expect_nak(ctx.req(F.CFG_CMD_ANIM_BEGIN, b"\x00\x01"), F.CFG_ERR_EINVAL, "ANIM_BEGIN short payload")
        ctx.expect_nak(data(0, blob[:16]), F.CFG_ERR_EINVAL, "ANIM_DATA without BEGIN")
        ctx.expect_nak(ctx.req(F.CFG_CMD_ANIM_COMMIT), F.CFG_ERR_EINVAL, "ANIM_COMMIT without BEGIN")
        n += 5
        ctx.expect_ok(begin(), F.CFG_CMD_ANIM_BEGIN, "ANIM_BEGIN")
        ctx.expect_nak(begin(), F.CFG_ERR_EBUSY, "ANIM_BEGIN twice")
        ctx.expect_ok(data(0, blob[:48]), F.CFG_CMD_ANIM_DATA, "ANIM_DATA @0")
        ctx.expect_nak(data(96, blob[96:144]), F.CFG_ERR_EINVAL, "ANIM_DATA out of order")
        ctx.expect_nak(data(0, blob[:48]), F.CFG_ERR_EINVAL, "ANIM_DATA replay")
        ctx.expect_ok(data(48, blob[48:96]), F.CFG_CMD_ANIM_DATA, "ANIM_DATA @48")
        info = ctx.dev.anim_info()
        ctx.check(info["uploading"] and info["upload_got"] == 96, f"ANIM_INFO during upload {info}")
        # EBUSY across upload kinds while the animation upload is open.
        pb = test_profile_blob()
        ctx.expect_nak(ctx.req(F.CFG_CMD_PROFILE_BEGIN, struct.pack("<BHI", 0, len(pb), F.crc32(pb))),
                       F.CFG_ERR_EBUSY, "PROFILE_BEGIN during anim upload")
        mb = test_macro_blob()
        ctx.expect_nak(ctx.req(F.CFG_CMD_MACRO_BEGIN, struct.pack("<BHI", 0, len(mb), F.crc32(mb))),
                       F.CFG_ERR_EBUSY, "MACRO_BEGIN during anim upload")
        ctx.expect_nak(ctx.req(F.CFG_CMD_SAVE_ALL), F.CFG_ERR_EBUSY, "SAVE_ALL during anim upload")
        ctx.expect_nak(ctx.req(F.CFG_CMD_ANIM_SETTINGS_SET, A.pack_settings(True, 60, 600)),
                       F.CFG_ERR_EBUSY, "ANIM_SETTINGS_SET during anim upload")
        ctx.expect_nak(ctx.req(F.CFG_CMD_ANIM_READ, struct.pack("<I", 0)), F.CFG_ERR_EBUSY,
                       "ANIM_READ during anim upload")
        ctx.expect_nak(ctx.req(F.CFG_CMD_ANIM_PREVIEW, bytes([A.PREVIEW_PLAY])), F.CFG_ERR_EBUSY,
                       "ANIM_PREVIEW during anim upload")
        # Incomplete COMMIT auto-aborts (nothing was flushed: < 4 KiB sent).
        ctx.expect_nak(ctx.req(F.CFG_CMD_ANIM_COMMIT), F.CFG_ERR_EINVAL, "ANIM_COMMIT incomplete")
        ctx.check(not ctx.dev.anim_info()["uploading"], "upload still open after failed COMMIT")
        n += 14
        # ABORT path.
        ctx.expect_ok(begin(), F.CFG_CMD_ANIM_BEGIN, "ANIM_BEGIN (abort test)")
        ctx.expect_ok(data(0, blob[:48]), F.CFG_CMD_ANIM_DATA, "ANIM_DATA @0")
        ctx.expect_ok(ctx.req(F.CFG_CMD_ANIM_ABORT), F.CFG_CMD_ANIM_ABORT, "ANIM_ABORT")
        ctx.expect_ok(ctx.req(F.CFG_CMD_ANIM_ABORT), F.CFG_CMD_ANIM_ABORT, "ANIM_ABORT idempotent")
        n += 4
        # Reverse EBUSY: animation BEGIN while a profile upload is open.
        ctx.expect_ok(ctx.req(F.CFG_CMD_PROFILE_BEGIN, struct.pack("<BHI", 0, len(pb), F.crc32(pb))),
                      F.CFG_CMD_PROFILE_BEGIN, "PROFILE_BEGIN")
        ctx.expect_nak(begin(), F.CFG_ERR_EBUSY, "ANIM_BEGIN during profile upload")
        ctx.expect_ok(ctx.req(F.CFG_CMD_PROFILE_ABORT), F.CFG_CMD_PROFILE_ABORT, "PROFILE_ABORT")
        n += 3
        # Stored animation untouched (no sector was written).
        after = ctx.dev.anim_info()
        if ctx.orig_anim_info is not None:
            ctx.check(after["stored_valid"] == ctx.orig_anim_info["stored_valid"]
                      and after["crc"] == ctx.orig_anim_info["crc"], "stored animation changed")
        ctx.expect_nak(ctx.req(F.CFG_CMD_ANIM_READ, struct.pack("<I", A.REGION_SIZE)), F.CFG_ERR_EINVAL,
                       "ANIM_READ past region")
        ctx.expect_nak(ctx.req(F.CFG_CMD_ANIM_SETTINGS_SET, b"\x02" + bytes(7)), F.CFG_ERR_EINVAL,
                       "ANIM_SETTINGS_SET enabled=2")
        ctx.expect_nak(ctx.req(F.CFG_CMD_ANIM_SETTINGS_SET, b"\x01"), F.CFG_ERR_EINVAL,
                       "ANIM_SETTINGS_SET short")
        n += 4
    finally:
        ctx.abort_uploads()
    res.metrics.update(checks=n)
    res.detail = (f"bad BEGIN/DATA/COMMIT → EINVAL, sequential DATA only, EBUSY both ways vs profile/macro/"
                  f"SAVE_ALL/settings/read/preview, incomplete COMMIT auto-aborts, ABORT idempotent, "
                  f"stored animation untouched ({n} checks, no flash writes)")


def t_anim_preview(ctx: HilContext, res: TestResult) -> None:
    _need_anim(ctx)
    assert ctx.dev is not None
    try:
        ctx.dev.anim_preview(A.PREVIEW_BUILTIN)
        i = ctx.dev.anim_info()
        ctx.check(i["playing"] and i["builtin_active"] and i["preview"], f"builtin preview state {i['status']:#x}")
        ctx.dev.anim_preview(A.PREVIEW_PLAY)
        i = ctx.dev.anim_info()
        ctx.check(i["playing"], "PLAY preview not playing")
        ctx.check(i["builtin_active"] == (not i["stored_valid"]), "PLAY picks stored/builtin wrongly")
        ctx.dev.anim_preview(A.PREVIEW_BLANK)
        ctx.check(ctx.dev.anim_info()["blanked"], "BLANK preview not blanked")
        ctx.expect_nak(ctx.req(F.CFG_CMD_ANIM_PREVIEW, bytes([9])), F.CFG_ERR_EINVAL, "ANIM_PREVIEW mode 9")
        if ctx.opts.interactive:
            time.sleep(1.0)
    finally:
        ctx.dev.anim_preview(A.PREVIEW_STOP)
    i = ctx.dev.anim_info()
    ctx.check(not i["playing"] and not i["blanked"], "STOP did not return to the normal UI")
    res.detail = "builtin → stored/builtin play → blank → stop state machine via ANIM_INFO; bad mode → EINVAL"


def t_anim_settings(ctx: HilContext, res: TestResult) -> None:
    _need_anim(ctx)
    assert ctx.dev is not None
    if not ctx.opts.allow_flash_write:
        raise Skip("ANIM_SETTINGS_SET rewrites the storage sector — rerun with --allow-flash-write")
    orig = ctx.orig_anim_settings or ctx.dev.anim_settings_get()
    test = {"enabled": not orig["enabled"], "idle_timeout_s": 17, "blank_timeout_s": 1234}
    try:
        got = ctx.dev.anim_settings_set(**test)
        ctx.check(got == test, f"SETTINGS_SET echoed {got}")
        ctx.check(ctx.dev.anim_settings_get() == test, "SETTINGS_GET after SET differs")
        # Profiles / macros must survive the MPFL rewrite.
        for i in range(5):
            ctx.check(ctx.meta("profile", i)["crc"] == ctx.orig_profile_crc.get(i), f"profile {i} changed")
    finally:
        ctx.dev.anim_settings_set(**orig)
    ctx.check(ctx.dev.anim_settings_get() == orig, "settings not restored")
    res.metrics.update(flash_writes=2)
    res.detail = f"set {test} → get matches, profiles intact, restored {orig} (2 flash writes)"


def t_anim_roundtrip(ctx: HilContext, res: TestResult) -> None:
    _need_anim(ctx)
    assert ctx.dev is not None
    if not ctx.opts.allow_flash_write:
        raise Skip("animation upload programs the flash region — rerun with --allow-flash-write")
    backup = ctx.orig_anim_blob
    blob = hil_anim_blob(frames=24)
    t0 = time.perf_counter()
    ctx.dev.anim_upload(blob)
    ms = (time.perf_counter() - t0) * 1000.0
    try:
        info = ctx.dev.anim_info()
        ctx.check(info["stored_valid"] and info["crc"] == F.crc32(blob), f"ANIM_INFO after upload {info}")
        ctx.check(info["frame_count"] == 24 and info["fps"] == 10 and info["name"] == "hiltest",
                  "header fields mismatch")
        rb = ctx.dev.anim_download()
        ctx.check(rb == blob, "read-back differs from uploaded blob")
        # Bad CRC: data is flushed then rejected → stored animation invalidated.
        bad_crc = F.crc32(blob) ^ 0xDEADBEEF
        ctx.expect_ok(ctx.req(F.CFG_CMD_ANIM_BEGIN, struct.pack("<II", len(blob), bad_crc)),
                      F.CFG_CMD_ANIM_BEGIN, "ANIM_BEGIN bad crc")
        for off, chunk in A.iter_chunks(blob):
            ctx.expect_ok(ctx.req(F.CFG_CMD_ANIM_DATA, struct.pack("<I", off) + chunk, timeout_ms=5000),
                          F.CFG_CMD_ANIM_DATA, f"ANIM_DATA@{off}")
        ctx.expect_nak(ctx.req(F.CFG_CMD_ANIM_COMMIT, timeout_ms=5000), F.CFG_ERR_EBADMSG,
                       "ANIM_COMMIT bad crc")
        ctx.check(not ctx.dev.anim_info()["stored_valid"], "stored animation still valid after bad COMMIT")
        # Structurally invalid blob with a correct CRC (fps 0 in header).
        broken = bytearray(blob)
        broken[8] = 0
        ctx.expect_ok(ctx.req(F.CFG_CMD_ANIM_BEGIN, struct.pack("<II", len(broken), F.crc32(bytes(broken)))),
                      F.CFG_CMD_ANIM_BEGIN, "ANIM_BEGIN broken")
        for off, chunk in A.iter_chunks(bytes(broken)):
            ctx.req(F.CFG_CMD_ANIM_DATA, struct.pack("<I", off) + chunk, timeout_ms=5000)
        ctx.expect_nak(ctx.req(F.CFG_CMD_ANIM_COMMIT, timeout_ms=5000), F.CFG_ERR_EBADMSG,
                       "ANIM_COMMIT invalid header")
    finally:
        ctx.abort_uploads()
        if backup is not None:
            ctx.dev.anim_upload(backup)
            restored = "original animation re-uploaded"
        else:
            restored = "no animation stored originally → left invalidated (builtin)"
    after = ctx.dev.anim_info()
    if backup is not None:
        ctx.check(after["stored_valid"] and after["crc"] == F.crc32(backup), "restore failed")
    else:
        ctx.check(not after["stored_valid"], "expected no stored animation after restore")
    res.metrics.update(upload_ms=round(ms, 1), blob_len=len(blob))
    res.detail = (f"{len(blob)} B / 24 frames uploaded in {ms:.0f} ms, info + read-back match; bad CRC and "
                  f"invalid header → EBADMSG + invalidated; {restored}")


TESTS: list[tuple[str, str, Callable[[HilContext, TestResult], None]]] = [
    ("enumerate", "1. Enumerate / open (VID/PID, usage page 0xFF00)", t_enumerate),
    ("ping", "2. PING round-trip + latency", t_ping),
    ("info", "3. GET_INFO + version handshake", t_info),
    ("echo", "4. ECHO random payloads + CRC injection", t_echo),
    ("malformed", "5. Bad cmd / seq / magic / version / length", t_malformed),
    ("profile", "6a. Profile upload protocol (flash-free)", t_profile_protocol),
    ("profile_roundtrip", "6b. Profile backup → upload → verify → restore", t_profile_roundtrip),
    ("macro", "7a. Macro upload protocol + EBUSY (flash-free)", t_macro_protocol),
    ("macro_roundtrip", "7b. Macro backup → upload → verify → restore", t_macro_roundtrip),
    ("active", "8. SET_ACTIVE / GET_ACTIVE cycle", t_active),
    ("save_all", "9. SAVE_ALL", t_save_all),
    ("anim_info", "10a. ANIM_INFO + stored animation read-back", t_anim_info),
    ("anim_protocol", "10b. Animation upload protocol + EBUSY (flash-free)", t_anim_protocol),
    ("anim_preview", "10c. ANIM_PREVIEW state machine", t_anim_preview),
    ("anim_settings", "10d. Idle settings set/get/restore", t_anim_settings),
    ("anim_roundtrip", "10e. Animation upload → verify → bad CRC → restore", t_anim_roundtrip),
    ("interactive", "11. Interactive keys / encoder", t_interactive),
    ("restore_check", "12. Device state restored", t_restore_check),
]
TEST_IDS = [t[0] for t in TESTS]


@dataclass
class HilReport:
    results: list[TestResult]
    info: dict
    mock: bool
    options: dict

    @property
    def counts(self) -> dict:
        c = {PASS: 0, FAIL: 0, SKIP: 0}
        for r in self.results:
            c[r.status] += 1
        return c

    @property
    def exit_code(self) -> int:
        if any(r.id == "enumerate" and r.status == FAIL for r in self.results):
            return 2
        return 1 if self.counts[FAIL] else 0

    def to_dict(self) -> dict:
        return {
            "tool": "hil_test",
            "host_version": ver.HOST_APP_VERSION,
            "expected_fw": f"{ver.FW_VERSION_MAJOR_EXPECTED}.{ver.FW_VERSION_MINOR_CURRENT}",
            "mock": self.mock,
            "device": self.info,
            "options": self.options,
            "results": [asdict(r) for r in self.results],
            "summary": self.counts,
            "exit_code": self.exit_code,
        }


def run_suite(opts: HilOptions, *, hid_module=None, mock: bool = False,
              prompt: Optional[Callable[[str], str]] = None,
              log: Optional[Callable[[str], None]] = None,
              on_result: Optional[Callable[[TestResult], None]] = None) -> HilReport:
    ctx = HilContext(opts, hid_module=hid_module, mock=mock, prompt=prompt, log=log)
    results: list[TestResult] = []
    selected = set(opts.only or TEST_IDS) - set(opts.skip or [])
    # enumerate + info are prerequisites for everything else.
    selected |= {"enumerate", "info"}
    try:
        for tid, title, fn in TESTS:
            res = TestResult(id=tid, title=title, status=PASS)
            t0 = time.perf_counter()
            if tid not in selected:
                res.status, res.detail = SKIP, "not selected (--only/--skip)"
            elif tid != "enumerate" and ctx.dev is None:
                res.status, res.detail = SKIP, "no device open"
            else:
                try:
                    fn(ctx, res)
                except Skip as exc:
                    res.status, res.detail = SKIP, str(exc)
                except Fail as exc:
                    res.status, res.detail = FAIL, str(exc)
                except DeviceError as exc:
                    res.status, res.detail = FAIL, f"device error: {exc}"
                except Exception as exc:  # keep going; report the crash
                    res.status, res.detail = FAIL, f"{type(exc).__name__}: {exc}"
                if res.status == FAIL and tid not in ("enumerate", "restore_check"):
                    ctx.abort_uploads()
            res.duration_ms = round((time.perf_counter() - t0) * 1000.0, 1)
            results.append(res)
            if on_result:
                on_result(res)
    finally:
        if ctx.dev is not None:
            ctx.abort_uploads()
            try:
                if ctx.orig_active is not None and ctx.dev.get_active_slot() != ctx.orig_active:
                    ctx.dev.set_active_slot(ctx.orig_active)
            except DeviceError:
                pass
            ctx.dev.close()
    opt_dict = asdict(opts)
    if isinstance(opt_dict.get("path"), bytes):
        opt_dict["path"] = opt_dict["path"].decode("latin-1")
    return HilReport(results=results, info=ctx.info, mock=mock, options=opt_dict)


__all__ = [
    "FAIL", "PASS", "SKIP", "HilOptions", "HilReport", "TEST_IDS", "TESTS",
    "TestResult", "run_suite", "test_macro_blob", "test_profile_blob",
]
