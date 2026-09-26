# Macro binary blob v1

Shared wire format for one macro bank slot (ids **0–4**). **Do not** `memcpy`
a host or firmware C struct across the USB link — packing is field-by-field,
little-endian, with **no C struct padding**.

Constants are mirrored in:

- Firmware: `firmware/include/macro_blob.h`
- Host: `configurator/macropad_config/protocol/macro_blob.py`

## Bank

`MACRO_BUILTIN_COUNT` = **5** (ids 0–4).

`MACRO_MAX_STEPS` = **24**

`MACRO_BLOB_V1_SIZE` = **162**  
`= 16 (name) + 1 (step_count) + 1 (reserved) + 24 × 6 (steps)`

`MACRO_BANK_BLOB_SIZE` = **810** (`5 × 162`)

## Per-macro layout (little-endian)

| Offset | Size | Field |
|--------|------|-------|
| 0 | 16 | `name` — ASCII, NUL-padded |
| 16 | 1 | `step_count` — `1..MACRO_MAX_STEPS`, must include a final `END` (host/firmware append `END` if missing) |
| 17 | 1 | `reserved` — always `0` |
| 18 | 144 | `steps[MACRO_MAX_STEPS]` — 24 × step (6 bytes each); unused slots **zeroed** |

### Step (6 bytes)

| Off | Size | Field |
|-----|------|-------|
| 0 | 1 | `op` — `macro_op_t` (END=0, KEY_DOWN=1, KEY_UP=2, TAP=3, DELAY_MS=4, TEXT=5, CONSUMER=6) |
| 1 | 1 | `mods` — keyboard modifier bitmap |
| 2 | 1 | `keycode` — HID keycode (`0` = none / release-all for KEY_UP) |
| 3 | 1 | `pad` — always `0` |
| 4 | 2 | `arg` — delay_ms / text_id / consumer usage, little-endian |

### Modifier bits

| Bit | Meaning |
|-----|---------|
| 0x01 | Left Ctrl |
| 0x02 | Left Shift |
| 0x04 | Left Alt |
| 0x08 | Left GUI |

## CRC

USB `MACRO_BEGIN` carries `blob_crc32` = IEEE CRC32 of the **162** blob bytes
(same polynomial as frame CRC in `PROTOCOL.md`).

## Ops (host JSON ↔ wire)

| JSON `op` | Wire |
|-----------|------|
| `END` | 0 |
| `KEY_DOWN` | 1 |
| `KEY_UP` | 2 |
| `TAP` | 3 |
| `DELAY_MS` | 4 |
| `TEXT` | 5 |
| `CONSUMER` | 6 |

Host JSON key tokens and mod names reuse the profile blob mapping
(`key_name_to_hid` / `mods_to_bitmap`).
