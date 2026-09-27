"""Pack / unpack macro_blob_v1 (162 bytes) — mirrors firmware macro_blob.h."""

from __future__ import annotations

import struct
from collections.abc import Mapping
from typing import Any

from ..models.macro import MACRO_OPS, Macro, MacroStep
from .frames import crc32
from .profile_blob import (
    bitmap_to_mods,
    hid_to_key_name,
    key_name_to_hid,
    mods_to_bitmap,
)

MACRO_NAME_MAX = 16
MACRO_MAX_STEPS = 24
MACRO_BUILTIN_COUNT = 5
MACRO_STEP_WIRE_SIZE = 6
MACRO_BLOB_V1_SIZE = MACRO_NAME_MAX + 2 + MACRO_MAX_STEPS * MACRO_STEP_WIRE_SIZE  # 162
MACRO_BANK_BLOB_SIZE = MACRO_BUILTIN_COUNT * MACRO_BLOB_V1_SIZE  # 810

# Max raw bytes per MACRO_DATA after 2-byte offset (same as profile).
MACRO_DATA_MAX_CHUNK = 50

OP_TO_WIRE = {name: i for i, name in enumerate(MACRO_OPS)}
WIRE_TO_OP = {i: name for name, i in OP_TO_WIRE.items()}


class MacroBlobError(ValueError):
    """Invalid macro blob or Macro that cannot be packed."""


def _pad_name(s: str) -> bytes:
    raw = (s or "").encode("ascii", errors="replace")[: MACRO_NAME_MAX - 1]
    return raw + bytes(MACRO_NAME_MAX - len(raw))


def _read_name(data: bytes) -> str:
    return data.split(b"\x00", 1)[0].decode("ascii", errors="replace")


def _pack_step(step: MacroStep | Mapping[str, Any]) -> bytes:
    if isinstance(step, MacroStep):
        op_name = step.op
        mods = step.mods
        key = step.key
        arg = step.arg
    else:
        op_name = str(step.get("op", "END")).upper()
        mods = step.get("mods", [])
        key = step.get("key", "")
        arg = int(step.get("arg", 0) or 0)

    if op_name not in OP_TO_WIRE:
        raise MacroBlobError(f"unknown op {op_name!r}")
    op = OP_TO_WIRE[op_name]
    mods_b = mods_to_bitmap(mods) if op_name in ("KEY_DOWN", "KEY_UP", "TAP") else 0
    keycode = 0
    if op_name in ("KEY_DOWN", "KEY_UP", "TAP"):
        keycode = key_name_to_hid(key or "")
    arg_u = 0
    if op_name in ("DELAY_MS", "TEXT", "CONSUMER"):
        arg_u = int(arg) & 0xFFFF
    return struct.pack("<BBBBH", op, mods_b, keycode & 0xFF, 0, arg_u)


def _unpack_step(data: bytes) -> MacroStep:
    if len(data) < MACRO_STEP_WIRE_SIZE:
        raise MacroBlobError("step truncated")
    op, mods, keycode, _pad, arg = struct.unpack_from("<BBBBH", data, 0)
    op_name = WIRE_TO_OP.get(op)
    if op_name is None:
        raise MacroBlobError(f"unknown wire op {op}")
    if op_name == "END":
        return MacroStep(op="END")
    if op_name in ("KEY_DOWN", "KEY_UP", "TAP"):
        key = hid_to_key_name(keycode) if keycode else ""
        return MacroStep(op=op_name, mods=bitmap_to_mods(mods), key=key)
    return MacroStep(op=op_name, arg=int(arg))


