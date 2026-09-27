# Macropad USB Config Protocol (v1)

Step 15 — framing + PING / GET_INFO / ECHO over a **second HID interface**.
Step 16 — flash-backed profile slots + chunked **profile upload**.
Step 17 — flash-backed **macro bank** sync + light protocol polish.
Step 18 — host **auto app-switch** via `SET_ACTIVE`.
Step 19 — architecture hardening: debounced active persist + `SAVE_ALL`.
Step 23 — HIL test tooling + `PROFILE_READ` / `MACRO_READ` readback (`FW_VERSION` 0.23, host 0.23.0). See [`../docs/VERSIONING.md`](../docs/VERSIONING.md).
**Steps 14–20 are complete.**

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
| `0x15` | PROFILE_READ | `slot u8`, `offset u16 LE` | `slot`, `offset u16 LE`, up to **48** blob bytes (fw 0.23+) |
| `0x20` | MACRO_BEGIN | `id u8`, `total_len u16 LE`, `blob_crc32 u32 LE` | empty OK |
| `0x21` | MACRO_DATA | `offset u16 LE` + raw bytes (≤50) | empty OK |
| `0x22` | MACRO_COMMIT | empty | empty OK (after CRC + replace RAM + flash) |
| `0x23` | MACRO_ABORT | empty | empty OK |
| `0x24` | MACRO_GET | `id u8` | `id`, `len u16 LE`, `crc32 u32 LE` (metadata only) |
| `0x25` | MACRO_READ | `id u8`, `offset u16 LE` | `id`, `offset u16 LE`, up to **48** blob bytes (fw 0.23+) |
| `0x30` | SET_ACTIVE | `slot u8` | empty OK (RAM + OLED; **debounced** flash persist) |
| `0x31` | GET_ACTIVE | empty | `slot u8` (optional; GET_INFO also reports it) |
| `0x32` | SAVE_ALL | empty | empty OK (immediate full storage rewrite) |
| `0x7F` | NAK | — | device reply only; `payload[0]` = err |

### GET_INFO payload (14 bytes)

| Off | Type | Field |
|-----|------|-------|
| 0 | u8 | `fw_major` (`0`) |
| 1 | u8 | `fw_minor` (Step *N* → *N*, e.g. `23`) |
| 2 | u8 | `proto_ver` (`1`) |
| 3 | u8 | `active_slot` |
| 4 | u8 | `slot_count` |
| 5 | u8 | `flags` — **bit0** flash storage, **bit1** macro bank present, **bit2** readback (`PROFILE_READ`/`MACRO_READ`, fw 0.23+) |
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

`PROFILE_GET` returns metadata only (`slot`, `len`, `crc`).

### Readback (Step 23)

`PROFILE_READ` (`0x15`) / `MACRO_READ` (`0x25`) return the **packed RAM blob**
(the same bytes `PROFILE_GET` / `MACRO_GET` CRC over) in windows of up to
`CFG_READ_CHUNK_MAX = 48` bytes: request `id u8, offset u16 LE`; response
`id, offset, data[min(48, size - offset)]`. `offset >= size`, bad id, or a
payload shorter than 3 bytes → NAK `EINVAL`. No flash I/O; allowed while an
upload is staged. Host: `ConfigDevice.profile_read()` / `macro_read()`
(3 / 4 requests per blob). Older firmware answers `EINVAL` (unknown cmd) —
gate on GET_INFO flags bit2 or `version.fw_supports_readback()`.

The blob read back is the firmware's canonical form (unpack → RAM → pack):
names get a NUL forced at byte 15, profile pad byte = 0, macro steps are
truncated after the first `END` (or `END` appended), step pad bytes = 0.
Host packers emit the same canonical form, so an uploaded blob reads back
byte-identical.

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

### SET_ACTIVE / GET_ACTIVE (Step 18) + debounced persist (Step 19)

Host-driven profile switch for auto app-switch:

1. Host matches foreground process → profile / slot (see [`../autoswitch/SCHEMA.md`](../autoswitch/SCHEMA.md)).
2. `SET_ACTIVE` with `slot` `0..4`.
3. Device calls `profiles_set_active(slot)`, updates OLED idle title + toast,
   prints UART `cfg set_active N`. If the on-device profile menu is open, the
   menu is exited to idle after applying.
4. Empty OK response. Bad slot → NAK `EINVAL`.
5. **Upload busy:** `SET_ACTIVE` remains OK (RAM only); staging is not disturbed.

