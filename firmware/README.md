# Macropad firmware (RP2040)

Pico SDK / TinyUSB firmware for the Waveshare RP2040-Zero macropad. Local build output:
`build/macropad.uf2`; releases ship it as `macropad-fw-X.Y.Z.uf2` on the
[Releases page](https://github.com/joshua12-5/macropad/releases). Release history:
[`../CHANGELOG.md`](../CHANGELOG.md).

Current: `FW_VERSION` **0.26**, protocol v1, USB `bcdDevice` **0x011A** (see
[`../docs/VERSIONING.md`](../docs/VERSIONING.md)).

## Modules

| File | Role |
|------|------|
| `src/main.c` | init + 1 ms main loop (matrix, encoder, USB, config channel, OLED, idle animation) |
| `src/matrix.c` / `src/encoder.c` | 3×4 key matrix scan + debounce; EC11 quadrature + push button |
| `src/usb_descriptors.c` / `src/usb_hid_app.c` | IF0 keyboard + consumer, IF1 vendor config HID; wake-key suppression |
| `src/config_protocol.c` | 64-byte framed config protocol ([`../docs/PROTOCOL.md`](../docs/PROTOCOL.md)) |
| `src/profiles.c` / `src/actions.c` / `src/text_table.c` | 5 profile slots, non-blocking action engine |
| `src/macros.c` / `src/macro_blob.c` / `src/profile_blob.c` | macro engine + bank; wire blob pack/unpack |
| `src/storage.c` | MPFL flash image (profiles, macros, active slot, idle settings) + debounced persist (`storage_schedule_persist`: ~4 s quiet, skipped when flash already matches) |
| `src/oled_driver.c` | SSD1306 over I2C0, non-blocking chunked flush |
| `src/oled_gfx.c` / `src/oled_font.c` | SDK-free 128×64 framebuffer + drawing (text, rects, inverse), 5×7 font |
| `src/oled_ui.c` | UI pages: home, key / volume pop-ups, toasts, menu |
| `src/menu.c` | generic table-driven menu engine (wrapping list, breadcrumb, scroll bar, `n/N`) |
| `src/device_menu.c` | the on-device menu tree, 9 s timeout, `device_select_profile()` |
| `src/anim.c` / `src/anim_codec.c` | idle state machine, animation flash region, built-in starfield, blob decoder |

## Idle animation

After `idle_timeout_s` (default 60 s, 0 = off) without key / encoder input the OLED plays the
stored animation (or the built-in starfield); after `blank_timeout_s` (default 600 s, 0 = never)
the panel is switched off. The input that wakes the display is swallowed (not sent to the PC).
Format and authoring: [`../docs/ANIMATION.md`](../docs/ANIMATION.md).

## On-device menu

Hold the encoder ~0.8 s to open it; turn = move (wraps), short press (on release) = open /
confirm, hold = back one level (exit at the top), 9 s idle = exit. Tree and behaviour:
[`../docs/USER_GUIDE.md#the-on-device-menu`](../docs/USER_GUIDE.md#the-on-device-menu). The
encoder's `long_press` action slot is reserved and never fires.

The menu and drawing code has no Pico SDK dependency, so it also builds on the PC:
`configurator/scripts/smoke_oled_menu.py` compiles `menu.c`, `device_menu.c`, `oled_ui.c`,
`oled_gfx.c` and `oled_font.c` with the stubs in [`tests/host/`](tests/host/), runs
`oled_menu_test.c` (navigation, wrap, back / exit, timeout, toasts, persist scheduling) and
writes 4× PNGs of the frames (`--out DIR`).

**I2C timing (400 kHz):** one 1 KiB frame is ≈ 26.1 ms of bus time. `oled_driver_task()` sends
at most two 16-byte chunks (≈ 0.81 ms) per 1 ms loop tick, so a frame lands in ≈ 33 ms
(≈ 30 fps ceiling) without stalling the matrix scan or USB.

## Flash map (2 MiB)

| Offset | Size | Content |
|--------|------|---------|
| `0x000000` – image end | ≈ 64 KiB | firmware (`__flash_binary_end` = `0x1000FF58`, gcc 14.2) |
| image end – `0x1DEFFF` | ≈ 1.8 MiB | free |
| `0x1DF000` – `0x1FEFFF` | 128 KiB | idle-animation region (`MPAN` blob; max 127 uncompressed frames) |
| `0x1FF000` – `0x1FFFFF` | 4 KiB | `MPFL` storage image v3 |

`anim.c` static-asserts the region layout and disables stored animations at boot if the image
ever reaches the region; `firmware.yml` fails the build in that case. Details:
[`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md#flash-map).

## Build

Verified toolchain: **Pico SDK tag `2.1.1`** with submodules (TinyUSB),
**`PICO_BOARD=waveshare_rp2040_zero`**, `arm-none-eabi-gcc` 13.2 (CI) / 14.2 (local),
CMake ≥ 3.13, Ninja. Our sources build with `-Wall -Wextra` and zero warnings.

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
# → build/macropad.uf2 (hold BOOT, plug in, copy to RPI-RP2)
```

Notes:

- `PICO_BOARD` defaults to `waveshare_rp2040_zero` in `CMakeLists.txt` (2 MiB flash,
  W25Q080 boot2 at clkdiv 4). `PICO_BOARD=pico` also builds (same GPIO numbers; pinout in
  `include/board_pins.h` is frozen and board-independent).
- SDK 2.x fetches and builds `picotool` from source on first configure if none is installed
  (needs network + a host C++ compiler). Install picotool 2.1.1 to skip that.
- CMake warns if `PICO_SDK_VERSION_STRING` is not the verified `2.1.1`.
- An existing `build/` from an older checkout still contains the previous target name; delete
  it (or run `cmake -B build` again) if you see stale `macropad_step*.uf2` files.
- Formatting: [`../.clang-format`](../.clang-format) describes the house style
  (`clang-format -i src/*.c include/*.h`).

## UART debug (GP0 TX, 115200 8N1)

Boot banner `=== Macropad firmware 0.26 ===`, then e.g.
`stor load v3|v2|v1 (macros factory)|default`, `stor save ok|fail`,
`stor debounce save`, `stor debounce skip (unchanged)`, `cfg macro …`, `cfg set_active N`,
`cfg save_all ok`, `macro save ok`, `profile save ok`, `menu: open|close|timeout`,
`profile -> [N] NAME`,
`anim idle: on|off, idle N s, blank N s`, `anim stored: N frames @ F fps, … B` /
`anim: no stored animation (builtin)`, `anim play builtin|stored`, `anim blank`, `anim wake`,
`anim upload begin len=N`, `anim commit ok (N sectors)` / `anim commit rejected err=N`,
`anim upload abort`, `anim flash rc=N sector=N`.
