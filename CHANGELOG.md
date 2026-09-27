# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to the versioning matrix in [`docs/VERSIONING.md`](docs/VERSIONING.md)
(firmware `0.N` and host `0.N.0` share the minor number *N*).

## [Unreleased]

### Added

- **User documentation**: [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) (parts and wiring, flashing,
  installing the configurator on Windows / macOS / Linux, every action type, profiles, macros,
  idle animations, auto-switch, backups, firmware updates, command-line flags),
  [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) and a docs index
  [`docs/README.md`](docs/README.md).
- Screenshot set under `docs/images/` used by the README and the user guide.

### Changed

- Top-level `README.md` rewritten as a product page (features, gallery, quick start, links).
- Changelog entries describe the changes themselves instead of internal milestone numbers;
  link references now exist only for tagged releases (v0.24.0 and later).
- Comments and docstrings no longer cite internal milestones.

### Fixed

- Auto-switch docs and the Auto-switch dialog said `SET_ACTIVE` never writes flash. The switch is
  instant in RAM, and the device then saves the slot once it has been stable for 4 s (skipped when
  flash already holds it).
- `macros/SCHEMA.md` still said macros could not be synced to the device; it now describes the
  5 × 24-step macro bank and **Upload macros to device…**.
- `--hil --help` understated flash wear: the animation settings / round-trip tests also need
  `--allow-flash-write` (7 storage-sector writes plus a few animation-region sectors per full run).
- `docs/ANIMATION.md` linked to a flash-map anchor that no longer existed.
- The 0.25.0 entry below gave the animation frame cap as 255; the format allows 1024 frames.

### Planned

- Code signing / notarisation for the Windows and macOS configurator builds.
- More hardware coverage (HIL runs on real boards per release).

## [0.25.0] — 2026-09-27

OLED idle animations, plus a repository cleanup and two configurator editor fixes. The PCB and
enclosure are not part of this release. Firmware **0.25**, host **0.25.0**, USB `bcdDevice`
**0x0119**, release asset `macropad-fw-0.25.0.uf2` (local build output is now
`firmware/build/macropad.uf2`).

### Added

- **Firmware idle animations** (`anim.c`): after `idle_timeout` (default 60 s, 0 = disabled) with
  no key / encoder input the OLED plays the stored animation at its fps (looping or holding the
  last frame); a second `blank_timeout` (default 10 min, 0 = never) switches the panel off for
  burn-in protection. Any key / encoder input wakes the normal UI and is **swallowed** (the waking
  key stays out of HID reports until released; a waking encoder turn / press is dropped and does
  not open the profile menu). Built-in procedural starfield when nothing is uploaded.
- **Animation flash region**: 128 KiB at `0x1DF000`–`0x1FEFFF`, directly below the MPFL sector,
  static-asserted and boot-checked against the image end; `MPAN` v1 blob (32-byte header with
  magic, version, frame count, fps, loop flag, CRC32, name + RAW / PackBits-RLE / XOR-delta-RLE
  frames in SSD1306 page order). At least 127 frames fit in the worst case (all uncompressed);
  the format allows up to 1024.
- **Protocol `0x40`–`0x48`**: `ANIM_BEGIN` / `ANIM_DATA` / `ANIM_COMMIT` / `ANIM_ABORT` /
  `ANIM_INFO` / `ANIM_READ` / `ANIM_SETTINGS_GET` / `ANIM_SETTINGS_SET` / `ANIM_PREVIEW`;
  GET_INFO flags **bit3** (`CFG_INFO_FLAG_ANIM`). Same 48-byte chunk / CRC32 / `EBUSY` rules as
  profile and macro uploads; COMMIT validates the whole blob in flash (`EBADMSG` + invalidate on
  failure); only the needed sectors are erased, via `flash_safe_execute()`.
- **Configurator: Tools → Idle animation…** — frame strip with thumbnails (add / duplicate /
  delete / reorder), 128×64 pixel canvas (pen, eraser, brush size, invert,
  clear, shift, onion skin, grid, zoom, undo / redo), live preview at the chosen fps, settings
  (fps, loop, enabled, idle / blank timeout), GIF / PNG-sequence / single-image import (fit or
  stretch, threshold or Floyd–Steinberg dithering, invert), 4 presets (starfield, bouncing text,
  scrolling text with your text, pulse / breathing), projects saved as `*.mpanim.json` in the
  user data folder, GIF and `.mpan` export, device upload with progress, preview on device,
  push / read settings; clear message for firmware < 0.25.
