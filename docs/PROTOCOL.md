# Macropad USB Config Protocol (v1)

Current: firmware **0.25**, host **0.25.0**, `proto_ver` **1**. Versioning rules:
[`VERSIONING.md`](VERSIONING.md); animation format: [`ANIMATION.md`](ANIMATION.md).

| Since fw | Added |
|----------|-------|
| 0.15 | framing + `PING` / `GET_INFO` / `ECHO` over a **second HID interface** |
| 0.16 | flash-backed profile slots + chunked **profile upload** |
| 0.17 | flash-backed **macro bank** sync |
| 0.18 | host **auto app-switch** via `SET_ACTIVE` |
| 0.19 | debounced active-slot persist + `SAVE_ALL` |
| 0.23 | `PROFILE_READ` / `MACRO_READ` readback (GET_INFO flags bit2) |
| 0.25 | **OLED idle animation** commands `0x40`–`0x48`, GET_INFO flags bit3, storage v3 |

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
| `0x40` | ANIM_BEGIN | `total_len u32 LE`, `blob_crc32 u32 LE` | empty OK (fw 0.25+) |
| `0x41` | ANIM_DATA | `offset u32 LE` (sequential) + ≤ **48** bytes | empty OK |
| `0x42` | ANIM_COMMIT | empty | empty OK (after flash CRC + structure check) |
| `0x43` | ANIM_ABORT | empty | empty OK (idempotent) |
| `0x44` | ANIM_INFO | empty | 40-byte status (below) |
| `0x45` | ANIM_READ | `offset u32 LE` | `offset u32 LE` + ≤ **48** bytes of the flash region |
| `0x46` | ANIM_SETTINGS_GET | empty | 8-byte idle settings block |
| `0x47` | ANIM_SETTINGS_SET | 8-byte idle settings block | same block (after MPFL rewrite) |
| `0x48` | ANIM_PREVIEW | `mode u8`: 0 stop, 1 play stored (built-in if none), 2 built-in, 3 blank | `mode u8` |
| `0x7F` | NAK | — | device reply only; `payload[0]` = err |

### GET_INFO payload (14 bytes)

| Off | Type | Field |
|-----|------|-------|
| 0 | u8 | `fw_major` (`0`) |
| 1 | u8 | `fw_minor` (Step *N* → *N*, e.g. `23`) |
| 2 | u8 | `proto_ver` (`1`) |
| 3 | u8 | `active_slot` |
| 4 | u8 | `slot_count` |
| 5 | u8 | `flags` — **bit0** flash storage, **bit1** macro bank present, **bit2** readback (`PROFILE_READ`/`MACRO_READ`, fw 0.23+), **bit3** OLED idle animation (`0x40`–`0x48`, fw 0.25+) |
| 6..13 | 8 bytes | product tag ASCII, e.g. `MACROPAD` (no NUL required) |

### Profile upload (fw 0.16+)

1. Host packs JSON → `profile_blob_v1` (148 bytes). See [`PROFILE_BLOB.md`](PROFILE_BLOB.md).
2. `PROFILE_BEGIN` with destination slot `0..4`, `total_len=148`, CRC32 of the blob.
3. One or more `PROFILE_DATA` chunks: `offset` + up to **50** payload bytes
   (`CFG_PAYLOAD_MAX - 2`).
4. `PROFILE_COMMIT` — device verifies assembled CRC, unpacks into RAM slot,
   writes the flash image (profiles **and** macros), ACK empty. OLED title
   refreshes if the active slot changed in RAM.
5. `PROFILE_ABORT` discards the staging buffer at any time before COMMIT.

`PROFILE_GET` returns metadata only (`slot`, `len`, `crc`).

### Readback (fw 0.23+)

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

### Macro upload (fw 0.17+)

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

### SET_ACTIVE / GET_ACTIVE (fw 0.18+) + debounced persist (fw 0.19+)

Host-driven profile switch for auto app-switch:

1. Host matches foreground process → profile / slot (see [`../autoswitch/SCHEMA.md`](../autoswitch/SCHEMA.md)).
2. `SET_ACTIVE` with `slot` `0..4`.
3. Device calls `profiles_set_active(slot)`, updates OLED idle title + toast,
   prints UART `cfg set_active N`. If the on-device profile menu is open, the
   menu is exited to idle after applying.
4. Empty OK response. Bad slot → NAK `EINVAL`.
5. **Upload busy:** `SET_ACTIVE` remains OK (RAM only); staging is not disturbed.

