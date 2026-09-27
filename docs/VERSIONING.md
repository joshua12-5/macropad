# Versioning matrix (Step 22)

How firmware, wire protocol, and host JSON schemas relate — and what must match.

## Matrix (shipping Step 22)

| Axis | Constant / field | Current | Where |
|------|------------------|---------|--------|
| Firmware | `FW_VERSION_MAJOR`.`FW_VERSION_MINOR` | **0.22** | `firmware/include/config_protocol.h` → GET_INFO |
| Wire protocol | `CFG_PROTO_VERSION` / `proto_ver` | **1** | frame byte + GET_INFO; host `macropad_config/version.py` `PROTO_VER` |
| Host app | `HOST_APP_VERSION` | **0.22.0** | `configurator/macropad_config/version.py` (+ About) |
| Profile JSON / blob | `schema_version` | **1** | `profiles/*.json`, `PROFILE_BLOB`, host `SCHEMA_VERSION` |
| Macro library / blob | `schema_version` | **1** | `macros/library.json`, `MACRO_BLOB`, `MACRO_SCHEMA_VERSION` |
| Autoswitch rules | `schema_version` | **1** | `autoswitch/rules.json`, host `rules.SCHEMA_VERSION` |
| USB `bcdDevice` | `USB_BCD` | **0x0116** (1.22) | `firmware/src/usb_descriptors.c` |
| CMake / UF2 | target name | `macropad_step22` | `firmware/CMakeLists.txt` |
| Pico SDK | git tag | **2.1.1** (+ submodules) | `firmware/README.md`, `.github/workflows/firmware.yml` `PICO_SDK_TAG` |
| Board | `PICO_BOARD` | **waveshare_rp2040_zero** | `firmware/CMakeLists.txt` default, CI env |

Firmware **major.minor** is a product revision (shown in Connect / GET_INFO).
It is **not** the same number as `proto_ver` or JSON `schema_version`.

## Compatibility rules

### 1. Host must match `proto_ver`

On Connect / GET_INFO the device reports `proto_ver` (frame version + info byte).

- Host expected value: `PROTO_VER` (== `CFG_PROTO_VERSION` == **1**).
- If `device.proto_ver != PROTO_VER`: **warn clearly** (dialog + status). Do not assume
  uploads / SET_ACTIVE / SAVE_ALL are safe. Prefer disconnect / upgrade pairing.
- Frame unpack already rejects foreign frame `version` bytes (`FrameError`).

### 2. Schema version checks (host JSON + blobs)

| Document | Rule |
|----------|------|
| Profile JSON | `schema_version` must equal host `SCHEMA_VERSION` (1) or load fails |
| Macro library | `schema_version` must equal `MACRO_SCHEMA_VERSION` (1) |
| Autoswitch rules | `schema_version` must equal autoswitch `SCHEMA_VERSION` (1) |
| Profile / macro blobs | packed `schema_version` must be 1; firmware rejects other values |

Bump a schema only with a migration plan (new reader path or converter). Do not
silently accept unknown schema versions.

### 3. Feature gates by firmware minor (same major)

Host may talk protocol v1 to older Step builds. Some Device menu actions need a
minimum `FW_VERSION_MINOR` (major must match expected **0**):

| Feature | Min fw minor | Notes |
|---------|--------------|--------|
| Profile upload | **16** | BEGIN/DATA/COMMIT |
| Macro upload | **17** | macro bank + MACRO_* cmds |
| Autoswitch (`SET_ACTIVE`) | **18** | host-driven active slot |
| Save device state (`SAVE_ALL`) | **19** | immediate flash rewrite |

If firmware is too old, the configurator **disables** those actions and sets a
tooltip explaining the required version (Connect still works for info).

## How bumping works

| What you change | Bump | Also update |
|-----------------|------|-------------|
| Polish / host-only / docs / smokes in Steps 18–24 | `FW_VERSION_MINOR` + host `0.MINOR.0` + CMake `macropad_stepNN` + `bcdDevice` | READMEs, About, this matrix, CHANGELOG |
| Incompatible wire change (new framing, cmd meaning) | `CFG_PROTO_VERSION` / `PROTO_VER` | Both sides; old hosts must warn |
| Profile / macro / autoswitch JSON shape | that schema’s `schema_version` | SCHEMA.md, validators, blobs, firmware unpack |
| Breaking firmware API without proto bump | raise `FW_VERSION_MAJOR` | Document min host; rare |

**Practice for this repo:** Step *N* → `FW_VERSION_MINOR = N`, host
`HOST_APP_VERSION = "0.N.0"`, UF2 `macropad_stepN`, keep `proto_ver` and JSON
schemas at **1** until an intentional incompatibility.

Release process: [`RELEASE.md`](RELEASE.md). Changelog: [`../CHANGELOG.md`](../CHANGELOG.md).

## Smoke / hardware / CI

- Headless: `configurator/scripts/smoke_version.py` (via `run_all_smokes.py`).
- CI: [`.github/workflows/smokes.yml`](../.github/workflows/smokes.yml) runs host smokes;
  [`.github/workflows/firmware.yml`](../.github/workflows/firmware.yml) builds the firmware with Pico SDK
  **2.1.1** / `PICO_BOARD=waveshare_rp2040_zero` and uploads the UF2 artifact (`macropad-firmware-uf2`).
- Bumping the SDK: change `PICO_SDK_TAG` in `firmware.yml` (the cache key follows it),
  `MACROPAD_TESTED_SDK` in `firmware/CMakeLists.txt`, and `firmware/README.md` together.
- On device: [`HARDWARE_TEST.md`](HARDWARE_TEST.md).
