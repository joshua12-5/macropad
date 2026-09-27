# Macropad firmware (RP2040)

Build target: `macropad_step22.uf2`

## Step 22 — Verified firmware build + CI UF2 artifact

- First real compile: Pico SDK **2.1.1**, `PICO_BOARD=waveshare_rp2040_zero`,
  `arm-none-eabi-gcc` 14.2, CMake + Ninja. Zero warnings with `-Wall -Wextra`.
- `FW_VERSION_MINOR` = **22**; CMake target `macropad_step22`; USB `bcdDevice` = **0x0116** (1.22).
- Storage erase/program runs through `flash_safe_execute()` (single-core: IRQs masked, same as
  before); the flash image is staged in the static 4 KiB sector buffer instead of the stack.
- Size (text/data/bss): **56500 / 0 / 11160**; UF2 ≈ 110.5 KiB; image ends at `0x1000DCB8`
  — storage sector `0x101FF000` is ~1.9 MiB past it (checked in CI).
- CI: [`.github/workflows/firmware.yml`](../.github/workflows/firmware.yml) → artifact `macropad-firmware-uf2`.

**Next: Step 23** — more polish/testing in the 18–24 block.

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
# → build/macropad_step22.uf2 (hold BOOT, plug in, copy to RPI-RP2)
```

Notes:

- `PICO_BOARD` defaults to `waveshare_rp2040_zero` in `CMakeLists.txt` (2 MiB flash,
  W25Q080 boot2 at clkdiv 4). `PICO_BOARD=pico` also builds (same GPIO numbers; pinout in
  `include/board_pins.h` is frozen and board-independent).
- SDK 2.x fetches and builds `picotool` from source on first configure if none is installed
  (needs network + a host C++ compiler). Install picotool 2.1.1 to skip that.
- CMake warns if `PICO_SDK_VERSION_STRING` is not the verified `2.1.1`.
- Storage lives in the last 4 KiB sector (`0x1FF000`); CI fails if `__flash_binary_end`
  ever reaches it.

## UART debug

`stor load v2|v1 (macros factory)|default`, `stor save ok|fail`,
`stor debounce save`, `cfg macro …`, `cfg set_active N`, `cfg save_all ok`,
`macro save ok`, `profile save ok`.