- Host package `macropad_config/animation/` (codec, presets, imaging, GIF writer, projects,
  5×7 font), `device.py` `anim_*` API, mock firmware animation model, HIL tests `anim_info`,
  `anim_protocol`, `anim_preview`, `anim_settings`, `anim_roundtrip`; `restore_check` also
  compares the stored animation + idle settings.
- Smokes `smoke_anim_codec.py` (host codec cross-checked against the firmware C decoder compiled
  on the host) and `smoke_anim_device.py` (protocol vs mock incl. seeded bugs, editor GUI);
  `--self-test` includes an animation encode / decode check.
- `docs/ANIMATION.md`; flash map in `docs/ARCHITECTURE.md`; manual idle checklist in
  `docs/HARDWARE_TEST.md`.
- `LICENSE` (MIT, Copyright (c) 2026 Joshua Zamora), `CONTRIBUTING.md`, `.editorconfig`,
  `.clang-format` (firmware C style; not applied wholesale), `ruff.toml` (lint + format config).
- `smoke_editor_forms.py` (14th smoke): per-type form rows in the action editor and the macro
  step editor, macro-library dirty tracking and the step-0 regression below.

### Changed

- **Non-blocking OLED flush**: `oled_driver_task()` streams the framebuffer in 16-byte I2C chunks
  (≤ 2 per 1 ms tick ≈ 0.81 ms) instead of blocking ≈ 26 ms per 1 KiB frame at 400 kHz; the
  normal UI benefits too.
- Flash storage image **MPFL v3** (v2 + idle settings); v1 / v2 still load and are rewritten as
  v3 on the next save.
- `firmware.yml` size check now fails when the image reaches the animation region and prints the
  headroom.
- Firmware size (gcc 14.2): text 65364 B (+8448 vs 0.24.0), bss 18688 B (+7528), UF2 131072 B (+16896).
- **Firmware build target renamed** `macropad_stepNN` → `macropad` (local `build/macropad.uf2`);
  CI / release workflows follow. Release asset names are unchanged (`macropad-fw-<ver>.uf2`).
- User-facing strings no longer mention internal milestone numbers: the UART boot banner is now
  `=== Macropad firmware 0.25 ===`, the About box shows the version and copyright, and the
  status hints and old-firmware message name the release asset instead of a build target.
- Docs consolidated under `docs/`: `protocol/PROTOCOL.md`, `PROFILE_BLOB.md`, `MACRO_BLOB.md`
  moved to `docs/` (`protocol/README.md` points there); READMEs and `ARCHITECTURE.md` describe the
  current state instead of a development log (history stays in this changelog).
- Python code linted and formatted with ruff (pyupgrade typing, import order, unused imports /
  variables, strict `zip`); dead code removed (unused firmware functions `profiles_next/prev`,
  `storage_save_slot`, `storage_loaded_from_flash`, `macros_name`, `text_table_count`,
  `anim_settings_get/set`, `anim_state`, `oled_driver_frames_pushed`; unused host helpers).
- CI: actions bumped to Node 24 majors (`checkout@v7`, `cache@v6`, `setup-python@v7`,
  `upload-artifact@v7`, `download-artifact@v8`); Linux runners pinned to `ubuntu-24.04`
  (packaging stays on `ubuntu-22.04` for glibc 2.35); smokes workflow runs `ruff check` +
  `ruff format --check`.
- `.gitignore` completed (CMake/IDE outputs, PyInstaller dirs, HIL / self-test reports, UF2s).

### Fixed

- **Macro library: selecting macros corrupted data** — switching to another macro wrote the
  (never loaded) step editor into step 0 of the macro being left, turning it into `END`; the
  library was then marked dirty so closing asked "Discard changes?". The step editor is now loaded
  for the selected row and edits are written back only when they change the step.
