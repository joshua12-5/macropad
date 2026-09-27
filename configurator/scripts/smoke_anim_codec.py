#!/usr/bin/env python3
"""Headless smoke: OLED idle-animation format + authoring helpers.

* PackBits / record / blob encode-decode (edge cases, all presets, corruption);
* Python constants vs firmware headers (anim_format.h, anim.h,
  config_protocol.h) and the 5x7 font vs firmware/src/oled_font.c;
* firmware/src/anim_codec.c compiled for the host (``cc``) validates and
  decodes the Python-built blobs bit-exactly (skipped when no C compiler);
* GIF writer → QImageReader round-trip, image import (fit/centre, threshold,
  Floyd–Steinberg, invert), project JSON save/load.

Usage:
  cd configurator
  QT_QPA_PLATFORM=offscreen python scripts/smoke_anim_codec.py
"""

from __future__ import annotations

import os
import random
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from macropad_config.animation import codec as A
from macropad_config.animation import font5x7
from macropad_config.animation import presets as P
from macropad_config.animation.gifwriter import write_oled_gif
from macropad_config.animation.project import AnimationProject, ProjectError
from macropad_config.protocol import frames as F

FAILS: list[str] = []


def expect(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)
        print(f"  FAIL: {msg}")


def raises(fn, exc=A.AnimFormatError) -> bool:
    try:
        fn()
    except exc:
        return True
    return False


def c_define(text: str, name: str) -> str:
    m = re.search(rf"#define\s+{name}\s+(.+?)(?:/\*|$)", text, re.M)
    return m.group(1).strip() if m else ""


def c_int(text: str, name: str) -> int:
    v = c_define(text, name).rstrip("u").rstrip("U")
    return int(v, 0)


def check_packbits() -> None:
    print("smoke_anim_codec: PackBits")
    rng = random.Random(24)
    cases = [
        bytes(1024),
        bytes([0xFF]) * 1024,
        bytes(range(256)) * 4,
        bytes([1, 2]) * 512,
        bytes([7]) * 127 + bytes([8]) * 129 + bytes([9]) * 768,
    ]
    for n in (1, 2, 3, 127, 128, 129, 130, 256, 257):
        cases.append(bytes([5]) * n)
        cases.append(bytes(rng.randrange(256) for _ in range(n)))
    for _ in range(40):
        cases.append(bytes(rng.choice((0, 0, 0, 255, rng.randrange(256))) for _ in range(1024)))
    for c in cases:
        enc = A.packbits_encode(c)
        expect(A.packbits_decode(enc, len(c)) == c, f"packbits roundtrip len {len(c)}")
        # control bytes never 128
        i = 0
        while i < len(enc):
            ctl = enc[i]
            expect(ctl != 128, "control byte 128 emitted")
            i += 1 + (ctl + 1 if ctl < 128 else 1)
    expect(len(A.packbits_encode(bytes(1024))) == 16, "1024 zeros → 8 runs of 128 (16 B)")
    expect(raises(lambda: A.packbits_decode(b"\x80\x00", 2)), "128 rejected")
    expect(raises(lambda: A.packbits_decode(b"\x05\x01", 6)), "truncated literal rejected")
    expect(raises(lambda: A.packbits_decode(b"\xff\x01", 3)), "short output rejected")
    base = bytes(rng.randrange(256) for _ in range(1024))
    delta = bytes(a ^ b for a, b in zip(base, bytes(1024), strict=True))
    expect(A.packbits_decode(A.packbits_encode(delta), 1024, xor_base=bytes(1024)) == base, "xor decode")


