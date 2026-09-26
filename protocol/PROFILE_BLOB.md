# Profile binary blob v1

Shared wire format for one profile slot. **Do not** `memcpy` a host or firmware
`profile_t` across the USB link — packing is field-by-field, little-endian, with
**no C struct padding**.

Constants are mirrored in:

- Firmware: `firmware/include/profile_blob.h`
- Host: `configurator/macropad_config/protocol/profile_blob.py`

## Size

`PROFILE_BLOB_V1_SIZE` = **148** bytes.

## Layout (little-endian)

| Offset | Size | Field |
|--------|------|-------|
| 0 | 2 | `schema_version` (u16) — must be `1` |
| 2 | 16 | `id` — ASCII, NUL-padded |
| 18 | 16 | `name` — ASCII, NUL-padded |
| 34 | 72 | `keys[12]` — 12 × action (6 bytes each) |
| 106 | 24 | `encoder` — cw, ccw, press, long_press (4 × action) |
| 130 | 16 | `oled.title` — ASCII, NUL-padded |
| 146 | 1 | `oled.animation` (`0` static, `1` scroll, `2` matrix) |
| 147 | 1 | `pad` — always `0` |

### Action (6 bytes)

| Off | Size | Field |
|-----|------|-------|
| 0 | 1 | `type` — `action_type_t` (DISABLED=0 … PROFILE=9) |
| 1 | 1 | `mods` — keyboard modifier bitmap |
| 2 | 1 | `keycode` — HID keycode |
| 3 | 1 | `aux` — volume dir / profile slot / text_id / macro_id |
| 4 | 2 | `usage` — consumer usage (MEDIA), little-endian |

Host JSON uses 1-based key indices `"1"`…`"12"`; the blob stores them in order at
indices 0…11.

### Modifier bits

| Bit | Meaning |
|-----|---------|
| 0x01 | Left Ctrl |
| 0x02 | Left Shift |
| 0x04 | Left Alt |
| 0x08 | Left GUI |

### Volume `aux`

`1` = up, `2` = down, `3` = mute.

## CRC

USB `PROFILE_BEGIN` carries `blob_crc32` = IEEE CRC32 of the **148** blob bytes
(same polynomial as frame CRC in `PROTOCOL.md`).
