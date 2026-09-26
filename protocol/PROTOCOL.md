# Macropad USB Config Protocol (v1)

Step 15 — framing + PING / GET_INFO / ECHO over a **second HID interface**.
Step 16 — flash-backed profile slots + chunked **profile upload**.
Step 17 — flash-backed **macro bank** sync + light protocol polish.
**Steps 14–17 are complete.** Next: Step 18+ auto app-switch / polish.

## USB topology

| IF | Role | Endpoints | Report map |
|----|------|-----------|------------|
| 0 | Keyboard + Consumer | IN `0x81` | Report ID **1** keyboard, **2** consumer (unchanged) |
| 1 | Vendor config | OUT `0x02`, IN `0x82` | Usage Page **`0xFF00`**, Usage **`0x01`**, **64-byte** Input + Output, **no Report ID** |

- VID `0x2E8A`, PID `0xC001`
- TinyUSB: `CFG_TUD_HID=2`, `CFG_TUD_HID_EP_BUFSIZE=64`, `CFG_TUD_VENDOR=0`
- Host opens with **hidapi**, filter by VID/PID **and** usage page `0xFF00`

### Report ID on the wire (IF1)

The IF1 descriptor has **no** Report ID item. The 64-byte frame is the full interrupt report.

**hidapi note:** on many platforms `write()` still expects a leading report-id byte. Send **`0x00` + 64 frame bytes** (65 total). On `read()`, if the first byte is `0x00` and length is 65, strip it; if length is 64, use as-is.

## Frame layout (64 bytes, little-endian)

| Offset | Size | Field |
|--------|------|-------|
| 0 | 2 | `magic` = `0x4D50` (`'M''P'` → bytes `50 4D`) |
| 2 | 1 | `version` = `1` |
| 3 | 1 | `flags` — bit0 = **response** |
| 4 | 1 | `cmd` |
| 5 | 1 | `seq` (host-chosen; device echoes) |
| 6 | 2 | `length` — payload bytes used, `0..52` |
| 8 | 52 | `payload` (zero-padded) |
| 60 | 4 | `crc32` of bytes `[0..59]` |

### CRC32

IEEE / ISO-HDLC / zlib style:

- poly `0xEDB88320` (reflected)
- init `0xFFFFFFFF`
- xorout `0xFFFFFFFF`

Covers the first **60** bytes only; result stored little-endian at offset 60.

## Commands (v1)

| cmd | name | host→dev payload | response payload |
|-----|------|------------------|------------------|
| `0x01` | PING | empty | ASCII `PONG` (4 bytes) |
| `0x02` | GET_INFO | empty | see below |
| `0x03` | ECHO | N bytes (`N≤52`) | same bytes |
| `0x10` | PROFILE_BEGIN | `slot u8`, `total_len u16 LE`, `blob_crc32 u32 LE` | empty OK |
| `0x11` | PROFILE_DATA | `offset u16 LE` + raw bytes (≤50) | empty OK |
| `0x12` | PROFILE_COMMIT | empty | empty OK (after CRC + unpack + flash) |
| `0x13` | PROFILE_ABORT | empty | empty OK |
| `0x14` | PROFILE_GET | `slot u8` | `slot`, `len u16 LE`, `crc32 u32 LE` (metadata only) |
| `0x20` | MACRO_BEGIN | `id u8`, `total_len u16 LE`, `blob_crc32 u32 LE` | empty OK |
| `0x21` | MACRO_DATA | `offset u16 LE` + raw bytes (≤50) | empty OK |
| `0x22` | MACRO_COMMIT | empty | empty OK (after CRC + replace RAM + flash) |
| `0x23` | MACRO_ABORT | empty | empty OK |
| `0x24` | MACRO_GET | `id u8` | `id`, `len u16 LE`, `crc32 u32 LE` (metadata only) |
| `0x7F` | NAK | — | device reply only; `payload[0]` = err |

### GET_INFO payload (14 bytes)

| Off | Type | Field |
|-----|------|-------|
| 0 | u8 | `fw_major` (`0`) |
| 1 | u8 | `fw_minor` (Step 17 → `17`) |
| 2 | u8 | `proto_ver` (`1`) |
| 3 | u8 | `active_slot` |
| 4 | u8 | `slot_count` |
| 5 | u8 | `flags` — **bit0** flash storage, **bit1** macro bank present |
| 6..13 | 8 bytes | product tag ASCII, e.g. `MACROPAD` (no NUL required) |