**Flash policy (fw 0.19+):** `SET_ACTIVE` does **not** erase/program flash
immediately. The device schedules a debounced rewrite of the full storage image
(profiles + macros + new `active_slot` already in RAM). If no new `SET_ACTIVE`
arrives for ~4 seconds (`STORAGE_ACTIVE_DEBOUNCE_MS`), one sector rewrite runs.
Repeated switches cancel and reschedule the quiet window. UART:
`stor debounce save` then `stor save ok|fail`.

**fw 0.23+:** when the quiet window expires and flash already holds a valid v2
image that matches RAM (last load/save succeeded) with the same `active_slot`,
the rewrite is skipped (`stor debounce skip (unchanged)`). Switching away and
back — as autoswitch and the HIL suite do — no longer costs a sector write.

`GET_ACTIVE` returns the current RAM slot as a single `u8` (optional convenience;
`GET_INFO.active_slot` is equivalent).

Auto-switch requires the **configurator** (or another host agent) to be running —
the device cannot observe host applications.

### SAVE_ALL (fw 0.19+)

`CFG_CMD_SAVE_ALL = 0x32`, empty payload.

1. If profile or macro upload is in progress → NAK `EBUSY`.
2. Cancels any pending debounced active persist.
3. Calls `storage_save_all()` (full v2 image: profiles + macros + `active_slot`).
4. Empty OK on success; NAK `EBUSY` if the flash program fails.

Host Device menu **Save device state** uses this for an explicit save without
waiting for the debounce timer.

### OLED idle animation (fw 0.25+)

Gate on GET_INFO flags **bit3** (`CFG_INFO_FLAG_ANIM`) or `version.fw_supports_anim()`;
older firmware answers these commands with `EINVAL` (unknown cmd). The blob format
(`MPAN` header + RAW / RLE / DELTA frame records) is specified in
[`../docs/ANIMATION.md`](ANIMATION.md); the host builds it with
`macropad_config.animation.codec.build_blob()`.

**Upload** — same BEGIN / DATA / COMMIT / ABORT shape as profiles and macros, but the
blob (32 … 131072 B) streams straight into the dedicated 128 KiB flash region at
`0x1DF000` instead of a RAM staging buffer:

1. `ANIM_BEGIN(total_len, crc32)` — `total_len` must be 36 … 131072 (`EINVAL`
   otherwise). `EBUSY` while a profile/macro/animation upload is open. Stops any
   playback (the normal UI returns).
2. `ANIM_DATA(offset, bytes≤48)` — **sequential only**: `offset` must equal the bytes
   received so far (`EINVAL` for gaps, replays, overruns or no BEGIN). Data is staged in
   a 4 KiB sector buffer; each time a sector fills it is erased + programmed through
   `flash_safe_execute()` (≈ 45–100 ms inside that DATA request — hosts use a 5 s
   timeout). Only the sectors the blob needs are erased. A flash failure → `EBUSY` +
   abort.
3. `ANIM_COMMIT` — incomplete → `EINVAL` (auto-abort). The last partial sector is
   flushed (0xFF padded), then the firmware CRCs `flash[0, total_len)` against the BEGIN
   CRC and runs the full structural validation (header CRC, data CRC, every record
   decodes to exactly 1024 B, frame 0 not DELTA). Failure → `EBADMSG` **and** sector 0
   is erased (no half-valid animation survives; the built-in starfield plays instead).
   Success → the new animation is active immediately. Worst case (full region) ≈ 0.2 s.
4. `ANIM_ABORT` — closes the upload. If a sector was already written, sector 0 is
   erased (built-in fallback); if not, the previous animation is untouched.

While an animation upload is open: `PROFILE_BEGIN`, `MACRO_BEGIN`, `SAVE_ALL`,
`ANIM_SETTINGS_SET`, `ANIM_READ` and `ANIM_PREVIEW` → `EBUSY`; `ANIM_BEGIN` while a
profile/macro upload is open → `EBUSY`.

**ANIM_INFO payload (40 bytes)**

| Off | Type | Field |
|-----|------|-------|
| 0 | u8 | status: bit0 stored animation valid, bit1 upload open, bit2 playing, bit3 display blanked, bit4 built-in playing, bit5 host preview active, bit6 region usable (image does not overlap) |
| 1 | u8 | blob format version (1) |
| 2 | u16 | stored frame_count (0 if none) |
| 4 | u8 | stored fps |
| 5 | u8 | stored flags (bit0 loop) |
| 6 | u32 | stored total_len (header + records) |
| 10 | u32 | CRC32 of the stored blob (`total_len` bytes) |
| 14 | u32 | region size (131072) |
| 18 | u16 | max frames if every frame were RAW (127) |
| 20 | u32 | last OLED frame push: I2C bus time µs |
| 24 | u32 | last OLED frame push: wall time µs (queued → done) |
| 28 | u32 | upload bytes received (while bit1) |
| 32 | 8 | stored name (ASCII, NUL padded) |

