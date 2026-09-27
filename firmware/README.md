# Macropad firmware (RP2040)

Build target: `macropad_step24b.uf2` (released as `macropad-fw-X.Y.Z.uf2` on the
[Releases page](https://github.com/joshua12-5/macropad/releases))

## Step 24b — OLED idle animations

- `FW_VERSION_MINOR` = **25**; CMake target `macropad_step24b`; USB `bcdDevice` = **0x0119** (1.25).
- `anim.c`: idle state machine ACTIVE → PLAYING (after `idle_timeout_s`, default 60 s, 0 = off)
  → BLANK (after `blank_timeout_s`, default 600 s, 0 = never; display off). Any key / encoder
  input wakes to the normal UI; the waking key is suppressed in the HID report until released
  (`usb_hid_suppress_key`), a waking encoder turn / press is dropped (press also cancels the
  long-press menu). Built-in procedural starfield (48 stars, 20 fps) when nothing is uploaded.
- `oled_driver.c`: non-blocking flush — `oled_driver_task()` streams the 1 KiB framebuffer in
  16-byte I2C chunks, ≤ 2 per main-loop tick. **I2C timing at 400 kHz:** ≈ 26.1 ms bus time per
  1 KiB frame (64 × 18-byte transactions + window command); the old blocking update stalled the
  loop that long on every repaint, now each tick spends ≤ ≈ 0.81 ms on I2C and a frame lands in
  ≈ 33 ms (≈ 30 fps ceiling; the format caps fps at 30). ANIM_INFO reports the measured bus / wall
  µs of the last frame.
- Animation region: 128 KiB at flash `0x1DF000`–`0x1FEFFF`, directly below the MPFL sector
  (`anim.h`; static-asserted, boot-checked against `__flash_binary_end`, CI fails if the image
  reaches `0x101DF000`). `MPAN` v1 blob (`anim_format.h`, decoder `anim_codec.c`): 32-byte header
  (magic, version, frame count, fps, loop, CRC32) + per-frame RAW / PackBits-RLE / XOR-delta-RLE
  records in SSD1306 page order. Max **127 frames** worst case (all RAW), 255 by header field;
  typical presets need 120–230 B/frame. Uploads erase + program only the covered sectors via
  `flash_safe_execute()`.
- Protocol `0x40`–`0x48`: ANIM_BEGIN / DATA / COMMIT / ABORT / INFO / READ, ANIM_SETTINGS_GET /
  SET, ANIM_PREVIEW; GET_INFO flags **bit3** (`CFG_INFO_FLAG_ANIM`); same chunk / CRC / `EBUSY`
  rules as profile / macro uploads (see [`../protocol/PROTOCOL.md`](../protocol/PROTOCOL.md)).
- Storage: MPFL **v3** = v2 + 8-byte idle settings (enabled, idle / blank timeouts); v2 / v1
  images still load (settings default) and are rewritten as v3 on the next save.
- Size (gcc 14.2): text **65428** (+8512 vs Step 24), bss **18692** (+7532: 4 KiB upload sector
  buffer, decode + I2C snapshot + validate frames, stars), UF2 **131072** B (+16896); image ends at
  `0x1000FF98`, ≈ 1.8 MiB below the animation region. Zero warnings.
- Flash map: [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md#flash-map-step-24b); formats and
  authoring: [`../docs/ANIMATION.md`](../docs/ANIMATION.md).

## Step 24 — Release packaging (kept)

- `FW_VERSION_MINOR` = **24**; CMake target `macropad_step24`; USB `bcdDevice` = **0x0118** (1.24).
  No firmware behaviour, protocol or blob changes.
- `.github/workflows/firmware.yml` is now also a reusable workflow (`workflow_call`) and uploads
  the `.elf` next to the `.uf2`; `.github/workflows/release.yml` calls it on tag `vX.Y.Z` and
  publishes `macropad-fw-X.Y.Z.uf2` / `.elf` / `.uf2.sha256` (see [`../docs/RELEASE.md`](../docs/RELEASE.md)).
- Size: text 56916 (+8 B vs Step 23, banner string), bss 11160, UF2 114176 B.

## Step 23 — HIL support: blob readback + quieter debounce (kept)

- Step 23 set `FW_VERSION_MINOR` 23, target `macropad_step23`, `bcdDevice` 0x0117.
- `CFG_CMD_PROFILE_READ` (`0x15`) / `CFG_CMD_MACRO_READ` (`0x25`): chunked readback (≤ 48 B per
  response) of the packed RAM blobs; GET_INFO flags **bit2** (`CFG_INFO_FLAG_READBACK`).
- Debounced `SET_ACTIVE` persist is skipped when flash already holds a v2 image matching RAM with
  the same `active_slot` (UART `stor debounce skip (unchanged)`).
- Size: text 56908 (+400 B vs Step 22), bss 11160 (unchanged), UF2 114176 B (+1024).
- Host HIL suite: `configurator/scripts/hil_test.py` (see [`../docs/HARDWARE_TEST.md`](../docs/HARDWARE_TEST.md)).

## Step 22 — Verified firmware build + CI UF2 artifact

- First real compile: Pico SDK **2.1.1**, `PICO_BOARD=waveshare_rp2040_zero`,
  `arm-none-eabi-gcc` 14.2, CMake + Ninja. Zero warnings with `-Wall -Wextra`.
- `FW_VERSION_MINOR` was **22**; CMake target `macropad_step22`; USB `bcdDevice` **0x0116** (1.22).
- Storage erase/program runs through `flash_safe_execute()` (single-core: IRQs masked, same as
  before); the flash image is staged in the static 4 KiB sector buffer instead of the stack.
- Size (text/data/bss): **56508 / 0 / 11160**; UF2 113152 B (≈ 110.5 KiB); image ends at `0x1000DCC0`
  — storage sector `0x101FF000` is ~1.9 MiB past it (checked in CI).
  (Local gcc 14.2 numbers; CI's Ubuntu gcc 13.2 gives ~55.4 KB text, UF2 ≈ 108.5 KiB.)
- CI: [`.github/workflows/firmware.yml`](../.github/workflows/firmware.yml) → artifact `macropad-firmware-uf2`.

**Next: Step 24** — last polish/testing step of the 18–24 block.

## Step 21 — Changelog / CI smokes / release polish

- `FW_VERSION_MINOR` was **21**; CMake target `macropad_step21`; USB `bcdDevice` **0x0115** (1.21).
- Host smokes CI: [`.github/workflows/smokes.yml`](../.github/workflows/smokes.yml) (no Pico SDK).
- Changelog / release notes: [`../CHANGELOG.md`](../CHANGELOG.md), cut guide [`../docs/RELEASE.md`](../docs/RELEASE.md).
- Version matrix: [`../docs/VERSIONING.md`](../docs/VERSIONING.md).

## Step 20 — Testing / versioning polish

- `FW_VERSION_MINOR` = **20**; CMake target was `macropad_step20` (superseded by Step 21).
- USB `bcdDevice` was **0x0114** (1.20).
- Version matrix / bump rules: [`../docs/VERSIONING.md`](../docs/VERSIONING.md).
- Manual hardware checklist: [`../docs/HARDWARE_TEST.md`](../docs/HARDWARE_TEST.md).
- Host `0.20.0` alignment (now **0.21.0**).

## Step 19 — Architecture hardening / polish

- Debounced flash persist of `active_slot` after `SET_ACTIVE` (~4 s quiet window).
- `CFG_CMD_SAVE_ALL` (`0x32`) — immediate `storage_save_all()`.
- Architecture overview: [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md).

## Step 18 — Auto app-switch (kept)

- Host `SET_ACTIVE` / `GET_ACTIVE`; Step 19 adds debounced flash persist.

## Step 17 — Macro bank flash sync + protocol polish

- Flash image **v2** in the last 4 KiB sector (`MPFL`): profiles + 5×`macro_blob_v1` (162 B each).
- USB `MACRO_BEGIN` / `DATA` / `COMMIT` / `ABORT` / `GET`.

See [`../protocol/MACRO_BLOB.md`](../protocol/MACRO_BLOB.md) and
[`../protocol/PROTOCOL.md`](../protocol/PROTOCOL.md).

## Build

Verified toolchain (Step 22): **Pico SDK tag `2.1.1`** with submodules (TinyUSB),
**`PICO_BOARD=waveshare_rp2040_zero`**, `arm-none-eabi-gcc` 14.2.1 (Debian/Ubuntu
`gcc-arm-none-eabi`), CMake ≥ 3.13, Ninja.

```bash
# Toolchain (Debian/Ubuntu):
sudo apt-get install gcc-arm-none-eabi libnewlib-arm-none-eabi \
    libstdc++-arm-none-eabi-newlib cmake ninja-build build-essential python3

# Pico SDK — pinned tag 2.1.1 (TinyUSB submodule required):
git clone --depth 1 --branch 2.1.1 https://github.com/raspberrypi/pico-sdk.git
git -C pico-sdk submodule update --init --depth 1
export PICO_SDK_PATH=$PWD/pico-sdk

cd firmware   # this directory
cmake -B build -G Ninja -DPICO_BOARD=waveshare_rp2040_zero
ninja -C build
# → build/macropad_step24b.uf2 (hold BOOT, plug in, copy to RPI-RP2)
```

Notes:

- `PICO_BOARD` defaults to `waveshare_rp2040_zero` in `CMakeLists.txt` (2 MiB flash,
  W25Q080 boot2 at clkdiv 4). `PICO_BOARD=pico` also builds (same GPIO numbers; pinout in
  `include/board_pins.h` is frozen and board-independent).
- SDK 2.x fetches and builds `picotool` from source on first configure if none is installed
  (needs network + a host C++ compiler). Install picotool 2.1.1 to skip that.
- CMake warns if `PICO_SDK_VERSION_STRING` is not the verified `2.1.1`.
- Storage lives in the last 4 KiB sector (`0x1FF000`), the animation region in the 128 KiB below
  it (`0x1DF000`); CI fails if `__flash_binary_end` ever reaches the animation region.

## UART debug

`stor load v2|v1 (macros factory)|default`, `stor save ok|fail`,
`stor debounce save`, `cfg macro …`, `cfg set_active N`, `cfg save_all ok`, `stor debounce skip (unchanged)`,
`macro save ok`, `profile save ok`,
`anim idle: on|off, idle N s, blank N s`, `anim stored: N frames @ F fps, … B` /
`anim: no stored animation (builtin)`, `anim play builtin|stored`, `anim blank`, `anim wake`,
`anim upload begin len=N`, `anim commit ok (N sectors)` / `anim commit rejected err=N`,
`anim upload abort`, `anim flash rc=N sector=N`.