def check_blobs() -> dict:
    print("smoke_anim_codec: blobs + presets")
    out = {}
    for key in P.PRESETS:
        frames, fps = P.generate(key)
        expect(all(len(f) == A.FRAME_BYTES for f in frames), f"{key} frame size")
        expect(len(frames) >= 10, f"{key} has {len(frames)} frames")
        blob = A.build_blob(frames, fps, True, key)
        back = A.parse_blob(blob)
        expect(
            back.frames == frames and back.fps == fps and back.loop and back.name == key[:8],
            f"{key} roundtrip",
        )
        expect(back.encodings[0] != A.ENC_DELTA, f"{key} frame 0 is a key frame")
        expect(len(blob) < A.REGION_SIZE, f"{key} fits region ({len(blob)} B)")
        out[key] = blob
        print(
            f"    {key:<9} {len(frames):4d} frames @ {fps} fps → {len(blob):6d} B "
            f"({len(blob) / len(frames):.0f} B/frame, enc {A.blob_stats(blob)['encodings']})"
        )
    # text presets react to user text
    f1, _ = P.scroll_text("A")
    f2, _ = P.scroll_text("A MUCH LONGER TICKER TEXT")
    expect(len(f2) > len(f1), "scroll length depends on text")
    fb, _ = P.bouncing_text("HI")
    expect(A.frame_pixel_count(fb[0]) > 0, "bouncing text draws")
    # header layout
    blob = out["starfield"]
    magic, ver, flags, _count, _fps, w, h = struct.unpack_from("<IBBHBBB", blob, 0)
    expect((magic, ver, flags & 1, w, h) == (0x4E41504D, 1, 1, 128, 64), "header fields")
    expect(blob[:4] == b"MPAN", "magic bytes 'MPAN'")
    expect(F.crc32(blob[:28]) == struct.unpack_from("<I", blob, 28)[0], "header crc")
    # corruption
    bad = bytearray(blob)
    bad[40] ^= 0x10
    expect(raises(lambda: A.parse_blob(bytes(bad))), "data corruption detected")
    bad = bytearray(blob)
    bad[8] = 31
    expect(raises(lambda: A.parse_blob(bytes(bad))), "header corruption detected")
    expect(raises(lambda: A.parse_blob(blob[:-1])), "truncation detected")
    frames = [bytes([i]) * 1024 for i in range(3)]
    good = A.build_blob(frames, 5)
    # forge frame 0 as DELTA with valid CRCs
    data = bytearray(good[32:])
    data[0] = A.ENC_DELTA
    hdr = bytearray(good[:32])
    struct.pack_into("<I", hdr, 16, F.crc32(bytes(data)))
    struct.pack_into("<I", hdr, 28, F.crc32(bytes(hdr[:28])))
    expect(raises(lambda: A.parse_blob(bytes(hdr) + bytes(data))), "frame 0 DELTA rejected")
    expect(raises(lambda: A.build_blob([], 10)), "empty rejected")
    expect(raises(lambda: A.build_blob(frames, 31)), "fps 31 rejected")
    # worst case sizes
    rng = random.Random(5)
    noise = [bytes(rng.randrange(256) for _ in range(1024)) for _ in range(A.MAX_FRAMES_RAW)]
    nb = A.build_blob(noise, 10)
    expect(len(nb) <= A.REGION_SIZE, f"{A.MAX_FRAMES_RAW} noise frames fit ({len(nb)} B)")
    expect(A.blob_stats(nb)["encodings"]["RAW"] == A.MAX_FRAMES_RAW, "noise stored RAW")
    nb2 = A.build_blob(noise + noise[:1], 10)
    expect(len(nb2) > A.REGION_SIZE, "128 noise frames exceed the region")
    out["noise"] = nb
    out["edge"] = A.build_blob([bytes(1024), bytes([0xFF]) * 1024, bytes(range(256)) * 4], 30, False, "edge")
    # pixel helpers
    f = A.blank_frame()
    A.set_pixel(f, 0, 0)
    A.set_pixel(f, 127, 63)
    A.set_pixel(f, 5, 9)
    expect(f[0] == 1 and f[127 + 7 * 128] == 0x80 and f[5 + 128] == 0x02, "page order bits")
    expect(A.frame_from_bits(A.frame_to_bits(bytes(f))) == bytes(f), "bits roundtrip")
    s = A.shift_frame(bytes(f), 1, 0)
    expect(A.get_pixel(s, 0, 63) and A.get_pixel(s, 1, 0) and A.get_pixel(s, 6, 9), "shift wraps")
    expect(A.invert_frame(A.invert_frame(bytes(f))) == bytes(f), "invert twice")
    return out


