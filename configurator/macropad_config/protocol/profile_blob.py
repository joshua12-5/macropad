"""Pack / unpack profile_blob_v1 (148 bytes) — mirrors firmware profile_blob.h."""

from __future__ import annotations

import struct
from collections.abc import Mapping
from typing import Any

from .frames import crc32

PROFILE_BLOB_V1_SIZE = 148
PROFILE_NAME_MAX = 16
PROFILE_KEY_COUNT = 12
PROFILE_BLOB_ACTION_SIZE = 6

ACTION_TYPE = {
    "DISABLED": 0,
    "KEY": 1,
    "SHORTCUT": 2,
    "MACRO": 3,
    "TEXT": 4,
    "MEDIA": 5,
    "VOLUME": 6,
    "APP": 7,
    "URL": 8,
    "PROFILE": 9,
}
ACTION_TYPE_REV = {v: k for k, v in ACTION_TYPE.items()}

VOLUME_DIR = {"up": 1, "down": 2, "mute": 3}
VOLUME_DIR_REV = {v: k for k, v in VOLUME_DIR.items()}

OLED_ANIM = {"static": 0, "scroll": 1, "matrix": 2}
OLED_ANIM_REV = {v: k for k, v in OLED_ANIM.items()}


def _as_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if s.lower().startswith("0x"):
        return int(s, 16)
    return int(s, 10)


MOD_BITS = {
    "CTRL": 0x01,
    "SHIFT": 0x02,
    "ALT": 0x04,
    "GUI": 0x08,
    "WIN": 0x08,
    "CMD": 0x08,
}

# HID keyboard usages used by firmware / JSON profiles.
_HID_LETTER_BASE = 0x04  # A
_HID_DIGIT = {
    "1": 0x1E,
    "2": 0x1F,
    "3": 0x20,
    "4": 0x21,
    "5": 0x22,
    "6": 0x23,
    "7": 0x24,
    "8": 0x25,
    "9": 0x26,
    "0": 0x27,
}
_HID_NAMED = {
    "ENTER": 0x28,
    "ESC": 0x29,
    "ESCAPE": 0x29,
    "BACKSPACE": 0x2A,
    "TAB": 0x2B,
    "SPACE": 0x2C,
    "/": 0x38,
    "-": 0x2D,
    "=": 0x2E,
    "[": 0x2F,
    "]": 0x30,
    "\\": 0x31,
    ";": 0x33,
    "'": 0x34,
    "`": 0x35,
    ",": 0x36,
    ".": 0x37,
    "DELETE": 0x4C,
    "RIGHT": 0x4F,
    "LEFT": 0x50,
    "DOWN": 0x51,
    "UP": 0x52,
}
for _i in range(1, 13):
    _HID_NAMED[f"F{_i}"] = 0x3A + _i - 1

MEDIA_USAGE = {
    "PLAY_PAUSE": 0x00CD,
    "NEXT": 0x00B5,
    "SCAN_NEXT": 0x00B5,
    "PREV": 0x00B6,
    "SCAN_PREV": 0x00B6,
    "STOP": 0x00B7,
    "MUTE": 0x00E2,
    "VOLUME_UP": 0x00E9,
    "VOLUME_DOWN": 0x00EA,
}


class ProfileBlobError(ValueError):
    """Invalid profile blob or JSON that cannot be packed."""


def _pad_name(s: str) -> bytes:
    raw = (s or "").encode("ascii", errors="replace")[: PROFILE_NAME_MAX - 1]
    return raw + bytes(PROFILE_NAME_MAX - len(raw))


def _read_name(data: bytes) -> str:
    return data.split(b"\x00", 1)[0].decode("ascii", errors="replace")


def key_name_to_hid(name: str) -> int:
    """Map JSON key token → HID usage id."""
    if name is None:
        return 0
    key = str(name).strip()
    if not key:
        return 0
    upper = key.upper()
    if len(upper) == 1 and "A" <= upper <= "Z":
        return _HID_LETTER_BASE + (ord(upper) - ord("A"))
    if upper in _HID_DIGIT:
        return _HID_DIGIT[upper]
    if key in _HID_DIGIT:
        return _HID_DIGIT[key]
    if upper in _HID_NAMED:
        return _HID_NAMED[upper]
    if key in _HID_NAMED:
        return _HID_NAMED[key]
    # Accept decimal / 0xNN
    try:
        if key.lower().startswith("0x"):
            return int(key, 16) & 0xFF
        return int(key) & 0xFF
    except ValueError as exc:
        raise ProfileBlobError(f"unknown key name {name!r}") from exc


