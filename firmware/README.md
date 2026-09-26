# Macropad firmware (RP2040)

Build target: `macropad_step19.uf2`

## Step 19 — Architecture hardening / polish

- `FW_VERSION_MINOR` = **19**; CMake target `macropad_step19`.
- Debounced flash persist of `active_slot` after `SET_ACTIVE` (~4 s quiet window;
  cancel/reschedule on repeated switches). UART: `stor debounce save`.
- `CFG_CMD_SAVE_ALL` (`0x32`) — immediate `storage_save_all()`; NAK `EBUSY` if
  upload in progress or flash program fails.
- `SET_ACTIVE` still OK while upload busy (RAM); overlapping uploads still rejected.
- Architecture overview: [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md).

**Next: Step 20** — testing / versioning polish.

## Step 18 — Auto app-switch (kept)

- Host `SET_ACTIVE` / `GET_ACTIVE`; Step 19 adds debounced flash persist.

## Step 17 — Macro bank flash sync + protocol polish

- Flash image **v2** in the last 4 KiB sector (`MPFL`): profiles + 5×`macro_blob_v1` (162 B each).
- v1 images still load (profiles only); macros stay at factory defaults until next save.
- USB `MACRO_BEGIN` / `DATA` / `COMMIT` / `ABORT` / `GET`.
- Busy mutex: profile **or** macro upload, not both → `EBUSY`.

See [`../protocol/MACRO_BLOB.md`](../protocol/MACRO_BLOB.md) and
[`../protocol/PROTOCOL.md`](../protocol/PROTOCOL.md).

## Build

```bash
# Requires Pico SDK (PICO_SDK_PATH). Optional — CI/agents may skip if missing.
export PICO_SDK_PATH=/path/to/pico-sdk
mkdir -p build && cd build
cmake -DPICO_BOARD=pico ..
make -j$(nproc)
# Copy macropad_step19.uf2 to the Pico USB mass-storage bootloader.
```

Use `PICO_BOARD=pico` for RP2040-Zero bring-up (same GPIO numbers as Waveshare).

## UART debug

`stor load v2|v1 (macros factory)|default`, `stor save ok|fail`,
`stor debounce save`, `cfg macro …`, `cfg set_active N`, `cfg save_all ok`,
`macro save ok`, `profile save ok`.
