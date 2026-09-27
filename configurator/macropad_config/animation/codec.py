"""Animation blob codec — mirrors firmware/include/anim_format.h (Step 24b).

Blob layout (little-endian)::

    header (32 B)
      0  u32  magic 'MPAN' (0x4E41504D)
      4  u8   version = 1
      5  u8   flags (bit0 = loop)
      6  u16  frame_count (1..1024)
      8  u8   fps (1..30)
      9  u8   width = 128
     10  u8   height = 64
     11  u8   reserved = 0
     12  u32  data_len (bytes of frame records after the header)
     16  u32  data_crc (CRC-32/IEEE of the frame records)
     20  8s   name (ASCII, NUL padded)
     28  u32  header_crc (CRC-32 of bytes 0..27)
    frame records, back to back
      u8 enc (0 RAW, 1 RLE, 2 DELTA), u8 reserved, u16 len, payload[len]

Frames are 1024 bytes in SSD1306 page order: byte ``x + (y // 8) * 128``,
bit ``y % 8`` (bit0 = top row of the page). RLE is PackBits; DELTA is
PackBits of ``frame XOR previous_frame`` (never used for frame 0, so a loop
restart always starts from a key frame). The encoder picks the smallest
encoding per frame.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence

from ..protocol.frames import crc32

MAGIC = 0x4E41504D
VERSION = 1
HEADER_SIZE = 32
REC_HDR_SIZE = 4
WIDTH = 128
HEIGHT = 64
FRAME_BYTES = WIDTH * HEIGHT // 8
MAX_FPS = 30
MAX_FRAMES = 1024
FLAG_LOOP = 0x01

ENC_RAW = 0
ENC_RLE = 1
ENC_DELTA = 2
ENC_NAMES = {ENC_RAW: "RAW", ENC_RLE: "RLE", ENC_DELTA: "DELTA"}

# Flash region (firmware anim.h): 128 KiB directly below the MPFL sector.
REGION_OFFSET = 0x1DF000
REGION_SIZE = 128 * 1024
MAX_FRAMES_RAW = (REGION_SIZE - HEADER_SIZE) // (REC_HDR_SIZE + FRAME_BYTES)  # 127

_HDR = struct.Struct("<IBBHBBBBII8s")  # 28 bytes + header_crc
assert _HDR.size == 28

SETTINGS_SIZE = 8
INFO_SIZE = 40

PREVIEW_STOP = 0
PREVIEW_PLAY = 1
PREVIEW_BUILTIN = 2
PREVIEW_BLANK = 3

DEFAULT_IDLE_S = 60
DEFAULT_BLANK_S = 600


class AnimFormatError(ValueError):
    """Malformed animation blob / frame."""


# --------------------------------------------------------------------------
# PackBits
# --------------------------------------------------------------------------

def packbits_encode(data: bytes) -> bytes:
    """PackBits: c<128 → c+1 literals; c>128 → repeat next byte 257-c times."""
    data = bytes(data)
    n = len(data)
    out = bytearray()
    i = 0
    while i < n:
        j = i + 1
        while j < n and data[j] == data[i] and j - i < 128:
            j += 1
        run = j - i
        if run >= 3:
            out.append(257 - run)
            out.append(data[i])
            i = j
            continue
        start = i
        while i < n and i - start < 128:
            if i + 2 < n and data[i] == data[i + 1] == data[i + 2]:
                break
            i += 1
        out.append(i - start - 1)
        out += data[start:i]
    return bytes(out)


def packbits_decode(data: bytes, out_len: int, *, xor_base: Optional[bytes] = None) -> bytes:
    """Decode exactly ``out_len`` bytes; with ``xor_base`` XOR into it (DELTA)."""
    out = bytearray(xor_base if xor_base is not None else bytes(out_len))
    if len(out) != out_len:
        raise AnimFormatError("xor base length mismatch")
    i = o = 0
    n = len(data)
    xor = xor_base is not None
    while i < n:
        c = data[i]
        i += 1
        if c < 128:
            cnt = c + 1
            if i + cnt > n or o + cnt > out_len:
                raise AnimFormatError("PackBits literal overruns")
            for k in range(cnt):
                out[o + k] = (out[o + k] ^ data[i + k]) if xor else data[i + k]
            i += cnt
            o += cnt
        elif c > 128:
            cnt = 257 - c
            if i >= n or o + cnt > out_len:
                raise AnimFormatError("PackBits run overruns")
            v = data[i]
            i += 1
            for k in range(cnt):
                out[o + k] = (out[o + k] ^ v) if xor else v
            o += cnt
        else:
            raise AnimFormatError("PackBits control byte 128 is reserved")
    if o != out_len:
        raise AnimFormatError(f"PackBits produced {o} bytes, want {out_len}")
    return bytes(out)


# --------------------------------------------------------------------------
# Frame records
# --------------------------------------------------------------------------

def _check_frame(frame: bytes) -> bytes:
    frame = bytes(frame)
    if len(frame) != FRAME_BYTES:
        raise AnimFormatError(f"frame must be {FRAME_BYTES} bytes, got {len(frame)}")
    return frame


def encode_record(frame: bytes, prev: Optional[bytes] = None, *, allow_delta: bool = True) -> bytes:
    """Smallest of RAW / RLE / DELTA (DELTA only when ``prev`` given)."""
    frame = _check_frame(frame)
    best_enc, best = ENC_RAW, frame
    rle = packbits_encode(frame)
    if len(rle) < len(best):
        best_enc, best = ENC_RLE, rle
    if prev is not None and allow_delta:
        x = bytes(a ^ b for a, b in zip(frame, _check_frame(prev)))
        d = packbits_encode(x)
        if len(d) < len(best):
            best_enc, best = ENC_DELTA, d
    return struct.pack("<BBH", best_enc, 0, len(best)) + best


def decode_record(buf: bytes, offset: int, prev: bytes) -> tuple[bytes, int, int]:
    """Decode record at ``offset`` → (frame, bytes_used, enc)."""
    if offset + REC_HDR_SIZE > len(buf):
        raise AnimFormatError("truncated record header")
    enc, _res, ln = struct.unpack_from("<BBH", buf, offset)
    start = offset + REC_HDR_SIZE
    if start + ln > len(buf):
        raise AnimFormatError("truncated record payload")
    pl = bytes(buf[start:start + ln])
    if enc == ENC_RAW:
        if ln != FRAME_BYTES:
            raise AnimFormatError("RAW record must be 1024 bytes")
        frame = pl
    elif enc == ENC_RLE:
        frame = packbits_decode(pl, FRAME_BYTES)
    elif enc == ENC_DELTA:
        frame = packbits_decode(pl, FRAME_BYTES, xor_base=prev)
    else:
        raise AnimFormatError(f"unknown record encoding {enc}")
    return frame, REC_HDR_SIZE + ln, enc


# --------------------------------------------------------------------------
# Blob
# --------------------------------------------------------------------------

@dataclass
class AnimBlob:
    frames: List[bytes]
    fps: int
    loop: bool = True
    name: str = ""
    encodings: List[int] = field(default_factory=list)
    data_len: int = 0

    @property
    def total_len(self) -> int:
        return HEADER_SIZE + self.data_len


def _clean_name(name: str) -> bytes:
    raw = (name or "").encode("ascii", errors="replace")[:8]
    return raw.ljust(8, b"\x00")


def build_blob(frames: Sequence[bytes], fps: int, loop: bool = True, name: str = "") -> bytes:
    if not frames:
        raise AnimFormatError("animation needs at least one frame")
    if len(frames) > MAX_FRAMES:
        raise AnimFormatError(f"too many frames ({len(frames)} > {MAX_FRAMES})")
    fps = int(fps)
    if not 1 <= fps <= MAX_FPS:
        raise AnimFormatError(f"fps must be 1..{MAX_FPS}")
    data = bytearray()
    prev: Optional[bytes] = None
    for f in frames:
        data += encode_record(f, prev)
        prev = _check_frame(f)
    hdr = _HDR.pack(
        MAGIC, VERSION, FLAG_LOOP if loop else 0, len(frames), fps, WIDTH, HEIGHT, 0,
        len(data), crc32(bytes(data)), _clean_name(name),
    )
    return hdr + struct.pack("<I", crc32(hdr)) + bytes(data)


def parse_header(blob: bytes) -> dict:
    if len(blob) < HEADER_SIZE:
        raise AnimFormatError("blob shorter than header")
    (magic, ver, flags, count, fps, w, h, _r, data_len, data_crc, name) = _HDR.unpack_from(blob, 0)
    (hcrc,) = struct.unpack_from("<I", blob, 28)
    if magic != MAGIC:
        raise AnimFormatError(f"bad magic 0x{magic:08X}")
    if ver != VERSION:
        raise AnimFormatError(f"unsupported version {ver}")
    if crc32(bytes(blob[:28])) != hcrc:
        raise AnimFormatError("header CRC mismatch")
    if not 1 <= count <= MAX_FRAMES or not 1 <= fps <= MAX_FPS:
        raise AnimFormatError("frame_count/fps out of range")
    if (w, h) != (WIDTH, HEIGHT):
        raise AnimFormatError(f"unsupported size {w}x{h}")
    return {
        "version": ver, "flags": flags, "loop": bool(flags & FLAG_LOOP),
        "frame_count": count, "fps": fps, "data_len": data_len,
        "data_crc": data_crc, "name": name.rstrip(b"\x00").decode("ascii", "replace"),
    }


def parse_blob(blob: bytes) -> AnimBlob:
    """Full validation (same rules as firmware anim_validate) + decode."""
    hdr = parse_header(blob)
    data_len = hdr["data_len"]
    if HEADER_SIZE + data_len > len(blob):
        raise AnimFormatError("blob truncated")
    data = bytes(blob[HEADER_SIZE:HEADER_SIZE + data_len])
    if crc32(data) != hdr["data_crc"]:
        raise AnimFormatError("data CRC mismatch")
    frames: List[bytes] = []
    encs: List[int] = []
    prev = bytes(FRAME_BYTES)
    off = 0
    for i in range(hdr["frame_count"]):
        if i == 0 and off < len(data) and data[off] == ENC_DELTA:
            raise AnimFormatError("frame 0 must not be DELTA")
        frame, used, enc = decode_record(data, off, prev)
        frames.append(frame)
        encs.append(enc)
        prev = frame
        off += used
    if off != data_len:
        raise AnimFormatError("trailing bytes after last frame")
    return AnimBlob(frames=frames, fps=hdr["fps"], loop=hdr["loop"], name=hdr["name"],
                    encodings=encs, data_len=data_len)


def blob_stats(blob: bytes) -> dict:
    parsed = parse_blob(blob)
    counts = {name: 0 for name in ENC_NAMES.values()}
    for e in parsed.encodings:
        counts[ENC_NAMES[e]] += 1
    return {
        "total_len": len(blob), "frames": len(parsed.frames),
        "raw_len": HEADER_SIZE + len(parsed.frames) * (REC_HDR_SIZE + FRAME_BYTES),
        "region_size": REGION_SIZE, "fits": len(blob) <= REGION_SIZE,
        "encodings": counts,
    }


# --------------------------------------------------------------------------
# Pixel helpers (page order)
# --------------------------------------------------------------------------

def blank_frame() -> bytearray:
    return bytearray(FRAME_BYTES)


def get_pixel(frame: bytes, x: int, y: int) -> bool:
    if 0 <= x < WIDTH and 0 <= y < HEIGHT:
        return bool(frame[x + (y >> 3) * WIDTH] & (1 << (y & 7)))
    return False


def set_pixel(frame: bytearray, x: int, y: int, on: bool = True) -> None:
    if 0 <= x < WIDTH and 0 <= y < HEIGHT:
        idx = x + (y >> 3) * WIDTH
        bit = 1 << (y & 7)
        if on:
            frame[idx] |= bit
        else:
            frame[idx] &= ~bit & 0xFF


def frame_from_bits(bits: Sequence[int]) -> bytes:
    """Row-major 0/1 list (128*64) → page-order frame."""
    if len(bits) != WIDTH * HEIGHT:
        raise AnimFormatError("need 8192 pixels")
    f = bytearray(FRAME_BYTES)
    for y in range(HEIGHT):
        row = y * WIDTH
        page = (y >> 3) * WIDTH
        bit = 1 << (y & 7)
        for x in range(WIDTH):
            if bits[row + x]:
                f[page + x] |= bit
    return bytes(f)


def frame_to_bits(frame: bytes) -> bytearray:
    frame = _check_frame(frame)
    out = bytearray(WIDTH * HEIGHT)
    for y in range(HEIGHT):
        row = y * WIDTH
        page = (y >> 3) * WIDTH
        bit = 1 << (y & 7)
        for x in range(WIDTH):
            if frame[page + x] & bit:
                out[row + x] = 1
    return out


def invert_frame(frame: bytes) -> bytes:
    return bytes(b ^ 0xFF for b in _check_frame(frame))


def shift_frame(frame: bytes, dx: int, dy: int, *, wrap: bool = True) -> bytes:
    bits = frame_to_bits(frame)
    out = bytearray(WIDTH * HEIGHT)
    for y in range(HEIGHT):
        for x in range(WIDTH):
            if not bits[y * WIDTH + x]:
                continue
            nx, ny = x + dx, y + dy
            if wrap:
                nx %= WIDTH
                ny %= HEIGHT
            elif not (0 <= nx < WIDTH and 0 <= ny < HEIGHT):
                continue
            out[ny * WIDTH + nx] = 1
    return frame_from_bits(out)


def frame_pixel_count(frame: bytes) -> int:
    return sum(bin(b).count("1") for b in frame)


# --------------------------------------------------------------------------
# Wire helpers (ANIM_SETTINGS / ANIM_INFO payloads)
# --------------------------------------------------------------------------

def pack_settings(enabled: bool, idle_timeout_s: int, blank_timeout_s: int) -> bytes:
    for v, n in ((idle_timeout_s, "idle_timeout_s"), (blank_timeout_s, "blank_timeout_s")):
        if not 0 <= int(v) <= 0xFFFF:
            raise ValueError(f"{n} must be 0..65535 s")
    return struct.pack("<BBHHH", 1 if enabled else 0, 0, int(idle_timeout_s), int(blank_timeout_s), 0)


def unpack_settings(payload: bytes) -> dict:
    if len(payload) < SETTINGS_SIZE:
        raise AnimFormatError("settings payload too short")
    en, _flags, idle, blank, _r = struct.unpack_from("<BBHHH", payload, 0)
    return {"enabled": bool(en), "idle_timeout_s": idle, "blank_timeout_s": blank}


def parse_anim_info(payload: bytes) -> dict:
    if len(payload) < INFO_SIZE:
        raise AnimFormatError(f"ANIM_INFO payload too short ({len(payload)})")
    st = payload[0]
    (count,) = struct.unpack_from("<H", payload, 2)
    total, crc, region = struct.unpack_from("<III", payload, 6)
    (max_raw,) = struct.unpack_from("<H", payload, 18)
    bus, wall, got = struct.unpack_from("<III", payload, 20)
    return {
        "stored_valid": bool(st & 0x01), "uploading": bool(st & 0x02),
        "playing": bool(st & 0x04), "blanked": bool(st & 0x08),
        "builtin_active": bool(st & 0x10), "preview": bool(st & 0x20),
        "region_ok": bool(st & 0x40), "status": st,
        "format_version": payload[1], "frame_count": count, "fps": payload[4],
        "flags": payload[5], "loop": bool(payload[5] & FLAG_LOOP),
        "total_len": total, "crc": crc, "region_size": region, "max_frames_raw": max_raw,
        "last_frame_bus_us": bus, "last_frame_wall_us": wall, "upload_got": got,
        "name": bytes(payload[32:40]).rstrip(b"\x00").decode("ascii", "replace"),
    }


def iter_chunks(blob: bytes, size: int = 48) -> Iterable[tuple[int, bytes]]:
    off = 0
    while off < len(blob):
        piece = blob[off:off + size]
        yield off, piece
        off += len(piece)