def check_firmware_consistency() -> None:
    print("smoke_anim_codec: constants vs firmware sources")
    fmt = (REPO / "firmware/include/anim_format.h").read_text()
    anim_h = (REPO / "firmware/include/anim.h").read_text()
    proto = (REPO / "firmware/include/config_protocol.h").read_text()
    expect(c_int(fmt, "ANIM_MAGIC") == A.MAGIC, "MAGIC")
    for cname, py in (
        ("ANIM_VERSION", A.VERSION),
        ("ANIM_HEADER_SIZE", A.HEADER_SIZE),
        ("ANIM_REC_HDR_SIZE", A.REC_HDR_SIZE),
        ("ANIM_FRAME_BYTES", A.FRAME_BYTES),
        ("ANIM_MAX_FPS", A.MAX_FPS),
        ("ANIM_MAX_FRAMES", A.MAX_FRAMES),
        ("ANIM_ENC_RAW", A.ENC_RAW),
        ("ANIM_ENC_RLE", A.ENC_RLE),
        ("ANIM_ENC_DELTA", A.ENC_DELTA),
        ("ANIM_FLAG_LOOP", A.FLAG_LOOP),
    ):
        expect(c_int(fmt, cname) == py, f"{cname} {c_define(fmt, cname)} != {py}")
    expect("128u * 1024u" in c_define(anim_h, "ANIM_REGION_SIZE"), "ANIM_REGION_SIZE 128 KiB")
    expect("0x1DF000" in anim_h, "ANIM_REGION_OFFSET documented as 0x1DF000")
    expect(0x200000 - 4096 - A.REGION_SIZE == A.REGION_OFFSET == 0x1DF000, "region offset")
    for cname, py in (
        ("ANIM_SETTINGS_SIZE", A.SETTINGS_SIZE),
        ("ANIM_INFO_SIZE", A.INFO_SIZE),
        ("ANIM_DEFAULT_IDLE_S", A.DEFAULT_IDLE_S),
        ("ANIM_DEFAULT_BLANK_S", A.DEFAULT_BLANK_S),
        ("ANIM_PREVIEW_STOP", A.PREVIEW_STOP),
        ("ANIM_PREVIEW_PLAY", A.PREVIEW_PLAY),
        ("ANIM_PREVIEW_BUILTIN", A.PREVIEW_BUILTIN),
        ("ANIM_PREVIEW_BLANK", A.PREVIEW_BLANK),
    ):
        expect(c_int(anim_h, cname) == py, f"{cname} mismatch")
    for name in (
        "ANIM_BEGIN",
        "ANIM_DATA",
        "ANIM_COMMIT",
        "ANIM_ABORT",
        "ANIM_INFO",
        "ANIM_READ",
        "ANIM_SETTINGS_GET",
        "ANIM_SETTINGS_SET",
        "ANIM_PREVIEW",
    ):
        expect(c_int(proto, f"CFG_CMD_{name}") == getattr(F, f"CFG_CMD_{name}"), f"CFG_CMD_{name}")
    expect(c_int(proto, "CFG_INFO_FLAG_ANIM") == F.CFG_INFO_FLAG_ANIM, "CFG_INFO_FLAG_ANIM")
    expect(c_int(proto, "CFG_ANIM_CHUNK_MAX") == F.CFG_ANIM_CHUNK_MAX, "CFG_ANIM_CHUNK_MAX")
    font_c = (REPO / "firmware/src/oled_font.c").read_text()
    rows = re.findall(r"\{\s*((?:0x[0-9A-Fa-f]{2}\s*,\s*){4}0x[0-9A-Fa-f]{2})\s*\}", font_c)
    fw_font = tuple(tuple(int(v, 16) for v in r.split(",")) for r in rows)
    expect(fw_font == font5x7.FONT5X7, "font5x7.py differs from firmware oled_font.c")