**Flash policy (Step 19):** `SET_ACTIVE` does **not** erase/program flash
immediately. The device schedules a debounced rewrite of the full storage image
(profiles + macros + new `active_slot` already in RAM). If no new `SET_ACTIVE`
arrives for ~4 seconds (`STORAGE_ACTIVE_DEBOUNCE_MS`), one sector rewrite runs.
Repeated switches cancel and reschedule the quiet window. UART:
`stor debounce save` then `stor save ok|fail`.

**Step 23:** when the quiet window expires and flash already holds a valid v2
image that matches RAM (last load/save succeeded) with the same `active_slot`,
the rewrite is skipped (`stor debounce skip (unchanged)`). Switching away and
back — as autoswitch and the HIL suite do — no longer costs a sector write.

`GET_ACTIVE` returns the current RAM slot as a single `u8` (optional convenience;
`GET_INFO.active_slot` is equivalent).

Auto-switch requires the **configurator** (or another host agent) to be running —
the device cannot observe host applications.

### SAVE_ALL (Step 19)

`CFG_CMD_SAVE_ALL = 0x32`, empty payload.

1. If profile or macro upload is in progress → NAK `EBUSY`.
2. Cancels any pending debounced active persist.
3. Calls `storage_save_all()` (full v2 image: profiles + macros + `active_slot`).
4. Empty OK on success; NAK `EBUSY` if the flash program fails.

Host Device menu **Save device state** uses this for an explicit save without
waiting for the debounce timer.

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
| 3 | `ENOSYS` | reserved — **not emitted** by v1 firmware (unknown cmds get `EINVAL`) |
| 4 | `EBUSY` | upload already in progress (profile **or** macro) / flash program failed / SAVE_ALL while busy |

Unknown `cmd` → NAK `EINVAL`. Bad magic/CRC → NAK `EBADMSG` when possible.

Validation order: magic (`EBADMSG`) → version (`EINVAL`) → length > 52
(`EINVAL`) → CRC (`EBADMSG`). NAKs echo the request `seq`. A host frame with
the **response** flag set is silently ignored (no reply). An OUT report shorter
than 64 bytes (but ≥ 6) → NAK `EBADMSG`.

**seq** is echo-only: the device never validates or tracks it, so there is no
"bad seq" NAK. The host (`ConfigDevice.transact`) rejects replies whose `seq`
differs from the request.

## Firmware hooks

- `firmware/include/config_protocol.h` — constants + frame helpers
- `firmware/src/config_protocol.c` — CRC, validate, dispatch, deferred TX
- `firmware/src/storage.c` — flash sector v2 + profile/macro upload staging
- `firmware/src/profile_blob.c` / `macro_blob.c` — pack/unpack wire ↔ RAM
- `firmware/src/macros.c` — factory defaults + RAM working set + playback
- HID instance **1** OUT → `config_protocol_on_host_report`

UART: `cfg ping`, `cfg info`, `cfg echo`, `cfg nak`, `cfg profile …`,
`cfg macro …`, `cfg set_active N`, `cfg get_active N`, `cfg save_all ok`,
`stor load v2|v1|default`, `stor save ok|fail`, `stor debounce save`,
`profile save ok`, `macro save ok`.

## Host library

- `configurator/macropad_config/protocol/frames.py` — pack/unpack + CRC
- `configurator/macropad_config/protocol/profile_blob.py` — JSON ↔ profile blob
- `configurator/macropad_config/protocol/macro_blob.py` — library ↔ macro blob
- `configurator/macropad_config/protocol/device.py` — hidapi + shared chunked upload
- `configurator/scripts/smoke_protocol.py` / `smoke_storage.py` /
  `smoke_macros_blob.py` / `smoke_autoswitch.py` — no hardware
- `autoswitch/rules.json` + `configurator/macropad_config/autoswitch/` — host matcher
- `docs/ARCHITECTURE.md` — layers, data flows, flash vs RAM
- `configurator/scripts/run_all_smokes.py` — aggregate smoke runner
- `configurator/scripts/hil_test.py` + `macropad_config/hil/` — hardware-in-the-loop
  suite; `--mock` runs it against an in-process firmware model (`hil/mock.py`)

## Deferred (later)

- Step 20 testing / versioning polish
- Step 21 changelog, host-smokes CI, release polish
- Step 22 verified firmware build (SDK 2.1.1) + CI UF2 artifact
- Step 23 HIL tooling + PROFILE_READ / MACRO_READ (was: "full download streaming")
