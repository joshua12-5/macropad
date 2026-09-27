"""Image / GIF import → 128x64 1bpp OLED frames (Step 24b).

Uses QtGui (QImageReader handles GIF animation, PNG, JPEG, BMP, WebP…), so
no Pillow dependency. Pipeline per source image:

1. composite alpha onto the chosen background (black by default);
2. scale to fit 128x64 keeping aspect ratio (smooth), centre on black;
3. convert to 8-bit grey;
4. optional invert; then threshold or Floyd–Steinberg error diffusion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from . import codec as A

DITHER_THRESHOLD = "threshold"
DITHER_FLOYD = "floyd-steinberg"
DITHER_MODES = (DITHER_THRESHOLD, DITHER_FLOYD)


@dataclass
class ImportOptions:
    dither: str = DITHER_FLOYD
    threshold: int = 128
    invert: bool = False
    fit: str = "contain"          # "contain" (letterbox) or "stretch"
    background_white: bool = False  # alpha composites onto white instead of black


def _qt():
    from PySide6 import QtCore, QtGui  # local import: keep package Qt-free

    return QtCore, QtGui


def read_image_frames(path: str | Path) -> Tuple[list, Optional[int]]:
    """Return (QImage list, fps guess from GIF delays or None)."""
    QtCore, QtGui = _qt()
    reader = QtGui.QImageReader(str(path))
    reader.setAutoTransform(True)
    if not reader.canRead():
        raise ValueError(f"cannot read image {path}: {reader.errorString()}")
    images = []
    delays = []
    while True:
        img = reader.read()
        if img.isNull():
            break
        images.append(img)
        d = reader.nextImageDelay()
        if d > 0:
            delays.append(d)
        if len(images) >= A.MAX_FRAMES or not reader.supportsAnimation():
            break
    if not images:
        raise ValueError(f"no frames in {path}: {reader.errorString()}")
    fps = None
    if delays:
        avg = sum(delays) / len(delays)
        fps = max(1, min(A.MAX_FPS, round(1000 / max(1, avg))))
    return images, fps


def _natural_key(p: Path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)]


def sort_sequence(paths: Sequence[str | Path]) -> List[Path]:
    return sorted((Path(p) for p in paths), key=_natural_key)


def image_to_gray(img, opts: ImportOptions) -> bytearray:
    """QImage → 128x64 grey bytes (row-major), fitted + centred."""
    QtCore, QtGui = _qt()
    W, H = A.WIDTH, A.HEIGHT
    src = img.convertToFormat(QtGui.QImage.Format_ARGB32)
    if opts.fit == "stretch":
        scaled = src.scaled(W, H, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation)
    else:
        scaled = src.scaled(W, H, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
    canvas = QtGui.QImage(W, H, QtGui.QImage.Format_ARGB32)
    canvas.fill(QtGui.QColor(0, 0, 0))
    p = QtGui.QPainter(canvas)
    bg = QtGui.QColor(255, 255, 255) if opts.background_white else QtGui.QColor(0, 0, 0)
    x0 = (W - scaled.width()) // 2
    y0 = (H - scaled.height()) // 2
    p.fillRect(x0, y0, scaled.width(), scaled.height(), bg)
    p.drawImage(x0, y0, scaled)
    p.end()
    gray = canvas.convertToFormat(QtGui.QImage.Format_Grayscale8)
    out = bytearray(W * H)
    bpl = gray.bytesPerLine()
    raw = bytes(gray.constBits())[: bpl * H]
    for y in range(H):
        out[y * W:(y + 1) * W] = raw[y * bpl:y * bpl + W]
    return out


def gray_to_frame(gray: Sequence[int], opts: ImportOptions) -> bytes:
    W, H = A.WIDTH, A.HEIGHT
    vals = [255 - v for v in gray] if opts.invert else list(gray)
    bits = bytearray(W * H)
    if opts.dither == DITHER_FLOYD:
        buf = [float(v) for v in vals]
        for y in range(H):
            row = y * W
            for x in range(W):
                i = row + x
                old = buf[i]
                new = 255.0 if old >= 128.0 else 0.0
                bits[i] = 1 if new else 0
                err = old - new
                if x + 1 < W:
                    buf[i + 1] += err * 7 / 16
                if y + 1 < H:
                    if x > 0:
                        buf[i + W - 1] += err * 3 / 16
                    buf[i + W] += err * 5 / 16
                    if x + 1 < W:
                        buf[i + W + 1] += err * 1 / 16
    else:
        t = int(opts.threshold)
        for i, v in enumerate(vals):
            bits[i] = 1 if v >= t else 0
    return A.frame_from_bits(bits)


def image_to_frame(img, opts: ImportOptions) -> bytes:
    return gray_to_frame(image_to_gray(img, opts), opts)


def import_files(paths: Sequence[str | Path], opts: ImportOptions) -> Tuple[List[bytes], Optional[int]]:
    """GIF (all frames) / single image / image sequence → (frames, fps guess)."""
    paths = list(paths)
    if not paths:
        return [], None
    if len(paths) == 1:
        images, fps = read_image_frames(paths[0])
    else:
        images, fps = [], None
        for p in sort_sequence(paths):
            imgs, _ = read_image_frames(p)
            images.append(imgs[0])
    frames = [image_to_frame(img, opts) for img in images[: A.MAX_FRAMES]]
    return frames, fps