- Action editor and macro step editor hide the **label together with the field** for rows that do
  not apply to the selected type (e.g. MACRO no longer shows Key / Mods / Text id / Media / Volume /
  Profile labels; a TAP step no longer shows Delay / Text id / Consumer).
- `smoke_macros_blob.py` `test_append_end_if_missing` now actually tests the missing-END case.

## [0.24.0] — 2026-09-27

### Added

- **Tag-triggered release pipeline** `.github/workflows/release.yml`: pushing `vX.Y.Z` verifies the
  tag against `version.py`, `macropad_config.__version__`, firmware `FW_VERSION` and a CHANGELOG
  section, builds the firmware (reusing `firmware.yml` via `workflow_call`) and the configurator on
  Windows x64, macOS arm64, macOS x86_64 (experimental leg) and Linux x86_64 (Ubuntu 22.04 / glibc
  2.35), runs a headless `--self-test` on every packaged build (and again after re-extracting the
  archive), then publishes a GitHub prerelease with the CHANGELOG section as notes, all assets and
  `SHA256SUMS.txt`. `workflow_dispatch` runs everything as a dry run and uploads the would-be
  assets as the `release-dry-run` artifact instead of publishing.
- **Release assets**: `macropad-fw-<ver>.uf2` (+ `.elf`, `.uf2.sha256`),
  `MacropadConfigurator-<ver>-windows-x64.zip`, `MacropadConfigurator-<ver>-macos-arm64.zip`
  (ad-hoc signed `.app`), `macropad-configurator-<ver>-linux-x86_64.tar.gz` (app + udev rule
  `70-macropad.rules`, `INSTALL.txt`, `.desktop` template, `install.sh`), `SHA256SUMS.txt`.
- **Packaging** `packaging/`: PyInstaller one-dir spec, pinned build requirements
  (PySide6-Essentials 6.8.3, hidapi 0.15.0, PyInstaller 6.22.3), `release_tools.py`
  (`check` / `notes` / `sha256sums` / `versions`), `ci_selftest.py`, Linux extras.
- **Configurator CLI**: `--version`, `--self-test [--report FILE]` (imports every module, frame/CRC
  roundtrip, bundled profiles/macros/rules load + blob pack, hidapi binding loads + enumerates,
  HIL suite vs mock device for both hid APIs, MainWindow on Qt `offscreen`; exit 0/1) and
  `--hil ARGS` (the HIL tool inside the packaged app). Windowed Windows builds attach to the parent
  console for output.
- `macropad_config/paths.py`: frozen builds read bundled defaults from the bundle and keep user data
  in `%APPDATA%\MacropadConfigurator`, `~/Library/Application Support/MacropadConfigurator` or
  `$XDG_DATA_HOME/macropad-configurator` (seeded on first run, never overwritten).
  `MACROPAD_USER_DATA` overrides; source checkouts behave as before.
- `scripts/smoke_packaging.py` (11th host smoke): release_tools checks, CHANGELOG extraction,
  SHA256SUMS, user-data seeding, `--version`, non-Qt self-test checks.

### Changed

- **hidapi binding**: `requirements.txt` now uses `hidapi` (cython-hidapi, wheels embed the native
  library — no system libhidapi / `hidapi.dll` needed) instead of `hid` (pyhidapi, still supported).
  On Linux the package's `hidraw` backend is preferred over its libusb-based `hid` module.
- Firmware **0.24** / host **0.24.0**, UF2 target `macropad_step24`, `bcdDevice` `0x0118`.
  No protocol or blob changes (`CFG_PROTO_VERSION` 1, schemas 1).
- `docs/RELEASE.md` rewritten around the pipeline; README download section.
- `smokes.yml` also runs the full `--self-test` (incl. Qt offscreen).

## [0.23.0] — 2026-09-27

### Added

- **Hardware-in-the-loop suite** `configurator/scripts/hil_test.py` (package `macropad_config/hil/`,
  also `python -m macropad_config.hil`). Ordered tests over the vendor config HID interface using the
  production `ConfigDevice` / `frames` code: enumerate (+ `--list`), PING latency min/avg/max,
  GET_INFO + `version.py` handshake, ECHO random payloads + CRC injection, malformed frames
  (unknown cmd / bad magic / bad version / length / seq echo / response-flag / short report),
  profile + macro upload protocol (ABORT mid-upload, EBUSY mutex, bad COMMITs), profile + macro
  backup → upload → byte-compare → restore, SET_ACTIVE / GET_ACTIVE cycle, SAVE_ALL, guided
  `--interactive` key/encoder checklist, final restore check. PASS/FAIL/SKIP report, `--json`,
  exit 1 on FAIL / 2 on no device. Flash-writing steps require `--allow-flash-write`.