HARNESS = r"""
#include "anim_format.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static uint32_t crc32(const uint8_t *d, size_t n) {
    uint32_t c = 0xFFFFFFFFu;
    for (size_t i = 0; i < n; i++) { c ^= d[i]; for (int b = 0; b < 8; b++) c = (c >> 1) ^ (0xEDB88320u & -(c & 1u)); }
    return ~c;
}
int main(int argc, char **argv) {
    if (argc < 3) return 4;
    FILE *f = fopen(argv[1], "rb"); if (!f) return 3;
    static uint8_t buf[200000]; size_t n = fread(buf, 1, sizeof buf, f); fclose(f);
    anim_header_t h; uint32_t total = 0;
    if (!anim_validate(buf, n, crc32, &h, &total)) { printf("INVALID\n"); return 1; }
    FILE *o = fopen(argv[2], "wb");
    static uint8_t frame[ANIM_FRAME_BYTES]; memset(frame, 0, sizeof frame);
    size_t off = ANIM_HEADER_SIZE;
    for (unsigned i = 0; i < h.frame_count; i++) {
        size_t used = anim_decode_record(&buf[off], total - off, frame);
        if (!used) { printf("DECODE %u\n", i); return 2; }
        fwrite(frame, 1, sizeof frame, o); off += used;
    }
    fclose(o);
    printf("OK %u %u %u %s\n", h.frame_count, h.fps, (unsigned)total, h.name);
    return 0;
}
"""


def check_c_codec(blobs: dict) -> None:
    print("smoke_anim_codec: firmware anim_codec.c on host")
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not cc:
        print("    SKIP: no host C compiler")
        return
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "h.c").write_text(HARNESS)
        exe = t / "anim_host"
        r = subprocess.run(
            [
                cc,
                "-std=c11",
                "-O1",
                "-Wall",
                "-Wextra",
                "-Werror",
                f"-I{REPO / 'firmware/include'}",
                str(t / "h.c"),
                str(REPO / "firmware/src/anim_codec.c"),
                "-o",
                str(exe),
            ],
            capture_output=True,
            text=True,
        )
        expect(r.returncode == 0, f"host compile failed: {r.stderr}")
        if r.returncode:
            return
        for key, blob in blobs.items():
            (t / "b.bin").write_bytes(blob)
            r = subprocess.run([str(exe), str(t / "b.bin"), str(t / "o.bin")], capture_output=True, text=True)
            expect(r.returncode == 0 and r.stdout.startswith("OK"), f"C rejects {key}: {r.stdout}")
            if r.returncode == 0:
                frames = A.parse_blob(blob).frames
                expect((t / "o.bin").read_bytes() == b"".join(frames), f"C decode differs for {key}")
        bad = bytearray(blobs["starfield"])
        bad[100] ^= 1
        (t / "b.bin").write_bytes(bytes(bad))
        r = subprocess.run([str(exe), str(t / "b.bin"), str(t / "o.bin")], capture_output=True, text=True)
        expect(r.returncode == 1, "C accepts corrupted blob")
        print(f"    C codec agrees on {len(blobs)} blobs (+ rejects corruption)")