def hid_to_key_name(code: int) -> str:
    code &= 0xFF
    if 0x04 <= code <= 0x1D:
        return chr(ord("A") + (code - 0x04))
    for name, val in _HID_DIGIT.items():
        if val == code:
            return name
    for name, val in _HID_NAMED.items():
        if val == code:
            return name
    return str(code)


def mods_to_bitmap(mods: Any) -> int:
    bits = 0
    if not mods:
        return 0
    if isinstance(mods, int):
        return mods & 0xFF
    for m in mods:
        bits |= MOD_BITS.get(str(m).upper(), 0)
    return bits & 0xFF


def bitmap_to_mods(bits: int) -> list[str]:
    out: list[str] = []
    if bits & 0x01:
        out.append("CTRL")
    if bits & 0x02:
        out.append("SHIFT")
    if bits & 0x04:
        out.append("ALT")
    if bits & 0x08:
        out.append("GUI")
    return out


def _pack_action(action: Mapping[str, Any] | None) -> bytes:
    if not action:
        action = {"type": "DISABLED"}
    atype_name = str(action.get("type", "DISABLED")).upper()
    if atype_name not in ACTION_TYPE:
        raise ProfileBlobError(f"unknown action type {atype_name!r}")
    atype = ACTION_TYPE[atype_name]
    mods = 0
    keycode = 0
    aux = 0
    usage = 0

    if atype_name in ("KEY", "SHORTCUT"):
        keycode = key_name_to_hid(str(action.get("key", "")))
        if atype_name == "SHORTCUT":
            mods = mods_to_bitmap(action.get("mods", []))
    elif atype_name == "MACRO":
        aux = int(action.get("macro_id", 0)) & 0xFF
    elif atype_name in ("TEXT", "URL"):
        aux = int(action.get("text_id", 0)) & 0xFF
    elif atype_name == "APP":
        if "text_id" in action:
            aux = int(action["text_id"]) & 0xFF
        elif "app_id" in action:
            aux = int(action["app_id"]) & 0xFF
    elif atype_name == "MEDIA":
        if "usage" in action:
            usage = _as_int(action["usage"]) & 0xFFFF
        elif "code" in action:
            code = action["code"]
            if isinstance(code, str) and code.upper() in MEDIA_USAGE:
                usage = MEDIA_USAGE[code.upper()]
            else:
                usage = _as_int(code) & 0xFFFF
    elif atype_name == "VOLUME":
        direction = str(action.get("dir", "up")).lower()
        if direction not in VOLUME_DIR:
            raise ProfileBlobError(f"bad volume dir {direction!r}")
        aux = VOLUME_DIR[direction]
    elif atype_name == "PROFILE":
        if "slot" in action:
            aux = int(action["slot"]) & 0xFF
        elif "profile_id" in action:
            # Host may use id string; slot unknown → 0
            aux = 0

    return struct.pack("<BBBBH", atype, mods, keycode, aux, usage)


def _unpack_action(data: bytes) -> dict[str, Any]:
    if len(data) < PROFILE_BLOB_ACTION_SIZE:
        raise ProfileBlobError("action truncated")
    atype, mods, keycode, aux, usage = struct.unpack_from("<BBBBH", data, 0)
    name = ACTION_TYPE_REV.get(atype, "DISABLED")
    action: dict[str, Any] = {"type": name}
    if name == "KEY":
        action["key"] = hid_to_key_name(keycode)
    elif name == "SHORTCUT":
        action["key"] = hid_to_key_name(keycode)
        action["mods"] = bitmap_to_mods(mods)
    elif name == "MACRO":
        action["macro_id"] = aux
    elif name in ("TEXT", "URL"):
        action["text_id"] = aux
    elif name == "APP":
        action["text_id"] = aux
    elif name == "MEDIA":
        action["usage"] = usage
        for label, val in MEDIA_USAGE.items():
            if val == usage:
                action["code"] = label
                break
    elif name == "VOLUME":
        action["dir"] = VOLUME_DIR_REV.get(aux, "up")
    elif name == "PROFILE":
        action["slot"] = aux
    return action