- **Mock device** `macropad_config/hil/mock.py`: fake `hid` module (pyhidapi and cython-hidapi
  flavours) + Python model of `config_protocol.c` / `storage.c` / blob canonicalisation, incl.
  NAK codes, upload staging, EBUSY, 5 slots, 4 KiB flash image with write counter, debounced persist;
  `--mock` / `--mock-fw-minor N`.
- `smoke_hil_mock.py` (runs the suite vs the mock, checks flash-write counts, fw 0.22 compat paths,
  interactive answers, and that seeded firmware bugs are caught). `run_all_smokes.py` → **10** scripts.
  CI smokes workflow also runs `hil_test.py --mock --allow-flash-write` and uploads the JSON report.
- Firmware: `CFG_CMD_PROFILE_READ` (`0x15`) / `CFG_CMD_MACRO_READ` (`0x25`) chunked readback of the
  packed RAM blobs (≤ 48 B per response), GET_INFO flags bit2 `CFG_INFO_FLAG_READBACK`; host
  `ConfigDevice.profile_read()` / `macro_read()` / `echo()` / `exchange_raw()` / `request()`,
  `version.fw_supports_readback()` (min fw 0.23).

### Changed

- Firmware `FW_VERSION_MINOR` **23**, target `macropad_step23`, `bcdDevice` **0x0117** (1.23);
  host **0.23.0**. Firmware size +400 B text (56508 → 56908), bss unchanged, UF2 113152 → 114176 B.
- Firmware: debounced SET_ACTIVE persist is skipped when flash already holds a matching v2 image with
  the same `active_slot` (`stor debounce skip (unchanged)`) — cycling slots and returning is free.
- `PROTOCOL.md`: documents validation order, seq echo-only semantics, `ENOSYS` as reserved/not emitted,
  readback commands and canonical blob form.

### Fixed

- Host: `ConfigDevice` only spoke cython-hidapi (`hid.device()`), but `requirements.txt` pins the
  pyhidapi `hid` package (`hid.Device(path=...)`) → `AttributeError` on real hardware. Both APIs now
  work; open/read/write errors surface as `DeviceError`. NAKs raise `NakError` (subclass, has `.code`).
- Host: `pack_macro` kept steps after the first `END`, while firmware truncates there, so such blobs
  read back differently (CRC mismatch after upload). Now truncates like firmware.

## [0.22.0] — 2026-09-27

### Added

- **First verified firmware build.** Pico SDK **2.1.1** (TinyUSB submodule),
  `PICO_BOARD=waveshare_rp2040_zero`, Arm GNU `arm-none-eabi-gcc` 14.2 (Debian/Ubuntu apt),
  CMake + Ninja. Builds with **zero warnings** under `-Wall -Wextra` (also clean under
  `-Wshadow -Wconversion -Wmissing-prototypes -Wstrict-prototypes -Wundef`).
- GitHub Actions firmware workflow [`.github/workflows/firmware.yml`](.github/workflows/firmware.yml):
  ubuntu-latest, apt toolchain, cached Pico SDK 2.1.1 + submodules, Ninja build,
  size + storage-offset check, **UF2 uploaded as the `macropad-firmware-uf2` artifact**.

### Changed

- Firmware `FW_VERSION_MINOR` **22**, CMake/UF2 target `macropad_step22`, USB `bcdDevice` **0x0116** (1.22).
- Host `HOST_APP_VERSION` **0.22.0**; version matrix, READMEs, build docs updated.
- CMake default `PICO_BOARD` is now `waveshare_rp2040_zero` (2 MiB flash, W25Q080 boot2 @ clkdiv 4);
  `-Wall -Wextra` on the firmware target; warns if the SDK is not the verified 2.1.1.