def pack_macro(macro: Macro | Mapping[str, Any]) -> bytes:
    """Serialize a Macro / dict to MACRO_BLOB_V1_SIZE bytes."""
    if isinstance(macro, Macro):
        name = macro.name
        steps = list(macro.steps)
    else:
        name = str(macro.get("name", ""))
        raw_steps = macro.get("steps") or []
        steps = [s if isinstance(s, MacroStep) else MacroStep.from_dict(s) for s in raw_steps]

    if not steps:
        raise MacroBlobError("steps must be non-empty")

    # Firmware (macro_blob_unpack / macros_replace) truncates at the first END;
    # do the same so the packed blob is canonical and reads back byte-identical.
    for i, st in enumerate(steps):
        if st.op == "END":
            steps = list(steps[: i + 1])
            break

    # Ensure final END; append if missing.
    if steps[-1].op != "END":
        steps = [*steps, MacroStep(op="END")]

    if len(steps) > MACRO_MAX_STEPS:
        raise MacroBlobError(f"too many steps ({len(steps)} > {MACRO_MAX_STEPS})")

    buf = bytearray(MACRO_BLOB_V1_SIZE)
    buf[0:16] = _pad_name(name)
    buf[16] = len(steps) & 0xFF
    buf[17] = 0
    for i, step in enumerate(steps):
        packed = _pack_step(step)
        off = 18 + i * MACRO_STEP_WIRE_SIZE
        buf[off : off + MACRO_STEP_WIRE_SIZE] = packed
    return bytes(buf)


def unpack_macro(blob: bytes, *, macro_id: int = 0) -> Macro:
    """Deserialize 162-byte blob → Macro (id supplied by caller)."""
    if len(blob) != MACRO_BLOB_V1_SIZE:
        raise MacroBlobError(f"expected {MACRO_BLOB_V1_SIZE} bytes, got {len(blob)}")
    name = _read_name(blob[0:16])
    count = blob[16]
    if count < 1 or count > MACRO_MAX_STEPS:
        raise MacroBlobError(f"bad step_count {count}")

    steps: list[MacroStep] = []
    for i in range(count):
        off = 18 + i * MACRO_STEP_WIRE_SIZE
        step = _unpack_step(blob[off : off + MACRO_STEP_WIRE_SIZE])
        steps.append(step)
        if step.op == "END":
            break
    else:
        # No END in declared range — append.
        if len(steps) >= MACRO_MAX_STEPS:
            raise MacroBlobError("missing END and no room to append")
        steps.append(MacroStep(op="END"))

    if not name:
        name = f"macro-{macro_id}"
    return Macro(id=int(macro_id), name=name, steps=steps)


def blob_crc(blob: bytes) -> int:
    if len(blob) != MACRO_BLOB_V1_SIZE:
        raise MacroBlobError("blob size mismatch")
    return crc32(blob)


def iter_macro_data_chunks(blob: bytes, chunk_size: int = MACRO_DATA_MAX_CHUNK):
    """Yield (offset, chunk_bytes) for MACRO_DATA framing."""
    if len(blob) != MACRO_BLOB_V1_SIZE:
        raise MacroBlobError("blob size mismatch")
    if chunk_size < 1 or chunk_size > MACRO_DATA_MAX_CHUNK:
        raise MacroBlobError(f"bad chunk_size {chunk_size}")
    offset = 0
    while offset < len(blob):
        piece = blob[offset : offset + chunk_size]
        yield offset, piece
        offset += len(piece)


def pack_library_slot(library: Any, macro_id: int) -> bytes | None:
    """Pack library macro with given id, or None if missing."""
    macro = None
    if hasattr(library, "macro_by_id"):
        macro = library.macro_by_id(macro_id)
    elif isinstance(library, Mapping):
        for m in library.get("macros", []):
            if int(m.get("id", -1)) == macro_id:
                macro = m
                break
    if macro is None:
        return None
    return pack_macro(macro)


__all__ = [
    "MACRO_BANK_BLOB_SIZE",
    "MACRO_BLOB_V1_SIZE",
    "MACRO_BUILTIN_COUNT",
    "MACRO_DATA_MAX_CHUNK",
    "MACRO_MAX_STEPS",
    "MACRO_NAME_MAX",
    "MacroBlobError",
    "blob_crc",
    "iter_macro_data_chunks",
    "pack_library_slot",
    "pack_macro",
    "unpack_macro",
]