### Profile upload (Step 16)

1. Host packs JSON → `profile_blob_v1` (148 bytes). See [`PROFILE_BLOB.md`](PROFILE_BLOB.md).
2. `PROFILE_BEGIN` with destination slot `0..4`, `total_len=148`, CRC32 of the blob.
3. One or more `PROFILE_DATA` chunks: `offset` + up to **50** payload bytes
   (`CFG_PAYLOAD_MAX - 2`).
4. `PROFILE_COMMIT` — device verifies assembled CRC, unpacks into RAM slot,
   writes the flash image (profiles **and** macros), ACK empty. OLED title
   refreshes if the active slot changed in RAM.
5. `PROFILE_ABORT` discards the staging buffer at any time before COMMIT.

`PROFILE_GET` returns metadata only (`slot`, `len`, `crc`) — full download is
deferred.

### Macro upload (Step 17)

Same chunked flow as profiles:

1. Host packs `macros/library.json` entry → `macro_blob_v1` (**162** bytes).
   See [`MACRO_BLOB.md`](MACRO_BLOB.md).
2. `MACRO_BEGIN` with id `0..4`, `total_len=162`, CRC32 of the blob.
3. `MACRO_DATA` chunks (offset + ≤50 bytes).
4. `MACRO_COMMIT` — verify CRC, replace RAM working-set slot (aborts playback
   if that id is running), `storage_save_all` (full v2 image), ACK.
5. `MACRO_ABORT` discards staging.

`MACRO_GET` returns metadata only (`id`, `len`, `crc`).

**Busy mutex:** profile upload and macro upload are mutually exclusive — starting
one while the other is active yields NAK `EBUSY`.

### Flash image (storage v2)

Last 4 KiB sector, magic `MPFL`:

| Field | Notes |
|-------|-------|
| magic u32 | `MPFL` |
| version u16 | **2** |
| active_slot u8 | |
| flags u8 | |
| profile_blob[5][148] | |
| macro_blob[5][162] | new in v2 |
| crc32 | of everything before crc |

v1 images (profiles only) still load; macros stay at factory defaults until the
next save upgrades the sector to v2.

### Error codes (`NAK` payload[0])

| code | name | meaning |
|------|------|---------|
| 1 | `EINVAL` | bad version/length/unknown cmd / bad slot / incomplete upload |
| 2 | `EBADMSG` | bad magic or CRC (frame or blob) |
| 3 | `ENOSYS` | unimplemented cmd |
| 4 | `EBUSY` | upload already in progress (profile **or** macro) / flash program failed |

Unknown `cmd` → NAK `EINVAL`. Bad magic/CRC → NAK `EBADMSG` when possible.

## Firmware hooks

- `firmware/include/config_protocol.h` — constants + frame helpers
- `firmware/src/config_protocol.c` — CRC, validate, dispatch, deferred TX
- `firmware/src/storage.c` — flash sector v2 + profile/macro upload staging
- `firmware/src/profile_blob.c` / `macro_blob.c` — pack/unpack wire ↔ RAM
- `firmware/src/macros.c` — factory defaults + RAM working set + playback
- HID instance **1** OUT → `config_protocol_on_host_report`

UART: `cfg ping`, `cfg info`, `cfg echo`, `cfg nak`, `cfg profile …`,
`cfg macro …`, `stor load v2|v1|default`, `stor save ok|fail`,
`profile save ok`, `macro save ok`.

## Host library

- `configurator/macropad_config/protocol/frames.py` — pack/unpack + CRC
- `configurator/macropad_config/protocol/profile_blob.py` — JSON ↔ profile blob
- `configurator/macropad_config/protocol/macro_blob.py` — library ↔ macro blob
- `configurator/macropad_config/protocol/device.py` — hidapi + shared chunked upload
- `configurator/scripts/smoke_protocol.py` / `smoke_storage.py` /
  `smoke_macros_blob.py` — no hardware

## Deferred (Step 18+)

- Auto app-switching / focus detection
- Full profile/macro download streaming
- Further polish