- Storage flash write now goes through `flash_safe_execute()` (`pico_flash`) instead of a hand-rolled
  `save_and_disable_interrupts()` + `flash_range_*` block. Identical on this single-core build (IRQs
  masked for erase+program); fails safely instead of corrupting XIP if core 1 is ever started.
- Dropped unused `tinyusb_board` link dependency (TinyUSB BSP; no `board_*` calls in the firmware).
- UART boot banner updated to the current firmware version (it still showed an older one).
- `main.c`: initialise `enc_press_at` (gcc 13.2 on ubuntu-latest flagged `-Wmaybe-uninitialized`;
  false positive — only read after a press sets it — but keeps CI at zero warnings).

### Fixed

- Stack budget: `storage_save_all()` held the 1.5 KiB flash image on the stack (1592 B frame), so the
  USB callback → `PROFILE/MACRO_COMMIT` → save path exceeded the 2 KiB core-0 stack. The image is now
  built in the existing static 4 KiB sector buffer (frame now < 200 B; `.bss` unchanged).

## [0.21.0] — 2026-09-27

### Added

- `CHANGELOG.md` (Keep a Changelog).
- GitHub Actions host smoke workflow: [`.github/workflows/smokes.yml`](.github/workflows/smokes.yml)
  (Python 3.11+, `configurator/requirements.txt`, `run_all_smokes.py`; **no** Pico SDK / firmware build).
- [`docs/RELEASE.md`](docs/RELEASE.md) — how to cut a release (tag, changelog, flash target).

### Changed

- Firmware `FW_VERSION_MINOR` **21**, CMake/UF2 target `macropad_step21`, USB `bcdDevice` **0x0115** (1.21).
- Host `HOST_APP_VERSION` **0.21.0**; version matrix and READMEs updated.

## [0.20.0] — 2026-09-26

### Added

- [`docs/VERSIONING.md`](docs/VERSIONING.md) — fw major.minor vs `proto_ver` vs JSON schemas.
- Host `macropad_config/version.py` with feature min-fw gates and Connect/About proto warnings.
- `smoke_version.py`; [`docs/HARDWARE_TEST.md`](docs/HARDWARE_TEST.md) checklist.

### Changed

- Align `FW_VERSION_MINOR` / host / CMake `macropad_step20` / `bcdDevice` 0x0114 (1.20).

## [0.19.0] — 2026-09-26

### Added

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) stack overview.
- `CFG_CMD_SAVE_ALL` (`0x32`) immediate flash rewrite.
- Debounced flash persist of `active_slot` after `SET_ACTIVE`.
- `configurator/scripts/run_all_smokes.py` aggregator; clearer host errors; disconnect-safe autoswitch.

## [0.18.0] — 2026-09-26

### Added

- Host auto app-switch: rules JSON + foreground poll → `SET_ACTIVE` / `GET_ACTIVE`.
- Autoswitch editor (Tools → Auto-switch) and Device menu toggle.

## [0.17.0] — 2026-09-26

### Added

- Macro-bank flash sync: USB `MACRO_BEGIN` / `DATA` / `COMMIT` / `ABORT` / `GET`.
- Flash image **v2** (`MPFL`) with packed profile + macro blobs.

### Fixed

- Portable `cstr_nlen` instead of `strnlen` for firmware portability.

## [0.16.0] — 2026-09-26

### Added

- Flash profile storage (last 4 KiB sector) + chunked USB profile upload
  (`PROFILE_BEGIN` / `DATA` / `COMMIT` / `ABORT`).

## [0.15.0] — 2026-09-26

### Added

- USB vendor-HID config channel (usage page `0xFF00`), 64-byte framed protocol
  (`PING` / `GET_INFO` / `ECHO`), host protocol client.

## [0.14.0] — 2026-09-26

### Added

- On-device profile select UI: long-press encoder → OLED menu; rotate / short-press to confirm.

[Unreleased]: https://github.com/joshua12-5/macropad/compare/v0.25.0...HEAD
[0.25.0]: https://github.com/joshua12-5/macropad/compare/v0.24.0...v0.25.0
[0.24.0]: https://github.com/joshua12-5/macropad/releases/tag/v0.24.0

<!-- Versions before 0.24.0 were not tagged, so they have no link references. -->
