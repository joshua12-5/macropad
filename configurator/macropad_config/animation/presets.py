"""Built-in procedural animations (Step 24b), generated in Python.

Every preset returns ``(frames, fps)`` where frames are 1024-byte page-order
buffers ready for :func:`codec.build_blob`. All presets loop seamlessly.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple

from . import codec as A
from .font5x7 import ADVANCE, GLYPH_H, glyph, text_width

W, H = A.WIDTH, A.HEIGHT


class Canvas:
    """Row-major 1bpp scratch canvas with a few drawing primitives."""

    def __init__(self) -> None:
        self.bits = bytearray(W * H)

    def clear(self) -> None:
        self.bits[:] = bytes(W * H)

    def set(self, x: int, y: int, on: int = 1) -> None:
        if 0 <= x < W and 0 <= y < H:
            self.bits[y * W + x] = 1 if on else 0

    def get(self, x: int, y: int) -> int:
        if 0 <= x < W and 0 <= y < H:
            return self.bits[y * W + x]
        return 0

    def rect(self, x: int, y: int, w: int, h: int, fill: bool = False) -> None:
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                if fill or yy in (y, y + h - 1) or xx in (x, x + w - 1):
                    self.set(xx, yy)

    def circle(self, cx: float, cy: float, r: float) -> None:
        if r <= 0:
            self.set(round(cx), round(cy))
            return
        steps = max(12, int(r * 7))
        for i in range(steps):
            a = 2 * math.pi * i / steps
            self.set(round(cx + r * math.cos(a)), round(cy + r * math.sin(a)))

    def text(self, x: int, y: int, s: str, scale: int = 1) -> None:
        cx = x
        for ch in s:
            g = glyph(ch)
            for col in range(5):
                bits = g[col]
                for row in range(GLYPH_H):
                    if bits & (1 << row):
                        for sy in range(scale):
                            for sx in range(scale):
                                self.set(cx + col * scale + sx, y + row * scale + sy)
            cx += ADVANCE * scale

    def frame(self) -> bytes:
        return A.frame_from_bits(self.bits)


def _tri(t: float) -> float:
    """Triangle wave 0→1→0 over t in [0, 1)."""
    t %= 1.0
    return 2 * t if t < 0.5 else 2 * (1 - t)


# --------------------------------------------------------------------------

def starfield(frames: int = 60, stars: int = 48, seed: int = 7, fps: int = 20) -> Tuple[List[bytes], int]:
    """3D warp starfield (same look as the firmware's built-in fallback).

    Stars have periodic depth so the loop closes: each star's z decreases by
    a fixed step and wraps exactly after ``frames`` frames.
    """
    rng = random.Random(seed)
    table = []
    for _ in range(stars):
        sx = rng.uniform(-256, 256)
        sy = rng.uniform(-128, 128)
        phase = rng.random()
        table.append((sx, sy, phase))
    out: List[bytes] = []
    c = Canvas()
    for f in range(frames):
        c.clear()
        for sx, sy, phase in table:
            z = 64.0 * (1.0 - ((phase + f / frames) % 1.0)) + 1.0  # 65 → 1
            px = int(64 + sx * 8 / z)
            py = int(32 + sy * 8 / z)
            if not (0 <= px < W and 0 <= py < H):
                continue
            c.set(px, py)
            if z < 20:
                c.set(px + 1, py)
            if z < 10:
                c.set(px, py + 1)
                c.set(px + 1, py + 1)
        out.append(c.frame())
    return out, fps


def bouncing_text(text: str = "MACROPAD", frames: int = 60, scale: int = 2,
                  border: bool = True, fps: int = 20) -> Tuple[List[bytes], int]:
    """DVD-logo style bounce. x/y follow triangle waves with 2 and 3 bounces
    per loop so the animation is seamless."""
    text = text or "MACROPAD"
    while scale > 1 and text_width(text, scale) > W - 4:
        scale -= 1
    tw = text_width(text, scale)
    th = GLYPH_H * scale
    pad = 2 if border else 0
    rx = max(0, W - tw - 2 * pad)
    ry = max(0, H - th - 2 * pad)
    out: List[bytes] = []
    c = Canvas()
    for f in range(frames):
        c.clear()
        if border:
            c.rect(0, 0, W, H)
        x = pad + round(_tri(2 * f / frames) * rx)
        y = pad + round(_tri(3 * f / frames + 0.25) * ry)
        c.text(x, y, text, scale)
        out.append(c.frame())
    return out, fps


def scroll_text(text: str = "HELLO FROM MACROPAD", scale: int = 2, speed: int = 2,
                fps: int = 25) -> Tuple[List[bytes], int]:
    """Right-to-left marquee, vertically centred; loops when the text has
    fully left the screen (frame count = (128 + width) / speed)."""
    text = text or " "
    tw = text_width(text, scale)
    th = GLYPH_H * scale
    speed = max(1, int(speed))
    span = W + tw + ADVANCE * scale
    count = max(1, math.ceil(span / speed))
    y = (H - th) // 2
    out: List[bytes] = []
    c = Canvas()
    for f in range(min(count, A.MAX_FRAMES)):
        c.clear()
        c.text(W - f * speed, y, text, scale)
        # thin rails top/bottom for a ticker look
        for x in range(0, W, 2):
            c.set(x, y - 4)
            c.set(x, y + th + 3)
        out.append(c.frame())
    return out, fps


_BAYER4 = (
    (0, 8, 2, 10),
    (12, 4, 14, 6),
    (3, 11, 1, 9),
    (15, 7, 13, 5),
)


def pulse(frames: int = 40, fps: int = 20) -> Tuple[List[bytes], int]:
    """Breathing glow: a radial gradient whose brightness follows a raised
    cosine, rendered with a 4x4 ordered (Bayer) dither, plus an outer ring
    that expands with the breath."""
    out: List[bytes] = []
    c = Canvas()
    cx, cy = (W - 1) / 2, (H - 1) / 2
    rmax = 30.0
    for f in range(frames):
        b = 0.5 - 0.5 * math.cos(2 * math.pi * f / frames)  # 0..1..0
        c.clear()
        for y in range(H):
            for x in range(W):
                d = math.hypot(x - cx, (y - cy) * 1.0) / rmax
                lvl = max(0.0, 1.0 - d) * (0.25 + 0.75 * b)
                if lvl * 16 > _BAYER4[y & 3][x & 3] + 0.5:
                    c.bits[y * W + x] = 1
        c.circle(cx, cy, 8 + 22 * b)
        out.append(c.frame())
    return out, fps


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    fn: Callable[..., Tuple[List[bytes], int]]
    takes_text: bool = False
    default_text: str = ""


PRESETS: Dict[str, Preset] = {
    "starfield": Preset("starfield", "Starfield (warp)", starfield),
    "bounce": Preset("bounce", "Bouncing text", bouncing_text, True, "MACROPAD"),
    "scroll": Preset("scroll", "Scrolling text", scroll_text, True, "HELLO FROM MACROPAD"),
    "pulse": Preset("pulse", "Pulse / breathing", pulse),
}


def generate(key: str, text: str | None = None) -> Tuple[List[bytes], int]:
    p = PRESETS[key]
    if p.takes_text:
        return p.fn(text=text if text is not None else p.default_text)
    return p.fn()
