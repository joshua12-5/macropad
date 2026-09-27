"""Minimal GIF89a writer — no Pillow needed.

Used for "Export GIF…" in the animation editor, the preset preview image and
smoke round-trips. Frames are 1bpp OLED frames rendered with an on/off
colour, optionally scaled up by an integer factor.
"""

from __future__ import annotations

import struct
from collections.abc import Iterable, Sequence

from . import codec as A

RGB = tuple[int, int, int]
OLED_ON: RGB = (0xE6, 0xF3, 0xFF)
OLED_OFF: RGB = (0x05, 0x07, 0x0C)


def _lzw_encode(indices: bytes, min_code_size: int) -> bytes:
    clear = 1 << min_code_size
    eoi = clear + 1
    out = bytearray()
    bitbuf = 0
    nbits = 0

    def emit(code: int, width: int) -> None:
        nonlocal bitbuf, nbits
        bitbuf |= code << nbits
        nbits += width
        while nbits >= 8:
            out.append(bitbuf & 0xFF)
            bitbuf >>= 8
            nbits -= 8

    width = min_code_size + 1
    table = {bytes([i]): i for i in range(clear)}
    next_code = eoi + 1
    emit(clear, width)
    w = b""
    for b in indices:
        wc = w + bytes([b])
        if wc in table:
            w = wc
            continue
        emit(table[w], width)
        if next_code < 4096:
            table[wc] = next_code
            next_code += 1
            if next_code > (1 << width) and width < 12:
                width += 1
        else:
            emit(clear, width)
            table = {bytes([i]): i for i in range(clear)}
            next_code = eoi + 1
            width = min_code_size + 1
        w = bytes([b])
    if w:
        emit(table[w], width)
    emit(eoi, width)
    if nbits:
        out.append(bitbuf & 0xFF)
    return bytes(out)


def _sub_blocks(data: bytes) -> bytes:
    out = bytearray()
    for i in range(0, len(data), 255):
        chunk = data[i : i + 255]
        out.append(len(chunk))
        out += chunk
    out.append(0)
    return bytes(out)


def encode_gif(
    frames: Sequence[bytes],
    width: int,
    height: int,
    palette: Sequence[RGB],
    delay_cs: int | Sequence[int] = 5,
    loop: bool = True,
) -> bytes:
    """frames: palette-index bytes (width*height each)."""
    pal = list(palette)
    size_bits = 1
    while (1 << size_bits) < max(2, len(pal)):
        size_bits += 1
    while len(pal) < (1 << size_bits):
        pal.append((0, 0, 0))
    min_code = max(2, size_bits)
    out = bytearray(b"GIF89a")
    out += struct.pack("<HHBBB", width, height, 0x80 | (size_bits - 1), 0, 0)
    for r, g, b in pal:
        out += bytes((r, g, b))
    if loop:
        out += b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"
    delays = [delay_cs] * len(frames) if isinstance(delay_cs, int) else list(delay_cs)
    for idx, frame in enumerate(frames):
        if len(frame) != width * height:
            raise ValueError("frame size mismatch")
        out += b"\x21\xf9\x04" + struct.pack("<BHBB", 0x04, max(2, int(delays[idx])), 0, 0)
        out += b"\x2c" + struct.pack("<HHHHB", 0, 0, width, height, 0)
        out.append(min_code)
        out += _sub_blocks(_lzw_encode(bytes(frame), min_code))
    out += b"\x3b"
    return bytes(out)


def oled_frames_to_indices(frames: Iterable[bytes], scale: int = 1) -> list[bytes]:
    res: list[bytes] = []
    W, H = A.WIDTH, A.HEIGHT
    for f in frames:
        bits = A.frame_to_bits(f)
        if scale == 1:
            res.append(bytes(bits))
            continue
        rows = bytearray()
        for y in range(H):
            row = bytearray()
            for x in range(W):
                row += bytes([bits[y * W + x]]) * scale
            rows += bytes(row) * scale
        res.append(bytes(rows))
    return res


def write_oled_gif(
    path,
    frames: Sequence[bytes],
    fps: int,
    *,
    scale: int = 1,
    loop: bool = True,
    on: RGB = OLED_ON,
    off: RGB = OLED_OFF,
) -> bytes:
    idx = oled_frames_to_indices(frames, scale)
    delay = max(2, round(100 / max(1, int(fps))))
    data = encode_gif(idx, A.WIDTH * scale, A.HEIGHT * scale, [off, on], delay, loop)
    if path is not None:
        with open(path, "wb") as fh:
            fh.write(data)
    return data
