#!/usr/bin/env python3
"""Headless smoke: macro_blob pack/unpack + chunk framing (no hardware).

Usage:
  cd configurator
  python scripts/smoke_macros_blob.py
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from macropad_config.models.macro import load_library
from macropad_config.protocol.frames import (
    CFG_CMD_MACRO_BEGIN,
    CFG_CMD_MACRO_DATA,
    CFG_PAYLOAD_MAX,
    crc32,
    pack_frame,
    unpack_frame,
)
from macropad_config.protocol.macro_blob import (
    MACRO_BLOB_V1_SIZE,
    MACRO_BUILTIN_COUNT,
    MACRO_DATA_MAX_CHUNK,
    MACRO_MAX_STEPS,
    blob_crc,
    iter_macro_data_chunks,
    pack_macro,
    unpack_macro,
)


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_blob_size_constant() -> None:
    expect(MACRO_MAX_STEPS == 24, f"max_steps={MACRO_MAX_STEPS}")
    expect(MACRO_BLOB_V1_SIZE == 162, f"size={MACRO_BLOB_V1_SIZE}")
    expect(MACRO_BUILTIN_COUNT == 5, "count")
    expect(MACRO_DATA_MAX_CHUNK == 50, "chunk")
    expect(MACRO_DATA_MAX_CHUNK + 2 <= CFG_PAYLOAD_MAX, "chunk fits")
    expect(MACRO_BLOB_V1_SIZE == 16 + 2 + 24 * 6, "arith")


def test_pack_unpack_library() -> None:
    lib = load_library(REPO / "macros" / "library.json")
    expect(len(lib.macros) == 5, f"macros={len(lib.macros)}")
    for mid in range(MACRO_BUILTIN_COUNT):
        macro = lib.macro_by_id(mid)
        expect(macro is not None, f"missing id {mid}")
        assert macro is not None
        blob = pack_macro(macro)
        expect(len(blob) == MACRO_BLOB_V1_SIZE, f"id {mid} len")
        back = unpack_macro(blob, macro_id=mid)
        expect(back.id == mid, "id")
        expect(back.name == macro.name, f"name {back.name!r}!={macro.name!r}")
        expect(len(back.steps) == len(macro.steps), f"steps count id={mid}")
        expect(back.steps[-1].op == "END", "end")
        # Stable re-pack
        blob2 = pack_macro(back)
        expect(blob2 == blob, f"id {mid} not stable")


def test_hello_ops_roundtrip() -> None:
    lib = load_library(REPO / "macros" / "library.json")
    hello = lib.macro_by_id(0)
    assert hello is not None
    blob = pack_macro(hello)
    back = unpack_macro(blob, macro_id=0)
    ops = [s.op for s in back.steps]
    expect(ops[0] == "TAP", f"op0={ops[0]}")
    expect(back.steps[0].key == "H", f"key={back.steps[0].key}")
    expect("DELAY_MS" in ops, "delay")
    expect(ops[-1] == "END", "end")


def test_append_end_if_missing() -> None:
    from macropad_config.models.macro import Macro, MacroStep

    # A macro without a trailing END gets one appended by pack_macro.
    m = Macro(id=0, name="tmp", steps=[MacroStep(op="TAP", mods=[], key="A")])
    blob = pack_macro(m)
    back = unpack_macro(blob, macro_id=0)
    expect([s.op for s in back.steps] == ["TAP", "END"], f"END appended: {[s.op for s in back.steps]}")
    blob2 = pack_macro(Macro(id=0, name="x", steps=[MacroStep(op="DELAY_MS", arg=10), MacroStep(op="END")]))
    expect(blob2[16] >= 2, "count")


def test_blob_crc_matches_frames_crc() -> None:
    lib = load_library(REPO / "macros" / "library.json")
    macro = lib.macro_by_id(1)
    assert macro is not None
    blob = pack_macro(macro)
    expect(blob_crc(blob) == crc32(blob), "crc")


def test_chunk_framing() -> None:
    lib = load_library(REPO / "macros" / "library.json")
    macro = lib.macro_by_id(4)
    assert macro is not None
    blob = pack_macro(macro)
    chunks = list(iter_macro_data_chunks(blob))
    expect(len(chunks) >= 3, f"chunks={len(chunks)}")
    rebuilt = bytearray(MACRO_BLOB_V1_SIZE)
    for offset, piece in chunks:
        expect(len(piece) <= MACRO_DATA_MAX_CHUNK, "piece")
        rebuilt[offset : offset + len(piece)] = piece
        payload = struct.pack("<H", offset) + piece
        expect(len(payload) <= CFG_PAYLOAD_MAX, "payload")
        raw = pack_frame(CFG_CMD_MACRO_DATA, seq=3, payload=payload)
        fr = unpack_frame(raw)
        expect(fr.cmd == CFG_CMD_MACRO_DATA, "cmd")
        expect(fr.payload == payload, "payload rt")
    expect(bytes(rebuilt) == blob, "reassembled")

    begin = struct.pack("<BHI", 4, MACRO_BLOB_V1_SIZE, blob_crc(blob))
    raw = pack_frame(CFG_CMD_MACRO_BEGIN, seq=1, payload=begin)
    fr = unpack_frame(raw)
    expect(fr.payload == begin, "begin")


def test_alt_tab_mods() -> None:
    lib = load_library(REPO / "macros" / "library.json")
    m = lib.macro_by_id(4)
    assert m is not None
    blob = pack_macro(m)
    back = unpack_macro(blob, macro_id=4)
    down = back.steps[0]
    expect(down.op == "KEY_DOWN", f"op={down.op}")
    expect("ALT" in down.mods, f"mods={down.mods}")


def main() -> int:
    tests = [
        test_blob_size_constant,
        test_pack_unpack_library,
        test_hello_ops_roundtrip,
        test_append_end_if_missing,
        test_blob_crc_matches_frames_crc,
        test_chunk_framing,
        test_alt_tab_mods,
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
    print(f"\nAll {len(tests)} smoke_macros_blob tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
