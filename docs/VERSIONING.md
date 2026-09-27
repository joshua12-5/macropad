# Versioning matrix (Step 24b)

How firmware, wire protocol, and host JSON schemas relate — and what must match.

## Matrix (shipping Step 24b)

| Axis | Constant / field | Current | Where |
|------|------------------|---------|--------|
| Firmware | `FW_VERSION_MAJOR`.`FW_VERSION_MINOR` | **0.25** | `firmware/include/config_protocol.h` → GET_INFO |
| Wire protocol | `CFG_PROTO_VERSION` / `proto_ver` | **1** | frame byte + GET_INFO; host `macropad_config/version.py` `PROTO_VER` |
| Host app | `HOST_APP_VERSION` | **0.25.0** | `configurator/macropad_config/version.py` (+ About) |
| Profile JSON / blob | `schema_version` | **1** | `profiles/*.json`, `PROFILE_BLOB`, host `SCHEMA_VERSION` |
| Macro library / blob | `schema_version` | **1** | `macros/library.json`, `MACRO_BLOB`, `MACRO_SCHEMA_VERSION` |
| Autoswitch rules | `schema_version` | **1** | `autoswitch/rules.json`, host `rules.SCHEMA_VERSION` |
| Animation blob | header `version` | **1** | `firmware/include/anim_format.h`, host `animation/codec.py` ([`ANIMATION.md`](ANIMATION.md)) |
| Animation project | `schema_version` | **1** | `*.mpanim.json`, host `animation/project.py` |
| Flash storage image | MPFL `version` | **3** | `firmware/src/storage.c` (v1/v2 still load) |
| USB `bcdDevice` | `USB_BCD` | **0x0119** (1.25) | `firmware/src/usb_descriptors.c` |
| CMake / UF2 | target name | `macropad_step24b` | `firmware/CMakeLists.txt` |
| Pico SDK | git tag | **2.1.1** (+ submodules) | `firmware/README.md`, `.github/workflows/firmware.yml` `PICO_SDK_TAG` |
| Board | `PICO_BOARD` | **waveshare_rp2040_zero** | `firmware/CMakeLists.txt` default, CI env |
| Release tag | `vMAJOR.MINOR.PATCH` | **v0.24.0** (latest published; 0.25.0 not tagged yet) | must equal host version and `FW_VERSION` major.minor; checked by `packaging/release_tools.py check` in `release.yml` |

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
| Blob readback (`PROFILE_READ` / `MACRO_READ`) | **23** | also GET_INFO flags bit2; HIL backup/byte-compare |
| OLED idle animation (`0x40`–`0x48`) | **25** | also GET_INFO flags bit3; editor authoring works offline, device actions explain the update |

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
schemas at **1** until an intentional incompatibility. Feature steps inserted after
Step 24 take the next minor with a letter suffix on the target: Step 24b → fw **0.25**,
host **0.25.0**, `macropad_step24b`, `bcdDevice` 0x0119. New commands in the existing
v1 framing are additive (older hosts ignore them, older firmware NAKs them with
`EINVAL`), so `proto_ver` stays 1.

Release process: [`RELEASE.md`](RELEASE.md). Changelog: [`../CHANGELOG.md`](../CHANGELOG.md).

## Smoke / hardware / CI

- Headless: `configurator/scripts/smoke_version.py`, `smoke_hil_mock.py` and `smoke_packaging.py`
  (via `run_all_smokes.py`), plus `python -m macropad_config --self-test`.
- HIL: `configurator/scripts/hil_test.py` checks the proto handshake and warns (or
  `--strict-version` fails) when fw minor ≠ `FW_VERSION_MINOR_CURRENT`.
- CI: [`.github/workflows/smokes.yml`](../.github/workflows/smokes.yml) runs host smokes;
  [`.github/workflows/firmware.yml`](../.github/workflows/firmware.yml) builds the firmware with Pico SDK
  **2.1.1** / `PICO_BOARD=waveshare_rp2040_zero` and uploads the UF2 artifact (`macropad-firmware-uf2`);
  [`.github/workflows/release.yml`](../.github/workflows/release.yml) (tag `vX.Y.Z`) rejects a tag
  that disagrees with `HOST_APP_VERSION`, `__version__`, `FW_VERSION` or CHANGELOG.
- Bumping the SDK: change `PICO_SDK_TAG` in `firmware.yml` (the cache key follows it),
  `MACROPAD_TESTED_SDK` in `firmware/CMakeLists.txt`, and `firmware/README.md` together.
- On device: [`HARDWARE_TEST.md`](HARDWARE_TEST.md).