def pack_profile_dict(data: Mapping[str, Any]) -> bytes:
    """Serialize a schema-v1 profile dict (or Profile.to_dict()) to 148 bytes."""
    schema = int(data.get("schema_version", 0))
    if schema != 1:
        raise ProfileBlobError(f"unsupported schema_version {schema}")
    buf = bytearray(PROFILE_BLOB_V1_SIZE)
    struct.pack_into("<H", buf, 0, schema)
    buf[2:18] = _pad_name(str(data.get("id", "")))
    buf[18:34] = _pad_name(str(data.get("name", "")))

    keys = data.get("keys") or {}
    for i in range(PROFILE_KEY_COUNT):
        action = keys.get(str(i + 1)) or keys.get(i + 1) or {"type": "DISABLED"}
        packed = _pack_action(action)
        off = 34 + i * PROFILE_BLOB_ACTION_SIZE
        buf[off : off + PROFILE_BLOB_ACTION_SIZE] = packed

    enc = data.get("encoder") or {}
    for j, slot in enumerate(("cw", "ccw", "press", "long_press")):
        packed = _pack_action(enc.get(slot) or {"type": "DISABLED"})
        off = 106 + j * PROFILE_BLOB_ACTION_SIZE
        buf[off : off + PROFILE_BLOB_ACTION_SIZE] = packed

    oled = data.get("oled") or {}
    title = oled.get("title")
    if not isinstance(title, str):
        title = str(data.get("name", ""))
    buf[130:146] = _pad_name(title)
    anim = oled.get("animation", "static")
    if isinstance(anim, str):
        buf[146] = OLED_ANIM.get(anim.lower(), 0)
    else:
        buf[146] = int(anim) & 0xFF
    buf[147] = 0
    return bytes(buf)


def unpack_profile_dict(blob: bytes) -> dict[str, Any]:
    """Deserialize 148-byte blob → schema-v1 profile dict."""
    if len(blob) != PROFILE_BLOB_V1_SIZE:
        raise ProfileBlobError(f"expected {PROFILE_BLOB_V1_SIZE} bytes, got {len(blob)}")
    schema = struct.unpack_from("<H", blob, 0)[0]
    if schema != 1:
        raise ProfileBlobError(f"unsupported schema_version {schema}")
    profile_id = _read_name(blob[2:18])
    name = _read_name(blob[18:34])
    keys: dict[str, Any] = {}
    for i in range(PROFILE_KEY_COUNT):
        off = 34 + i * PROFILE_BLOB_ACTION_SIZE
        keys[str(i + 1)] = _unpack_action(blob[off : off + PROFILE_BLOB_ACTION_SIZE])
    encoder: dict[str, Any] = {}
    for j, slot in enumerate(("cw", "ccw", "press", "long_press")):
        off = 106 + j * PROFILE_BLOB_ACTION_SIZE
        encoder[slot] = _unpack_action(blob[off : off + PROFILE_BLOB_ACTION_SIZE])
    title = _read_name(blob[130:146])
    anim = OLED_ANIM_REV.get(blob[146], "static")
    return {
        "schema_version": schema,
        "id": profile_id,
        "name": name,
        "oled": {"title": title, "animation": anim},
        "keys": keys,
        "encoder": encoder,
    }


def pack_profile(profile: Any) -> bytes:
    """Accept a Profile instance (with to_dict) or a plain dict."""
    if hasattr(profile, "to_dict"):
        return pack_profile_dict(profile.to_dict())
    return pack_profile_dict(profile)


def blob_crc(blob: bytes) -> int:
    if len(blob) != PROFILE_BLOB_V1_SIZE:
        raise ProfileBlobError("blob size mismatch")
    return crc32(blob)


# Max raw bytes per PROFILE_DATA after 2-byte offset.
PROFILE_DATA_MAX_CHUNK = 50


def iter_profile_data_chunks(blob: bytes, chunk_size: int = PROFILE_DATA_MAX_CHUNK):
    """Yield (offset, chunk_bytes) for PROFILE_DATA framing."""
    if len(blob) != PROFILE_BLOB_V1_SIZE:
        raise ProfileBlobError("blob size mismatch")
    if chunk_size < 1 or chunk_size > PROFILE_DATA_MAX_CHUNK:
        raise ProfileBlobError(f"bad chunk_size {chunk_size}")
    offset = 0
    while offset < len(blob):
        piece = blob[offset : offset + chunk_size]
        yield offset, piece
        offset += len(piece)


__all__ = [
    "PROFILE_BLOB_V1_SIZE",
    "PROFILE_DATA_MAX_CHUNK",
    "ProfileBlobError",
    "blob_crc",
    "hid_to_key_name",
    "iter_profile_data_chunks",
    "key_name_to_hid",
    "pack_profile",
    "pack_profile_dict",
    "unpack_profile_dict",
]
