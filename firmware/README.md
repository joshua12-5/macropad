# Firmware

RP2040-Zero · Pico SDK · TinyUSB · SSD1306 · KY-040 · Profiles (schema v1) · Action engine · Macro engine · On-device profile select · USB config protocol · Flash profile storage

Build target: `macropad_step16.uf2`

## Step 16 — Flash profile storage + USB upload

| Module | Role |
|--------|------|
| `storage.c` / `storage.h` | Last-sector flash image (`MPFL`), load on boot, save after COMMIT |
| `profile_blob.c` / `profile_blob.h` | Field-by-field pack/unpack (`PROFILE_BLOB_V1_SIZE` = 148) |
| `config_protocol.c` | `PROFILE_BEGIN` / `DATA` / `COMMIT` / `ABORT` / `GET` (meta); `MACRO_*` → ENOSYS |
| `profiles.c` | `profiles_write_slot` for RAM updates |

### Flash layout

- Offset: `PICO_FLASH_SIZE_BYTES - FLASH_SECTOR_SIZE` (typically `0x1FF000` on 2 MiB RP2040-Zero)
- Image: magic `MPFL` + version + active_slot + 5×148-byte blobs + CRC32
- UART: `stor load ok`, `stor load default`, `stor save ok/fail`

### Profile upload

Host sends chunked `profile_blob_v1` (see [`../protocol/PROFILE_BLOB.md`](../protocol/PROFILE_BLOB.md)).
Macros: `MACRO_BEGIN`… reserved for **Step 17** (device returns `ENOSYS`).

`FW_VERSION_MINOR` = **16**. GET_INFO `flags` bit0 = storage present.

## Step 15 — USB config protocol

Second HID interface (vendor usage page `0xFF00`) carries 64-byte framed config packets. Host uses hidapi on the same VID/PID filtered by usage page.

Protocol doc: [`../protocol/PROTOCOL.md`](../protocol/PROTOCOL.md).

### UART

```
cfg ping seq=N
cfg info seq=N
cfg echo seq=N len=N
cfg nak err=N …
cfg profile begin|commit|abort|get …
stor load ok|default
stor save ok|fail
```

### Flash / build

```bash
export PICO_SDK_PATH=/path/to/pico-sdk
cd firmware && mkdir -p build && cd build
cmake .. && make -j
# Copy macropad_step16.uf2 to the Pico USB mass-storage bootloader.
```

Build may be unverified on this host if Pico SDK / arm-none-eabi is not installed.

## Step 14 — On-device profile select UI

Long-press the encoder (~800 ms) while idle to open a scrollable profile menu on the OLED. Rotate to move the cursor; short-press to confirm; long-press again or wait ~9 s with no input to cancel. Matrix keys and encoder volume/media actions are muted while the menu is open.

## Earlier: Step 9 — Non-blocking macro engine

Built-in macros remain in `macros.c` until Step 17 syncs the host library.

UART (115200 on GP0/GP1) logs profile-select lines, `MACRO start` / `MACRO end`, action typer lines, `cfg …`, and `stor …`.