**Idle settings block (8 bytes)** — `enabled u8 (0/1)`, `flags u8 (0)`,
`idle_timeout_s u16` (0 = never start the animation), `blank_timeout_s u16` (0 = never
switch the display off), `reserved u16`. `ANIM_SETTINGS_SET` rejects `enabled > 1`
(`EINVAL`), applies the settings, restarts the idle clock and rewrites the MPFL sector
(v3) immediately; the reply echoes the stored block. Defaults: enabled, 60 s, 600 s.

**ANIM_READ** returns raw flash bytes of the region (host reads `total_len` from
ANIM_INFO first); `offset ≥ 131072` → `EINVAL`.

**ANIM_PREVIEW** plays regardless of the `enabled` flag and ignores the blank timeout
until any key/encoder input or `mode 0`.

Device behaviour: after `idle_timeout_s` without key / encoder input the stored
animation (built-in starfield if none) plays at its fps; any input wakes the normal UI
and the waking press/turn is swallowed (no HID report, no action). After
`blank_timeout_s` the SSD1306 is switched off (`0xAE`) — this also applies when the
animation is disabled.

### Flash image (storage v3)

Last 4 KiB sector, magic `MPFL`:

| Field | Notes |
|-------|-------|
| magic u32 | `MPFL` |
| version u16 | **3** (fw 0.25+; 2 before) |
| active_slot u8 | |
| flags u8 | |
| profile_blob[5][148] | |
| macro_blob[5][162] | new in v2 |
| anim_settings[8] | new in v3 (idle settings block above) |
| crc32 | of everything before crc |

v1 images (profiles only) still load; macros stay at factory defaults until the
next save upgrades the sector. v2 images load with default idle settings; every
save writes v3. The animation frames live in their own region (see
[`../docs/ARCHITECTURE.md`](ARCHITECTURE.md) flash map).

### Error codes (`NAK` payload[0])

| code | name | meaning |
|------|------|---------|
| 1 | `EINVAL` | bad version/length/unknown cmd / bad slot / incomplete upload |
| 2 | `EBADMSG` | bad magic or CRC (frame or blob) |
| 3 | `ENOSYS` | reserved — **not emitted** by v1 firmware (unknown cmds get `EINVAL`) |
| 4 | `EBUSY` | upload already in progress (profile, macro **or** animation) / flash program failed / SAVE_ALL / settings / preview while busy |

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
- `firmware/src/storage.c` — flash sector (MPFL v3) + profile/macro upload staging
- `firmware/src/profile_blob.c` / `macro_blob.c` — pack/unpack wire ↔ RAM
- `firmware/src/macros.c` — factory defaults + RAM working set + playback
- `firmware/src/anim.c` / `anim_codec.c` — idle state machine, animation region upload,
  playback, built-in starfield / blob validation + PackBits decode
- HID instance **1** OUT → `config_protocol_on_host_report`

UART: `cfg ping`, `cfg info`, `cfg echo`, `cfg nak`, `cfg profile …`,
`cfg macro …`, `cfg set_active N`, `cfg get_active N`, `cfg save_all ok`,
`stor load v2|v1|default`, `stor save ok|fail`, `stor debounce save`,
`profile save ok`, `macro save ok`, `anim upload begin|abort`, `anim commit ok|rejected`,
`anim play builtin|stored`, `anim wake`, `anim blank`, `stor load v3`.

## Host library

- `configurator/macropad_config/protocol/frames.py` — pack/unpack + CRC
- `configurator/macropad_config/protocol/profile_blob.py` — JSON ↔ profile blob
- `configurator/macropad_config/protocol/macro_blob.py` — library ↔ macro blob
- `configurator/macropad_config/protocol/device.py` — hidapi + shared chunked upload,
  `anim_upload` / `anim_download` / `anim_info` / `anim_settings_*` / `anim_preview`
- `configurator/macropad_config/animation/` — blob codec, presets, GIF import/export, projects
- `configurator/scripts/smoke_protocol.py` / `smoke_storage.py` /
  `smoke_macros_blob.py` / `smoke_autoswitch.py` — no hardware
- `autoswitch/rules.json` + `configurator/macropad_config/autoswitch/` — host matcher
- `docs/ARCHITECTURE.md` — layers, data flows, flash vs RAM
- `configurator/scripts/run_all_smokes.py` — aggregate smoke runner
- `configurator/scripts/hil_test.py` + `macropad_config/hil/` — hardware-in-the-loop
  suite; `--mock` runs it against an in-process firmware model (`hil/mock.py`)
