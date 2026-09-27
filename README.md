# RP2040 Macropad

[![Host smokes](https://github.com/joshua12-5/macropad/actions/workflows/smokes.yml/badge.svg)](https://github.com/joshua12-5/macropad/actions/workflows/smokes.yml)
[![Firmware build](https://github.com/joshua12-5/macropad/actions/workflows/firmware.yml/badge.svg)](https://github.com/joshua12-5/macropad/actions/workflows/firmware.yml)
[![Latest release](https://img.shields.io/github/v/release/joshua12-5/macropad?include_prereleases&label=release)](https://github.com/joshua12-5/macropad/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A 12-key programmable macropad with a rotary encoder and an OLED, built on the tiny
**Waveshare RP2040-Zero**, with a desktop app to configure it. No drivers needed: the
macropad is a standard USB keyboard and keeps its configuration in its own flash, so the app is
only needed for setup (and for optional automatic profile switching).

![Macropad Configurator main window](docs/images/main-window.png)

## Features

- **12 keys + push-button encoder**, each with its own action: single keys, shortcuts
  (Ctrl / Shift / Alt / GUI), macros, typed text, media keys, volume and profile switching.
- **5 on-device profiles**, switched from the knob, from a key, or automatically by the app
  you are using. The choice is saved to flash by itself.
- **On-device OLED menu:** hold the knob for profiles, idle-animation settings, device info and
  *Save device state*. Turn to move, press to pick, hold to go back.
- **Macro library:** up to 5 macros of 24 steps (key down / up / tap, delays, typed text, media
  keys), stored in the macropad's flash.
- **OLED idle animations:** draw frames pixel by pixel, import GIFs or image sequences with
  dithering, or start from presets. The macropad plays the animation when idle, turns the
  screen off later for burn-in protection, and swallows the key press that wakes it.
- **Auto-switch:** the desktop app watches the foreground app and switches profiles to match
  (Windows, macOS, Linux/X11).
- **Cross-platform configurator** for Windows, macOS (Apple Silicon and Intel) and Linux: a
  page per task (Keys, Macros, Idle, Auto-switch, Device, Settings), a `Ctrl+K` command
  palette, unsaved-change markers, one-file device backup / restore, `--self-test` and a
  built-in hardware test tool (`--hil`).
- **Non-blocking firmware** (Pico SDK + TinyUSB): 1 kHz scan with 5 ms debounce, 6-key
  rollover, and OLED updates streamed in the background.

## Gallery

| | |
|:-:|:-:|
| ![Command palette](docs/images/command-palette.png) | ![On-device OLED menu](docs/images/oled-menu.png) |
| **Command palette (`Ctrl+K`):** jump to any page, profile, key or command | **On-device menu:** hold the knob; turn, press, hold to go back |
| ![Device page](docs/images/device-page.png) | ![Macros page](docs/images/macros-page.png) |
| **Device:** connect, version check, uploads, backup / restore, firmware help | **Macros:** steps, ops, delays |
| ![Idle animation page](docs/images/idle-animation-page.png) | ![GIF import](docs/images/anim-import.png) |
| **Idle animation:** frames, canvas, presets, device upload | **GIF / image import** with dithering preview |
| ![Auto-switch page](docs/images/autoswitch-page.png) | ![Settings page](docs/images/settings-page.png) |
| **Auto-switch:** app → profile rules | **Settings:** theme, data folders, every shortcut, About |
| ![Action editor](docs/images/action-editor.png) | ![Profiles](docs/images/profile-manager.png) |
| **Action editor:** only the fields the chosen action uses | **Profiles:** create, duplicate, upload to a slot |
| ![Main window, light theme](docs/images/main-window-light.png) | |
| **Light theme:** follows the OS, or pick it on the Settings page | |

## Quick start

1. **Build the hardware:** RP2040-Zero, 12 switches with diodes in a 3 × 4 matrix, a KY-040
   encoder and an SSD1306 128 × 64 I2C OLED. The wiring and pin map are in the
   [user guide](docs/USER_GUIDE.md#wiring).
2. **Download** the [latest release](https://github.com/joshua12-5/macropad/releases): the
   firmware `macropad-fw-X.Y.Z.uf2` and the configurator for your OS.
3. **Flash:** hold **BOOT** on the RP2040-Zero while plugging it in, then copy the `.uf2` onto
   the `RPI-RP2` drive. The board reboots as a keyboard.
4. **Run the configurator:**

   | OS | Download | Run |
   |----|----------|-----|
   | Windows 10/11 x64 | `MacropadConfigurator-X.Y.Z-windows-x64.zip` | Extract, run `MacropadConfigurator\MacropadConfigurator.exe` (SmartScreen: *More info → Run anyway*) |
   | macOS 12+ (Apple Silicon / Intel) | `MacropadConfigurator-X.Y.Z-macos-arm64.zip` / `-macos-x86_64.zip` | Move the `.app` to Applications; allow it once under *Privacy & Security* (unsigned) |
   | Linux x86_64 (glibc ≥ 2.35) | `macropad-configurator-X.Y.Z-linux-x86_64.tar.gz` | Extract, `./install.sh` (udev rule), run `MacropadConfigurator/MacropadConfigurator` |

5. **Connect and configure:** click **Connect** in the header (`Ctrl+Shift+I`), click a key on
   the drawn macropad to edit it, then click **Upload** (`Ctrl+Shift+U`). `Ctrl+K` finds
   anything else by name.

Check downloads against `SHA256SUMS.txt`. Firmware `0.N` goes with configurator `0.N.x`.

## Documentation

- **[User guide](docs/USER_GUIDE.md):** hardware, flashing, installing, every feature, backups
  and updates.
- **[Troubleshooting](docs/TROUBLESHOOTING.md):** detection, permissions, OLED, encoder, ghosting,
  uploads, and bug reports.
- **[Documentation index](docs/README.md):** architecture, USB protocol, file formats,
  versioning and releases.
- **[Changelog](CHANGELOG.md)**

## Hardware at a glance

| Function | RP2040-Zero pins |
|----------|------------------|
| Matrix rows 1–3 | GP8, GP9, GP10 |
| Matrix columns 1–4 | GP11, GP12, GP13, GP14 |
| Encoder A (CLK) / B (DT) / switch | GP2 / GP3 / GP15 |
| OLED SDA / SCL (I2C0, 0x3C) | GP4 / GP5 |
| Debug UART TX / RX (115200) | GP0 / GP1 |

```
OLED                ENCODER
 1   2   3   4
 5   6   7   8
 9  10  11  12
```

The PCB and enclosure are not part of the project yet; the current build is hand-wired.

## Building from source

**Firmware** (Pico SDK 2.1.1, Arm GCC, CMake, Ninja). See [firmware/README.md](firmware/README.md):

```bash
git clone --depth 1 --branch 2.1.1 https://github.com/raspberrypi/pico-sdk.git
git -C pico-sdk submodule update --init --depth 1
export PICO_SDK_PATH=$PWD/pico-sdk
cd firmware
cmake -B build -G Ninja -DPICO_BOARD=waveshare_rp2040_zero
ninja -C build                      # → build/macropad.uf2
```

**Configurator** (Python 3.10+, PySide6). See [configurator/README.md](configurator/README.md):

```bash
cd configurator
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m macropad_config
```

Checks, style rules and the release process are in [CONTRIBUTING.md](CONTRIBUTING.md) and
[docs/RELEASE.md](docs/RELEASE.md).

## Project status

The latest release is **0.25.0**; `main` is at firmware **0.26** / configurator **0.26.0**
(USB protocol v1, not released yet). Both are feature-complete for the current hand-wired
hardware. The builds are tested in CI (host smokes, a hardware test suite
against a simulated device, and a firmware build with size and flash-map checks). Releases are
still marked as prereleases, and the apps are not code-signed yet.

## License

[MIT](LICENSE). Copyright (c) 2026 Joshua Zamora.
