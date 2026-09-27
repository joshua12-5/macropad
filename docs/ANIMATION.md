# OLED idle animations (Step 24b)

The macropad can play a custom 128×64 animation on its SSD1306 when nobody is using it, and
switch the display off later for burn-in protection. Animations are authored in the
configurator (**Tools → Idle animation…**) and stored in a dedicated flash region on the device.

## Behaviour on the device

| Setting | Default | Meaning |
|---------|---------|---------|
| enabled | on | play the animation when idle (blanking still applies when off) |
| idle timeout | 60 s | seconds without key / encoder input before the animation starts (0 = never) |
| blank timeout | 600 s | seconds without input before the display is switched off (0 = never) |

* The stored animation plays at its own fps (1–30) and loops (or holds the last frame when the
  loop flag is off). With no animation uploaded the firmware plays a **built-in procedural
  starfield** (48 stars, 20 fps).
* **Any** key press, encoder turn or encoder press wakes the normal UI. The waking input is
  swallowed: no HID report, no action, no long-press — the key reports again only after it is
  released and pressed again.
* Settings persist in the MPFL storage sector (v3) and survive power cycles.
* Frame pushes never block the main loop: the framebuffer is streamed over I2C in 16-byte
  chunks, at most two per 1 ms tick (see *I2C timing* below).

## Authoring (configurator)

**Tools → Idle animation…** works offline; device actions need firmware 0.25+.

* **Frames** strip with thumbnails — add, duplicate (Ctrl+D), delete, move earlier/later or drag
  to reorder.
* **Canvas** — 128×64 pixels at 2–12× zoom with an 8-px page grid. Pen / eraser (P / E), right
  mouse button does the opposite, brush 1–8 px, invert (I), clear, shift ◀▶▲▼ (wraps), onion
  skin of the previous frame, undo / redo (Ctrl+Z / Ctrl+Y), `[` / `]` previous / next frame.
* **Preview** — plays the frames at the chosen fps (Space).
* **Presets** — generated in Python: *Starfield (warp)*, *Bouncing text* (default `MACROPAD`),
  *Scrolling text* (your text, seamless marquee), *Pulse / breathing* (ordered-dither glow).
* **Import GIF / images…** — an animated GIF, a PNG/JPEG/BMP/WebP sequence (multi-select,
  natural sort: `f2` before `f10`) or one image. Each image is fitted into 128×64 keeping its
  aspect ratio and centred on black (or stretched), converted to grey and turned into 1-bit
  pixels by **Floyd–Steinberg dithering** or a **threshold** slider, optionally **inverted**.
  A live before/after preview shows the result; frames replace, append or insert after the
  current frame, and the GIF's frame delay can set the fps.
* **Files** — projects are saved as `*.mpanim.json` in `<user data>/animations`
  (`~/.local/share/macropad-configurator/animations`, `%APPDATA%\MacropadConfigurator\animations`,
  `~/Library/Application Support/MacropadConfigurator/animations`; override with
  `MACROPAD_ANIMATIONS_DIR`). **Export GIF…** writes a 3× preview GIF, **Export .mpan…** the exact
  device blob.
* **Device** — *Upload to device* (progress bar, cancel; verifies by reading the blob back and
  optionally pushes the idle settings), *Preview on device* / *Stop preview*, *Built-in demo*,
  *Push idle settings*, *Read from device*. On firmware older than 0.25 (GET_INFO flag bit3
  clear) these actions explain that a firmware update is needed instead of failing.

The stats line shows the encoded size against the 128 KiB region and the RAW / RLE / DELTA mix.

## Device blob (`.mpan`)

Little-endian; identical in `firmware/include/anim_format.h` and
`configurator/macropad_config/animation/codec.py`.

