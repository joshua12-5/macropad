# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to the versioning matrix in [`docs/VERSIONING.md`](docs/VERSIONING.md)
(firmware `0.N` / host `0.N.0` track Step *N*).

## [Unreleased]

### Planned

- Further polish in the Steps 18–24 block (packaging, more hardware coverage).

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

[Unreleased]: https://github.com/joshua12-5/macropad/compare/v0.21.0...HEAD
[0.21.0]: https://github.com/joshua12-5/macropad/releases/tag/v0.21.0
[0.20.0]: https://github.com/joshua12-5/macropad/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/joshua12-5/macropad/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/joshua12-5/macropad/compare/v0.17.0...v0.18.0
[0.17.0]: https://github.com/joshua12-5/macropad/compare/v0.16.0...v0.17.0
[0.16.0]: https://github.com/joshua12-5/macropad/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/joshua12-5/macropad/compare/v0.14.0...v0.15.0
[0.14.0]: https://github.com/joshua12-5/macropad/releases/tag/v0.14.0
