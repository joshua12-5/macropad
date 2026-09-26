# Macropad USB Config Protocol (v1)

Step 15 — framing + PING / GET_INFO / ECHO over a **second HID interface**.
Step 16 — flash-backed profile slots + chunked **profile upload** (BEGIN / DATA /
COMMIT / ABORT). Full **macro-bank** flash sync is **Step 17** (MACRO_* cmds
return `ENOSYS`).

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
| `0x20`–`0x23` | MACRO_* | — | **NAK `ENOSYS`** (Step 17) |
| `0x7F` | NAK | — | device reply only; `payload[0]` = err |

### GET_INFO payload (14 bytes)

| Off | Type | Field |
|-----|------|-------|
| 0 | u8 | `fw_major` (`0`) |
| 1 | u8 | `fw_minor` (Step 16 → `16`) |
| 2 | u8 | `proto_ver` (`1`) |
| 3 | u8 | `active_slot` |
| 4 | u8 | `slot_count` |
| 5 | u8 | `flags` — **bit0** = flash profile storage present |
| 6..13 | 8 bytes | product tag ASCII, e.g. `MACROPAD` (no NUL required) |

### Profile upload (Step 16)

1. Host packs JSON → `profile_blob_v1` (148 bytes). See [`PROFILE_BLOB.md`](PROFILE_BLOB.md).
2. `PROFILE_BEGIN` with destination slot `0..4`, `total_len=148`, CRC32 of the blob.
3. One or more `PROFILE_DATA` chunks: `offset` + up to **50** payload bytes
   (`CFG_PAYLOAD_MAX - 2`).
4. `PROFILE_COMMIT` — device verifies assembled CRC, unpacks into RAM slot,
   writes the flash image, ACK empty. OLED title refreshes if the active slot
   changed in RAM.
5. `PROFILE_ABORT` discards the staging buffer at any time before COMMIT.

`PROFILE_GET` returns metadata only (`slot`, `len`, `crc`) — full download is
deferred.

### Error codes (`NAK` payload[0])

| code | name | meaning |
|------|------|---------|
| 1 | `EINVAL` | bad version/length/unknown cmd / bad slot / incomplete upload |
| 2 | `EBADMSG` | bad magic or CRC (frame or profile blob) |
| 3 | `ENOSYS` | MACRO_* (Step 17) or other unimplemented cmd |
| 4 | `EBUSY` | upload already in progress / flash program failed |

Unknown `cmd` → NAK `EINVAL`. Bad magic/CRC → NAK `EBADMSG` when possible.

## Firmware hooks

- `firmware/include/config_protocol.h` — constants + frame helpers
- `firmware/src/config_protocol.c` — CRC, validate, dispatch, deferred TX
- `firmware/src/storage.c` — flash sector + upload staging
- `firmware/src/profile_blob.c` — pack/unpack wire blob ↔ `profile_t`
- HID instance **1** OUT → `config_protocol_on_host_report`

UART: `cfg ping`, `cfg info`, `cfg echo`, `cfg nak`, `cfg profile …`,
`stor load ok|default`, `stor save ok|fail`.

## Host library

- `configurator/macropad_config/protocol/frames.py` — pack/unpack + CRC
- `configurator/macropad_config/protocol/profile_blob.py` — JSON ↔ blob
- `configurator/macropad_config/protocol/device.py` — hidapi + `upload_profile`
- `configurator/scripts/smoke_protocol.py` / `smoke_storage.py` — no hardware

## Deferred (Step 17)

- Macro-bank flash sync (`MACRO_BEGIN` / `DATA` / `COMMIT` / `ABORT`)
- Full profile download streaming
- Polish / auto app-switch (out of scope here)
