# RP2040 Programmable Macropad

[![Host smokes](https://github.com/joshua12-5/macropad/actions/workflows/smokes.yml/badge.svg)](https://github.com/joshua12-5/macropad/actions/workflows/smokes.yml)
[![Firmware build](https://github.com/joshua12-5/macropad/actions/workflows/firmware.yml/badge.svg)](https://github.com/joshua12-5/macropad/actions/workflows/firmware.yml)

Commercial-style 12-key macropad on **Waveshare RP2040-Zero**: matrix + EC11 encoder + SSD1306 OLED, Pico SDK / TinyUSB firmware, and a Python/PySide6 desktop configurator.

## Features

- 12 keys + encoder, 5 on-device profiles (keys, shortcuts, media, macros), on-device profile menu
- Macro library with flash-backed bank; host-driven app auto-switch
- **OLED idle animations** (fw 0.25+): after a configurable idle time the OLED plays your own
  animation (or a built-in starfield), any key/encoder input wakes it without being sent to the
  PC, and a second timeout blanks the panel for burn-in protection. Draw frames pixel by pixel,
  import GIF / PNG sequences with dithering, or start from presets in the configurator's
  **Tools → Idle animation…** editor — see [`docs/ANIMATION.md`](docs/ANIMATION.md)
- Desktop configurator (Windows / macOS / Linux), headless smokes + hardware-in-the-loop test suite

## Layout

```
OLED                         ENCODER
1   2   3   4
5   6   7   8
9  10  11  12
```

## Status

Firmware **0.25** / configurator **0.25.0** (protocol v1). Feature-complete for the
current hardware revision; the PCB and enclosure are not in this repo yet. Release history:
[`CHANGELOG.md`](CHANGELOG.md).

## Download

Prebuilt binaries are on the **[Releases page](https://github.com/joshua12-5/macropad/releases)**
(latest: [v0.25.0](https://github.com/joshua12-5/macropad/releases/tag/v0.25.0), prerelease):

| You have | Download | Then |
|----------|----------|------|
| The macropad (RP2040-Zero) | `macropad-fw-X.Y.Z.uf2` | Hold BOOT, plug in, copy the UF2 to the `RPI-RP2` drive |
| Windows 10/11 x64 | `MacropadConfigurator-X.Y.Z-windows-x64.zip` | Extract, run `MacropadConfigurator\MacropadConfigurator.exe` (SmartScreen: *More info → Run anyway*) |
| macOS 12+ Apple Silicon | `MacropadConfigurator-X.Y.Z-macos-arm64.zip` | Unzip, move the `.app` to Applications, first launch via right-click → *Open* (unsigned) |
| Linux x86_64 (glibc ≥ 2.35) | `macropad-configurator-X.Y.Z-linux-x86_64.tar.gz` | Extract, `./install.sh` (udev rule), run `MacropadConfigurator/MacropadConfigurator` |

Verify downloads with `SHA256SUMS.txt`. The apps are **unsigned** — see
[`docs/RELEASE.md`](docs/RELEASE.md#unsigned-builds--what-users-will-see) for the Windows
SmartScreen / macOS Gatekeeper workarounds. `MacropadConfigurator --self-test` checks an install
headlessly; `--version` prints the version. Host and firmware minor versions should match
(Help → About / Device → Get info).

## Architecture

Stack layers, data flows, flash vs RAM: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
Version matrix / compat: [`docs/VERSIONING.md`](docs/VERSIONING.md).
Changelog: [`CHANGELOG.md`](CHANGELOG.md). Cut a release: [`docs/RELEASE.md`](docs/RELEASE.md).
Manual hardware checklist: [`docs/HARDWARE_TEST.md`](docs/HARDWARE_TEST.md).
CI runs host configurator smokes (`smokes.yml`) and the firmware build + size / flash-map check (`firmware.yml`).

## Protocol

Wire format and commands: [`docs/PROTOCOL.md`](docs/PROTOCOL.md).
Profile binary packing: [`docs/PROFILE_BLOB.md`](docs/PROFILE_BLOB.md).
Macro binary packing: [`docs/MACRO_BLOB.md`](docs/MACRO_BLOB.md).

## Profiles

Host-side JSON (schema v1): [`profiles/`](profiles/) + [`profiles/SCHEMA.md`](profiles/SCHEMA.md).

## Macros

Host library (configurator source of truth): [`macros/library.json`](macros/library.json) + [`macros/SCHEMA.md`](macros/SCHEMA.md).

Device → Upload macros writes the library into the firmware RAM working set + flash bank.
Factory defaults in `macros.c` seed empty flash / v1 images.

## Auto-switch

Rules: [`autoswitch/rules.json`](autoswitch/rules.json) + [`autoswitch/SCHEMA.md`](autoswitch/SCHEMA.md).
Override path with `MACROPAD_AUTOSWITCH_PATH`. Matching is case-insensitive
substring on process basename; optional `title_regex`; first rule wins.

## Configurator

Desktop app: [`configurator/`](configurator/).

```bash
cd configurator
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m macropad_config
```

Loads `profiles/*.json` (override with `MACROPAD_PROFILES_DIR`) and `macros/library.json` (`MACROPAD_MACROS_PATH`). Edit key/encoder actions and profile name/OLED title; **File → Save** (`Ctrl+S`) writes JSON. **Profile → New / Duplicate / Delete** manage profiles. **Profile → Macro library…** edits the host macro library. **Device → Connect / Get device info** runs PING + GET_INFO (shows `active_slot`).
**Device → Upload profile / macros** sync flash banks;
**Device → Save device state** sends `SAVE_ALL` (`0x32`).
**Tools → Idle animation…** draws / imports OLED idle animations and uploads them (fw 0.25+).
**Tools → Auto-switch…** edits rules; **Device → Auto-switch enabled** polls the
foreground app (needs a prior Connect). Status bar: `Auto-switch: coding (Code)`.

Headless checks (or all at once). The same suite runs in CI on push/PR to
`main` (`.github/workflows/smokes.yml`); firmware is built separately by
`.github/workflows/firmware.yml`:

```bash
python scripts/run_all_smokes.py
# individual:
python scripts/smoke_version.py
python scripts/smoke_load.py
python scripts/smoke_edit.py
python scripts/smoke_profile_mgr.py
python scripts/smoke_macros.py
python scripts/smoke_editor_forms.py # form rows per action / step type, macro dialog dirty tracking
python scripts/smoke_protocol.py
python scripts/smoke_storage.py
python scripts/smoke_macros_blob.py
python scripts/smoke_autoswitch.py
python scripts/smoke_hil_mock.py      # HIL suite vs mock device
python scripts/smoke_packaging.py     # release tooling + --version
python scripts/smoke_anim_codec.py    # animation codec (host + compiled firmware C decoder), presets, GIF
python scripts/smoke_anim_device.py   # animation protocol vs mock + editor GUI
python -m macropad_config --self-test # full headless self-test (Qt offscreen)
```

## Firmware

See [`firmware/README.md`](firmware/README.md).

Verified with [Pico SDK](https://github.com/raspberrypi/pico-sdk) tag **2.1.1** and
`PICO_BOARD=waveshare_rp2040_zero` (`PICO_BOARD=pico` also builds). Local build output:
`firmware/build/macropad.uf2` — or download `macropad-fw-X.Y.Z.uf2` from the
[Releases page](https://github.com/joshua12-5/macropad/releases) (or the `macropad-firmware-uf2`
artifact of the latest `Firmware build` Actions run).

```bash
# Toolchain (Debian/Ubuntu):
sudo apt-get install gcc-arm-none-eabi libnewlib-arm-none-eabi \
    libstdc++-arm-none-eabi-newlib cmake ninja-build build-essential python3

# Pico SDK — pinned tag 2.1.1 (TinyUSB submodule required):
git clone --depth 1 --branch 2.1.1 https://github.com/raspberrypi/pico-sdk.git
git -C pico-sdk submodule update --init --depth 1
export PICO_SDK_PATH=$PWD/pico-sdk

cd firmware
cmake -B build -G Ninja -DPICO_BOARD=waveshare_rp2040_zero
ninja -C build
# → build/macropad.uf2 (hold BOOT, plug in, copy to RPI-RP2)
```

**On-device profile select:** long-press encoder (~800 ms) → OLED menu; rotate to highlight; short-press to confirm; long-press or ~9 s idle to cancel.

**USB:** IF0 keyboard+consumer; IF1 vendor config HID (usage page `0xFF00`), 64-byte framed protocol with profile upload.

**Flash:** last 4 KiB sector holds magic/`MPFL` image with 5 packed profile blobs + CRC
(v3 adds the idle-animation settings); the 128 KiB just below it (`0x1DF000`–`0x1FEFFF`) holds
the uploaded idle animation. Full map: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md#flash-map).

## Pinout (locked)

| Function | GPIO |
|----------|------|
| Rows 1–3 | GP8, GP9, GP10 |
| Cols 1–4 | GP11–GP14 |
| Encoder A/B/SW | GP2, GP3, GP15 |
| OLED SDA/SCL | GP4, GP5 (I2C0) |
| NeoPixel (onboard) | GP16 |
| Debug UART | GP0 TX, GP1 RX |

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) (dev setup, checks to run, commit style).

## License

[MIT](LICENSE) — Copyright (c) 2026 Joshua Zamora.