def check_gif_and_import() -> None:
    print("smoke_anim_codec: GIF writer + image import")
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter

    from macropad_config.animation import imaging as IM

    _app = QGuiApplication.instance() or QGuiApplication([])
    frames, _fps = P.bouncing_text("GIF", frames=8)
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        write_oled_gif(t / "a.gif", frames, 10, scale=1)
        imgs, gfps = IM.read_image_frames(t / "a.gif")
        expect(len(imgs) == 8 and gfps == 10, f"gif frames {len(imgs)} fps {gfps}")
        back, _ = IM.import_files([t / "a.gif"], IM.ImportOptions(dither=IM.DITHER_THRESHOLD))
        expect(back == frames, "GIF → import is lossless at 128x64 with threshold")
        write_oled_gif(t / "b.gif", frames, 10, scale=3)
        back3, _ = IM.import_files([t / "b.gif"], IM.ImportOptions(dither=IM.DITHER_THRESHOLD))
        expect(back3 == frames, "3x GIF downsampled back to identical frames")
        # square white box 64x64 → centred 64x64 at x 32..95
        img = QImage(64, 64, QImage.Format_RGB32)
        img.fill(QColor(255, 255, 255))
        img.save(str(t / "sq.png"))
        fr, _ = IM.import_files([t / "sq.png"], IM.ImportOptions(dither=IM.DITHER_THRESHOLD))
        bits = A.frame_to_bits(fr[0])
        expect(
            bits[32 * 128 + 32]
            and bits[32 * 128 + 95]
            and not bits[32 * 128 + 31]
            and not bits[32 * 128 + 96],
            "fit keeps aspect + centres",
        )
        inv, _ = IM.import_files([t / "sq.png"], IM.ImportOptions(dither=IM.DITHER_THRESHOLD, invert=True))
        expect(A.get_pixel(inv[0], 0, 0) and not A.get_pixel(inv[0], 64, 32), "invert")
        # 50 % grey → FS gives ~50 % lit, threshold 128 → all lit
        g = QImage(128, 64, QImage.Format_RGB32)
        g.fill(QColor(128, 128, 128))
        g.save(str(t / "grey.png"))
        fs, _ = IM.import_files([t / "grey.png"], IM.ImportOptions(dither=IM.DITHER_FLOYD))
        lit = A.frame_pixel_count(fs[0])
        expect(3500 < lit < 4700, f"Floyd–Steinberg 50% grey lit {lit}")
        th, _ = IM.import_files([t / "grey.png"], IM.ImportOptions(dither=IM.DITHER_THRESHOLD, threshold=200))
        expect(A.frame_pixel_count(th[0]) == 0, "threshold 200 on grey 128 → dark")
        # PNG sequence, natural sort (f2 before f10)
        for i in (10, 2, 1):
            im = QImage(128, 64, QImage.Format_RGB32)
            im.fill(QColor(0, 0, 0))
            p = QPainter(im)
            p.fillRect(i, 0, 1, 64, QColor(255, 255, 255))
            p.end()
            im.save(str(t / f"f{i}.png"))
        seq, _ = IM.import_files(
            [t / "f10.png", t / "f2.png", t / "f1.png"], IM.ImportOptions(dither=IM.DITHER_THRESHOLD)
        )
        expect(
            [next(x for x in range(128) if A.get_pixel(s, x, 5)) for s in seq] == [1, 2, 10],
            "PNG sequence natural order",
        )


def check_project() -> None:
    print("smoke_anim_codec: project files")
    frames, fps = P.pulse(frames=6)
    proj = AnimationProject(
        frames=frames,
        fps=fps,
        loop=False,
        name="pulse test",
        idle_enabled=False,
        idle_timeout_s=90,
        blank_timeout_s=0,
    )
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "x.mpanim.json"
        proj.save(path)
        back = AnimationProject.load(path)
        expect(
            back.frames == frames
            and back.fps == fps
            and not back.loop
            and back.name == "pulse test"
            and not back.idle_enabled
            and back.idle_timeout_s == 90
            and back.blank_timeout_s == 0,
            "project roundtrip",
        )
        blob = back.to_blob()
        expect(A.parse_blob(blob).name == "pulse te", "blob name truncated to 8")
        d = back.to_dict()
        d["schema_version"] = 99
        expect(raises(lambda: AnimationProject.from_dict(d), ProjectError), "schema 99 rejected")
        d = back.to_dict()
        d["frames"][0] = "AAAA"
        expect(raises(lambda: AnimationProject.from_dict(d), ProjectError), "bad frame size rejected")
    os.environ["MACROPAD_ANIMATIONS_DIR"] = "/tmp/x-anim-test-dir"
    from macropad_config.animation.project import animations_dir

    expect(str(animations_dir(create=False)) == "/tmp/x-anim-test-dir", "MACROPAD_ANIMATIONS_DIR")
    os.environ.pop("MACROPAD_ANIMATIONS_DIR")
    expect(animations_dir(create=False).name == "animations", "default dir under user data")


def main() -> int:
    check_packbits()
    blobs = check_blobs()
    check_firmware_consistency()
    check_c_codec(blobs)
    check_gif_and_import()
    check_project()
    if FAILS:
        print(f"smoke_anim_codec: {len(FAILS)} FAILURE(S)")
        return 1
    print("smoke_anim_codec: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
