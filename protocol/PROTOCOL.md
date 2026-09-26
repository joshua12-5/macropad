# Macropad USB Config Protocol (v1)

Step 15 — framing + PING / GET_INFO / ECHO over a **second HID interface**.
Profile/macro binary upload is **Step 16+** (not defined here beyond reserved cmds).

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
| `0x7F` | NAK | — | device reply only; `payload[0]` = err |

### GET_INFO payload (14 bytes)

| Off | Type | Field |
|-----|------|-------|
| 0 | u8 | `fw_major` (Step 15 → `0`) |
| 1 | u8 | `fw_minor` (Step 15 → `15`) |
| 2 | u8 | `proto_ver` (`1`) |
| 3 | u8 | `active_slot` |
| 4 | u8 | `slot_count` |
| 5 | u8 | `flags` (0 for now) |
| 6..13 | 8 bytes | product tag ASCII, e.g. `MACROPAD` (no NUL required) |

### Error codes (`NAK` payload[0])

| code | name | meaning |
|------|------|---------|
| 1 | `EINVAL` | bad version/length/unknown cmd |
| 2 | `EBADMSG` | bad magic or CRC |
| 3 | `ENOSYS` | reserved (unimplemented cmd in later steps) |
| 4 | `EBUSY` | reserved |

Unknown `cmd` → response with `flags.response`, `cmd=0x7F`, err=`EINVAL`.
Bad magic/CRC → NAK with `EBADMSG` when possible.

## Firmware hooks

- `firmware/include/config_protocol.h` — constants + `cfg_frame_t`
- `firmware/src/config_protocol.c` — CRC, validate, dispatch, deferred TX
- HID instance **1** OUT → `config_protocol_on_host_report`; response via `tud_hid_n_report(1, 0, …)`

UART: `cfg ping`, `cfg info`, `cfg echo`, `cfg nak`.

## Host library

- `configurator/macropad_config/protocol/frames.py` — pack/unpack + CRC
- `configurator/macropad_config/protocol/device.py` — hidapi open/send/recv (optional)
- `configurator/scripts/smoke_protocol.py` — frame unit tests (no hardware)

## Deferred (Step 16+)

- Flash storage of profiles / macros
- Binary profile upload / download commands
- Device menu **Upload to device**
