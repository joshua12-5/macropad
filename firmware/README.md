# Macropad firmware (RP2040)

Build target: `macropad_step20.uf2`

## Step 20 — Testing / versioning polish

- `FW_VERSION_MINOR` = **20**; CMake target `macropad_step20`.
- USB `bcdDevice` = **0x0114** (1.20).
- Version matrix / bump rules: [`../docs/VERSIONING.md`](../docs/VERSIONING.md).
- Manual hardware checklist: [`../docs/HARDWARE_TEST.md`](../docs/HARDWARE_TEST.md).
- No PCB change — constants + docs alignment with host `0.20.0`.

**Next: Step 21** — more polish/testing (e.g. release notes or CI stub).

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

```bash
# Requires Pico SDK (PICO_SDK_PATH). Optional — CI/agents may skip if missing.
export PICO_SDK_PATH=/path/to/pico-sdk
mkdir -p build && cd build
cmake -DPICO_BOARD=pico ..
make -j$(nproc)
# Copy macropad_step20.uf2 to the Pico USB mass-storage bootloader.
```

Use `PICO_BOARD=pico` for RP2040-Zero bring-up (same GPIO numbers as Waveshare).

## UART debug

`stor load v2|v1 (macros factory)|default`, `stor save ok|fail`,
`stor debounce save`, `cfg macro …`, `cfg set_active N`, `cfg save_all ok`,
`macro save ok`, `profile save ok`.
