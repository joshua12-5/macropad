#!/usr/bin/env python3
"""Headless smoke: the firmware's OLED menu, built and run on the host.

Compiles firmware/src/{menu,device_menu,oled_ui,oled_gfx,oled_font}.c with the
host stubs in firmware/tests/host/ and runs oled_menu_test.c, which drives the
menu with the same inputs main.c sends (turn / short press / hold / timeout)
and checks navigation, wrapping, back / exit, the 9 s timeout, toasts and that
profile switches and idle-setting changes schedule the debounced flash persist.
The framebuffer dumps are converted to 4x PNGs with an OLED look.

Usage:
  cd configurator
  python scripts/smoke_oled_menu.py [--out DIR]    # DIR gets the PNGs

Skipped (exit 0) when no host C compiler is available.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
FW = REPO / "firmware"
HOST = FW / "tests" / "host"
SOURCES = ["menu.c", "device_menu.c", "oled_ui.c", "oled_gfx.c", "oled_font.c"]

# OLED look: white-blue pixels on black, 4x, with a faint gap between pixels.
SCALE = 4
LIT = (214, 236, 255)
LIT_EDGE = (120, 150, 190)
DARK = (6, 8, 12)
BEZEL = 12

failures: list[str] = []


def expect(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)
        print(f"    FAIL: {msg}")


def read_pbm(path: Path) -> tuple[int, int, list[list[int]]]:
    tokens = path.read_text().split()
    if tokens[0] != "P1":
        raise ValueError(f"{path.name}: not a P1 PBM")
    w, h = int(tokens[1]), int(tokens[2])
    bits = "".join(tokens[3:])
    if len(bits) != w * h:
        raise ValueError(f"{path.name}: {len(bits)} pixels, expected {w * h}")
    return w, h, [[1 if bits[y * w + x] == "1" else 0 for x in range(w)] for y in range(h)]


def write_png(path: Path, w: int, h: int, rows: list[bytes]) -> None:
    raw = b"".join(b"\x00" + r for r in rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


def oled_png(pbm: Path, png: Path) -> tuple[int, int]:
    w, h, px = read_pbm(pbm)
    ow, oh = w * SCALE + 2 * BEZEL, h * SCALE + 2 * BEZEL
    rows: list[bytes] = []
    for oy in range(oh):
        row = bytearray()
        for ox in range(ow):
            x, y = ox - BEZEL, oy - BEZEL
            if 0 <= x < w * SCALE and 0 <= y < h * SCALE and px[y // SCALE][x // SCALE]:
                edge = (x % SCALE == SCALE - 1) or (y % SCALE == SCALE - 1)
                row += bytes(LIT_EDGE if edge else LIT)
            else:
                row += bytes(DARK)
        rows.append(bytes(row))
    write_png(png, ow, oh, rows)
    return ow, oh


def check_sources() -> None:
    print("smoke_oled_menu: sources")
    cmake = (FW / "CMakeLists.txt").read_text()
    for name in SOURCES:
        expect((FW / "src" / name).is_file(), f"missing firmware/src/{name}")
        expect(f"src/{name}" in cmake, f"firmware/CMakeLists.txt does not build src/{name}")
    # The engine and the drawing code must stay SDK-free (host-buildable).
    for name in ("menu.c", "oled_gfx.c"):
        text = (FW / "src" / name).read_text()
        expect(not re.search(r'#include\s+"(pico|hardware)/', text), f"{name} includes Pico SDK headers")
    main_c = (FW / "src" / "main.c").read_text()
    expect("profile_select" not in main_c, "main.c still has the old ad-hoc profile picker")
    expect("device_menu_input(MENU_IN_BACK)" in main_c, "main.c: hold should go back in the menu")
    print("    menu engine is SDK-free; CMake builds the menu sources")


def run(out: Path | None) -> None:
    print("smoke_oled_menu: host build + navigation checks")
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not cc:
        print("    SKIP: no host C compiler")
        return
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        exe = t / "oled_menu_test"
        cmd = [
            cc,
            "-std=c11",
            "-O1",
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-I{FW / 'include'}",
            f"-I{HOST / 'shim'}",
            *[str(FW / "src" / s) for s in SOURCES],
            str(HOST / "stubs.c"),
            str(HOST / "oled_menu_test.c"),
            "-o",
            str(exe),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        expect(r.returncode == 0, f"host compile failed:\n{r.stderr}")
        if r.returncode:
            return
        frames = t / "frames"
        frames.mkdir()
        r = subprocess.run([str(exe), str(frames)], capture_output=True, text=True)
        for line in r.stdout.splitlines():
            if line.startswith(("FAIL", "OK:")):
                print(f"    {line}")
        expect(r.returncode == 0, "oled_menu_test reported failures")
        pbms = sorted(frames.glob("*.pbm"))
        expected = {"home", "main_menu", "profiles", "toast_switched", "idle", "device_info", "toast_saved"}
        expect(expected <= {p.stem for p in pbms}, f"missing frames: {expected - {p.stem for p in pbms}}")
        dest = out or (t / "png")
        dest.mkdir(parents=True, exist_ok=True)
        for p in pbms:
            _, _, px = read_pbm(p)
            expect(any(any(row) for row in px), f"{p.stem}: blank frame")
            size = oled_png(p, dest / f"{p.stem}.png")
            expect(size == (128 * SCALE + 2 * BEZEL, 64 * SCALE + 2 * BEZEL), f"{p.stem}: PNG size {size}")
        print(f"    {len(pbms)} frames → {dest if out else 'temp dir'} ({SCALE}x PNG)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=os.environ.get("OLED_SHOTS_DIR") or None)
    args = ap.parse_args()
    check_sources()
    run(Path(args.out) if args.out else None)
    if failures:
        print(f"smoke_oled_menu: {len(failures)} failure(s)")
        return 1
    print("smoke_oled_menu: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
