# Macropad firmware (RP2040)

Build target: `macropad_step17.uf2`

## Step 17 — Macro bank flash sync + protocol polish

- Flash image **v2** in the last 4 KiB sector (`MPFL`): profiles + 5×`macro_blob_v1` (162 B each).
- v1 images still load (profiles only); macros stay at factory defaults until next save.
- USB `MACRO_BEGIN` / `DATA` / `COMMIT` / `ABORT` / `GET` (no longer `ENOSYS`).
- Busy mutex: profile **or** macro upload, not both → `EBUSY`.
- RAM working set in `macros.c`; factory tables remain as defaults.
- `FW_VERSION_MINOR` = **17**. GET_INFO flags: bit0 storage, bit1 macro bank.

See [`../protocol/MACRO_BLOB.md`](../protocol/MACRO_BLOB.md) and
[`../protocol/PROTOCOL.md`](../protocol/PROTOCOL.md).

## Step 16 — Flash profile storage + USB upload (kept)

- Profile upload path unchanged; COMMIT rewrites the full v2 image (profiles + macros).

## Build

```bash
# Requires Pico SDK (PICO_SDK_PATH). Optional — CI/agents may skip if missing.
export PICO_SDK_PATH=/path/to/pico-sdk
mkdir -p build && cd build
cmake -DPICO_BOARD=pico ..
make -j$(nproc)
# Copy macropad_step17.uf2 to the Pico USB mass-storage bootloader.
```

Use `PICO_BOARD=pico` for RP2040-Zero bring-up (same GPIO numbers as Waveshare).

## UART debug

`stor load v2|v1 (macros factory)|default`, `stor save ok|fail`,
`cfg macro begin|commit|abort|get`, `macro save ok`, `profile save ok`.

## Next

**Step 18** — auto app-switch / further polish.
