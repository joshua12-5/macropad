#!/usr/bin/env python3
"""Headless smoke: profile_blob pack/unpack + chunk framing (no hardware / no SDK).

Usage:
  cd configurator
  python scripts/smoke_storage.py
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from macropad_config.protocol.frames import (
    CFG_CMD_PROFILE_BEGIN,
    CFG_CMD_PROFILE_DATA,
    CFG_PAYLOAD_MAX,
    crc32,
    pack_frame,
    unpack_frame,
)
from macropad_config.protocol.profile_blob import (
    PROFILE_BLOB_V1_SIZE,
    PROFILE_DATA_MAX_CHUNK,
    blob_crc,
    iter_profile_data_chunks,
    pack_profile_dict,
    unpack_profile_dict,
)


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_blob_size_constant() -> None:
    expect(PROFILE_BLOB_V1_SIZE == 148, f"size={PROFILE_BLOB_V1_SIZE}")
    expect(PROFILE_DATA_MAX_CHUNK == 50, "chunk")
    expect(PROFILE_DATA_MAX_CHUNK + 2 <= CFG_PAYLOAD_MAX, "chunk fits payload")


def test_pack_unpack_coding_json() -> None:
    path = REPO / "profiles" / "Coding.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    blob = pack_profile_dict(data)
    expect(len(blob) == PROFILE_BLOB_V1_SIZE, f"len={len(blob)}")
    back = unpack_profile_dict(blob)
    expect(back["schema_version"] == 1, "schema")
    expect(back["id"] == "coding", f"id={back['id']!r}")
    expect(back["name"] == "CODING", f"name={back['name']!r}")
    expect(back["oled"]["title"] == "CODING", "oled")
    # Spot-check a few actions
    expect(back["keys"]["1"]["type"] == "SHORTCUT", "key1 type")
    expect(back["keys"]["1"]["key"] == "C", f"key1={back['keys']['1']}")
    expect("CTRL" in back["keys"]["1"]["mods"], "key1 mods")
    expect(back["keys"]["12"]["type"] == "MACRO", "macro")
    expect(back["keys"]["12"]["macro_id"] == 1, "macro_id")
    expect(back["encoder"]["cw"]["type"] == "VOLUME", "enc")
    expect(back["encoder"]["cw"]["dir"] == "up", "enc dir")


def test_roundtrip_all_profiles() -> None:
    for path in sorted((REPO / "profiles").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        blob = pack_profile_dict(data)
        back = unpack_profile_dict(blob)
        expect(back["id"] == data["id"], f"{path.name} id")
        expect(len(blob) == PROFILE_BLOB_V1_SIZE, f"{path.name} size")
        # Re-pack must be stable
        blob2 = pack_profile_dict(back)
        expect(blob2 == blob, f"{path.name} not stable after roundtrip")


def test_blob_crc_matches_frames_crc() -> None:
    path = REPO / "profiles" / "Default.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    blob = pack_profile_dict(data)
    expect(blob_crc(blob) == crc32(blob), "crc helper")


def test_chunk_framing() -> None:
    path = REPO / "profiles" / "Gaming.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    blob = pack_profile_dict(data)
    chunks = list(iter_profile_data_chunks(blob))
    expect(len(chunks) >= 3, f"chunks={len(chunks)}")
    rebuilt = bytearray(PROFILE_BLOB_V1_SIZE)
    for offset, piece in chunks:
        expect(len(piece) <= PROFILE_DATA_MAX_CHUNK, "piece too big")
        rebuilt[offset : offset + len(piece)] = piece
        # Also exercise frame pack for DATA
        payload = struct.pack("<H", offset) + piece
        expect(len(payload) <= CFG_PAYLOAD_MAX, "payload")
        raw = pack_frame(CFG_CMD_PROFILE_DATA, seq=7, payload=payload)
        fr = unpack_frame(raw)
        expect(fr.cmd == CFG_CMD_PROFILE_DATA, "cmd")
        expect(fr.payload == payload, "payload roundtrip")
    expect(bytes(rebuilt) == blob, "reassembled")

    # BEGIN frame
    begin = struct.pack("<BHI", 2, PROFILE_BLOB_V1_SIZE, blob_crc(blob))
    raw = pack_frame(CFG_CMD_PROFILE_BEGIN, seq=1, payload=begin)
    fr = unpack_frame(raw)
    expect(fr.payload == begin, "begin payload")


def test_layout_offsets() -> None:
    """Sanity: documented offsets match packed field boundaries."""
    blank = {
        "schema_version": 1,
        "id": "x",
        "name": "X",
        "oled": {"title": "X", "animation": "static"},
        "keys": {str(i): {"type": "DISABLED"} for i in range(1, 13)},
        "encoder": {
            "cw": {"type": "DISABLED"},
            "ccw": {"type": "DISABLED"},
            "press": {"type": "DISABLED"},
            "long_press": {"type": "DISABLED"},
        },
    }
    blob = pack_profile_dict(blank)
    expect(struct.unpack_from("<H", blob, 0)[0] == 1, "schema@0")
    expect(blob[2:18].startswith(b"x\x00"), "id@2")
    expect(blob[147] == 0, "pad")
    expect(len(blob) == 2 + 16 + 16 + 12 * 6 + 4 * 6 + 16 + 1 + 1, "arith")


def main() -> int:
    tests = [
        test_blob_size_constant,
        test_pack_unpack_coding_json,
        test_roundtrip_all_profiles,
        test_blob_crc_matches_frames_crc,
        test_chunk_framing,
        test_layout_offsets,
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
    print(f"\nAll {len(tests)} smoke_storage tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
