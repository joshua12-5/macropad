#!/usr/bin/env python3
"""Headless smoke test: config protocol frame CRC + pack/unpack (no hardware).

Usage:
  cd configurator
  python scripts/smoke_protocol.py
"""

from __future__ import annotations

import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from macropad_config.protocol.frames import (
    CFG_CMD_ECHO,
    CFG_CMD_GET_INFO,
    CFG_CMD_NAK,
    CFG_CMD_PING,
    CFG_ERR_EBADMSG,
    CFG_ERR_EINVAL,
    CFG_FLAG_RESPONSE,
    CFG_MAGIC,
    CFG_PAYLOAD_MAX,
    CFG_PROTO_VERSION,
    CFG_REPORT_SIZE,
    FrameError,
    crc32,
    pack_frame,
    parse_get_info,
    unpack_frame,
)


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_crc_matches_zlib() -> None:
    samples = [b"", b"MP", b"\x00" * 60, bytes(range(60)), b"hello" * 12]
    for s in samples:
        ours = crc32(s)
        ref = zlib.crc32(s) & 0xFFFFFFFF
        expect(ours == ref, f"CRC mismatch for {s!r}: {ours:#08x} vs {ref:#08x}")


def test_pack_unpack_roundtrip() -> None:
    for cmd, payload in [
        (CFG_CMD_PING, b""),
        (CFG_CMD_PING, b"PONG"),
        (CFG_CMD_ECHO, b"abc"),
        (CFG_CMD_ECHO, bytes(range(CFG_PAYLOAD_MAX))),
        (CFG_CMD_GET_INFO, bytes([0, 15, 1, 0, 3, 0]) + b"MACROPAD"),
        (CFG_CMD_NAK, bytes([CFG_ERR_EINVAL])),
    ]:
        raw = pack_frame(cmd, seq=42, payload=payload, flags=CFG_FLAG_RESPONSE)
        expect(len(raw) == CFG_REPORT_SIZE, f"len={len(raw)}")
        fr = unpack_frame(raw)
        expect(fr.magic == CFG_MAGIC, "magic")
        expect(fr.version == CFG_PROTO_VERSION, "version")
        expect(fr.cmd == cmd, "cmd")
        expect(fr.seq == 42, "seq")
        expect(fr.payload == payload, f"payload {fr.payload!r} != {payload!r}")
        expect(fr.is_response, "flags.response")


def test_bad_crc_rejected() -> None:
    raw = bytearray(pack_frame(CFG_CMD_PING, 1, b""))
    raw[60] ^= 0xFF
    try:
        unpack_frame(bytes(raw))
        raise AssertionError("expected FrameError for bad CRC")
    except FrameError as exc:
        expect("CRC" in str(exc).upper() or "crc" in str(exc), str(exc))


def test_bad_magic_rejected() -> None:
    raw = bytearray(pack_frame(CFG_CMD_PING, 1, b""))
    raw[0] = 0x00
    try:
        unpack_frame(bytes(raw))
        raise AssertionError("expected FrameError for bad magic")
    except FrameError:
        pass


def test_get_info_parse() -> None:
    pl = bytes([0, 15, 1, 2, 5, 0]) + b"MACROPAD"
    info = parse_get_info(pl)
    expect(info["fw_major"] == 0, "major")
    expect(info["fw_minor"] == 15, "minor")
    expect(info["proto_ver"] == 1, "proto")
    expect(info["active_slot"] == 2, "slot")
    expect(info["slot_count"] == 5, "count")
    expect(info["product_tag"] == "MACROPAD", f"tag={info['product_tag']!r}")


def test_payload_too_long() -> None:
    try:
        pack_frame(CFG_CMD_ECHO, 1, bytes(CFG_PAYLOAD_MAX + 1))
        raise AssertionError("expected FrameError")
    except FrameError:
        pass


def main() -> int:
    tests = [
        test_crc_matches_zlib,
        test_pack_unpack_roundtrip,
        test_bad_crc_rejected,
        test_bad_magic_rejected,
        test_get_info_parse,
        test_payload_too_long,
    ]
    failed = 0
    for t in tests:
        name = t.__name__
        try:
            t()
            print(f"PASS  {name}")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {name}: {exc}")
    if failed:
        print(f"\n{failed}/{len(tests)} failed")
        return 1
    print(f"\nAll {len(tests)} smoke_protocol tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
