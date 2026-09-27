# RP2040 Programmable Macropad

[![Host smokes](https://github.com/joshua12-5/macropad/actions/workflows/smokes.yml/badge.svg)](https://github.com/joshua12-5/macropad/actions/workflows/smokes.yml)
[![Firmware build](https://github.com/joshua12-5/macropad/actions/workflows/firmware.yml/badge.svg)](https://github.com/joshua12-5/macropad/actions/workflows/firmware.yml)

Commercial-style 12-key macropad on **Waveshare RP2040-Zero**: matrix + EC11 encoder + SSD1306 OLED, Pico SDK / TinyUSB firmware, and a Python/PySide6 desktop configurator.

## Layout

```
OLED                         ENCODER
1   2   3   4
5   6   7   8
9  10  11  12
```

## Status

| Step | Topic | Status |
|------|--------|--------|
| 1 | System architecture | Done (chat) |
| 2 | RP2040-Zero pinout | Frozen in `firmware/include/board_pins.h` |
| 3 | Matrix scan | Done |
| 4 | USB HID keyboard | Done |
| 5 | Rotary encoder + volume/mute | Done |
| 6 | SSD1306 OLED UI | Done |
| 7 | Profile system (schema v1) | Done |
| 8 | Action engine (TEXT/URL/APP/MACRO stub) | Done |
| 9 | Non-blocking macro engine | Done |
| 10 | PySide6 configurator shell | Done |
| 11 | Key/encoder action editors | Done |
| 12 | Profile manager (new / duplicate / delete) | Done |
| 13 | Macro library editor (host JSON) | Done |
| 14 | On-device profile select UI | Done |
| 15 | USB config protocol (vendor HID) | Done |
| 16 | Flash profile storage + USB upload | Done |
| 17 | Macro-bank flash sync / polish | Done |
| 18 | Auto app-switch / polish | Done |
| 19 | Architecture hardening / polish | Done |
| 20 | Testing / versioning polish | Done |
| 21 | Changelog / CI smokes / release polish | Done |
| 22 | Verified firmware build + CI UF2 artifact | Done |
| 23 | Hardware-in-the-loop test tooling | Done |
| 24 | Release packaging (tag → GitHub Release) | Done |

## Download

Prebuilt binaries are on the **[Releases page](https://github.com/joshua12-5/macropad/releases)**
(latest: [v0.24.0](https://github.com/joshua12-5/macropad/releases/tag/v0.24.0), prerelease):

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

**Step 24** adds a tag-triggered release pipeline
([`.github/workflows/release.yml`](.github/workflows/release.yml)): pushing `vX.Y.Z` checks the
tag against `version.py` / `FW_VERSION` / CHANGELOG, builds the firmware and PyInstaller bundles
for Windows, macOS and Linux, runs a headless `--self-test` on each packaged build and publishes a
GitHub prerelease with `SHA256SUMS.txt`; a manual run is a publish-free dry run. The configurator
gains `--version` / `--self-test` / `--hil`, per-user data dirs for frozen builds, and ships
cython-hidapi (native library bundled). 11 host smokes (`smoke_packaging.py`). Versions: firmware
**0.24**, host **0.24.0**, UF2 `macropad_step24`, `bcdDevice` 0x0118. How to cut a release:
[`docs/RELEASE.md`](docs/RELEASE.md).

**Step 23** (kept) adds hardware-in-the-loop tooling:
[`configurator/scripts/hil_test.py`](configurator/scripts/hil_test.py) runs an
ordered suite over the vendor config HID interface (PING latency, GET_INFO
version handshake, ECHO + CRC injection, malformed-frame NAKs, profile / macro
upload protocol + backup → upload → byte-compare → restore, SET_ACTIVE cycle,
SAVE_ALL, guided key checklist) with PASS/FAIL/SKIP output, `--json`, and a
non-zero exit on failure. Flash-writing steps need `--allow-flash-write`.
`--mock` runs the same suite against an in-process firmware model — that is
`smoke_hil_mock.py` in CI. Firmware 0.23 adds `PROFILE_READ` /
`MACRO_READ` readback. How to run it on hardware:
[`docs/HARDWARE_TEST.md`](docs/HARDWARE_TEST.md).

**Step 22** (kept) is the first real firmware compile: Pico SDK **2.1.1**,
`PICO_BOARD=waveshare_rp2040_zero`, zero warnings under `-Wall -Wextra`, and a
new GitHub Actions [`.github/workflows/firmware.yml`](.github/workflows/firmware.yml)
that builds the firmware and uploads `macropad_step22.uf2` as the
`macropad-firmware-uf2` artifact.

**Step 21** (kept) adds release polish: [`CHANGELOG.md`](CHANGELOG.md) (Keep a Changelog,
Steps 14–21), GitHub Actions [`.github/workflows/smokes.yml`](.github/workflows/smokes.yml)
(host smokes), and [`docs/RELEASE.md`](docs/RELEASE.md).

**Step 20** (kept): [`docs/VERSIONING.md`](docs/VERSIONING.md)
(fw major.minor vs `proto_ver` vs JSON schemas), host
`macropad_config/version.py` (feature min-fw gates), Connect/About proto
mismatch warnings, `smoke_version.py`, and
[`docs/HARDWARE_TEST.md`](docs/HARDWARE_TEST.md).

**Step 19** (kept): `docs/ARCHITECTURE.md`, debounced flash persist of
`active_slot` after `SET_ACTIVE`, `SAVE_ALL` (`0x32`), clearer host errors,
disconnect-safe autoswitch, `run_all_smokes.py`.

**Step 18** (kept): host auto app-switch via `SET_ACTIVE` (`0x30`); Step 19 adds
debounced flash persist so frequent switches still avoid per-switch erase.

## Architecture

Stack layers, data flows, flash vs RAM: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
Version matrix / compat: [`docs/VERSIONING.md`](docs/VERSIONING.md).
Changelog: [`CHANGELOG.md`](CHANGELOG.md). Cut a release: [`docs/RELEASE.md`](docs/RELEASE.md).
Manual hardware checklist: [`docs/HARDWARE_TEST.md`](docs/HARDWARE_TEST.md).
CI runs **host configurator smokes only** (no firmware build).

## Protocol

Wire format and commands: [`protocol/PROTOCOL.md`](protocol/PROTOCOL.md).
Profile binary packing: [`protocol/PROFILE_BLOB.md`](protocol/PROFILE_BLOB.md).
Macro binary packing: [`protocol/MACRO_BLOB.md`](protocol/MACRO_BLOB.md).

## Profiles

Host-side JSON (schema v1): [`profiles/`](profiles/) + [`profiles/SCHEMA.md`](profiles/SCHEMA.md).

## Macros

Host library (configurator source of truth): [`macros/library.json`](macros/library.json) + [`macros/SCHEMA.md`](macros/SCHEMA.md).

Host library uploads into the firmware RAM working set + flash bank (Step 17).
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
python scripts/smoke_protocol.py
python scripts/smoke_storage.py
python scripts/smoke_macros_blob.py
python scripts/smoke_autoswitch.py
python scripts/smoke_hil_mock.py      # HIL suite vs mock device
python scripts/smoke_packaging.py     # release tooling + --version
python -m macropad_config --self-test # full headless self-test (Qt offscreen)
```

## Firmware

See [`firmware/README.md`](firmware/README.md).

Verified with [Pico SDK](https://github.com/raspberrypi/pico-sdk) tag **2.1.1** and
`PICO_BOARD=waveshare_rp2040_zero` (`PICO_BOARD=pico` also builds). Flash target:
`macropad_step24.uf2` — or download `macropad-fw-X.Y.Z.uf2` from the
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
# → build/macropad_step24.uf2 (hold BOOT, plug in, copy to RPI-RP2)
```

**On-device profile select:** long-press encoder (~800 ms) → OLED menu; rotate to highlight; short-press to confirm; long-press or ~9 s idle to cancel.

**USB:** IF0 keyboard+consumer; IF1 vendor config HID (usage page `0xFF00`), 64-byte framed protocol with profile upload.

**Flash:** last 4 KiB sector holds magic/`MPFL` image with 5 packed profile blobs + CRC.

## Pinout (locked)

| Function | GPIO |
|----------|------|
| Rows 1–3 | GP8, GP9, GP10 |
| Cols 1–4 | GP11–GP14 |
| Encoder A/B/SW | GP2, GP3, GP15 |
| OLED SDA/SCL | GP4, GP5 (I2C0) |
| NeoPixel (onboard) | GP16 |
| Debug UART | GP0 TX, GP1 RX |

## License

TBD by repo owner.