| Off | Type | Field |
|-----|------|-------|
| 0 | u32 | magic `MPAN` (0x4E41504D) |
| 4 | u8 | version = 1 |
| 5 | u8 | flags: bit0 loop |
| 6 | u16 | frame_count (1 … 1024) |
| 8 | u8 | fps (1 … 30) |
| 9 | u8 | width = 128 |
| 10 | u8 | height = 64 |
| 11 | u8 | reserved = 0 |
| 12 | u32 | data_len — bytes of frame records after the header |
| 16 | u32 | data_crc — CRC-32 (IEEE, same as the frame CRC) of the records |
| 20 | 8 | name, ASCII, NUL padded |
| 28 | u32 | header_crc — CRC-32 of bytes 0 … 27 |

Then `frame_count` records back to back: `enc u8`, `reserved u8`, `len u16`, `payload[len]`.

| enc | name | payload |
|-----|------|---------|
| 0 | RAW | the 1024-byte frame |
| 1 | RLE | PackBits of the frame |
| 2 | DELTA | PackBits of `frame XOR previous frame` (never frame 0, so a loop restart starts from a key frame) |

Frames are in SSD1306 page order: byte `x + (y / 8) * 128`, bit `y % 8` (bit0 = top row of the
page) — the firmware copies a decoded frame straight into its framebuffer. PackBits control
byte `c`: `c < 128` → copy the next `c + 1` bytes; `c > 128` → repeat the next byte `257 − c`
times; `128` is invalid. The host encoder picks the smallest encoding per frame.

### Capacity (max frames)

The region is 128 KiB; a frame costs 4 bytes of record header plus its payload.

| Content | Bytes / frame | Frames in 128 KiB |
|---------|---------------|-------------------|
| worst case (noise, all RAW) | 1028 | **127** (`ANIM_MAX_FRAMES_RAW`) |
| dithered photo / video | ~700 – 1000 | ~130 – 185 |
| bouncing 2× text (preset) | ~228 | ~570 |
| pulse glow (preset) | ~206 | ~635 |
| scrolling text (preset) | ~147 | ~890 |
| starfield (preset) | ~123 | 1024 (format cap `ANIM_MAX_FRAMES`) |

At 20 fps, 127 frames is 6.4 s of arbitrary content; typical line-art loops fit 30–50 s.

## Project file (`*.mpanim.json`)

```json
{
  "format": "macropad-animation",
  "schema_version": 1,
  "name": "stars",
  "fps": 20,
  "loop": true,
  "width": 128,
  "height": 64,
  "frame_encoding": "ssd1306-pages-base64",
  "frames": ["<base64 of 1024 bytes>", "..."],
  "idle": {"enabled": true, "idle_timeout_s": 60, "blank_timeout_s": 600},
  "generator": "macropad-configurator 0.25.0"
}
```

`frames` use the device page order, so projects convert losslessly to and from `.mpan`.
Only the first 8 ASCII characters of `name` go into the blob header.

## I2C timing

The SSD1306 runs at 400 kHz: 9 clocks per byte → 22.5 µs/byte. One frame push is a 7-byte
window command (`21 00 7F 22 00 07`) plus 64 data transactions of 18 bytes (address + `0x40` +
16 pixels bytes):

* bus time ≈ 8 × 22.5 µs + 64 × 18 × 22.5 µs ≈ **26.1 ms per 1 KiB frame**;
* the old blocking `oled_driver_update()` stalled the main loop for those ~26 ms on every UI
  repaint; since Step 24b `oled_driver_task()` sends at most **2 chunks (≈ 0.81 ms)** per 1 ms
  main-loop tick, so matrix scan, encoder, USB and the config channel keep running every tick
  while a frame streams over ~33 ticks (≈ 33 ms wall, ≈ 30 fps ceiling — the format caps fps at 30);
* the real numbers of the last frame (bus µs and wall µs) are reported by `ANIM_INFO` and shown
  in the editor's device status line.

## Flash map

See [`ARCHITECTURE.md`](ARCHITECTURE.md#flash-map-step-24b).
