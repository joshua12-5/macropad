# Macropad architecture

Overview of the shipping stack (firmware 0.25, configurator 0.25.0): firmware, host app,
protocol, storage, testing and release tooling. The PCB / enclosure are not in this repo yet.

## Layers

```
┌─────────────────────────────────────────────────────────────────┐
│ Host configurator (PySide6) + autoswitch service                │
│   profiles/*.json · macros/library.json · autoswitch/rules.json │
└────────────────────────────┬────────────────────────────────────┘
                             │ USB vendor HID (IF1, 0xFF00)
                             │ framed protocol v1 (64 B)
┌────────────────────────────▼────────────────────────────────────┐
│ USB HID + config protocol                                       │
│   IF0: keyboard + consumer   IF1: config (PING…SAVE_ALL)        │
├─────────────────────────────────────────────────────────────────┤
│ Actions / macros / profiles (RAM working set)                   │
│   profile slots[5] · macro bank[5] · active_slot · engines      │
├─────────────────────────────────────────────────────────────────┤
│ Matrix / encoder / OLED UI / idle animation                     │
│   3×4 scan · EC11 · SSD1306 toasts / profile select / anim      │
├─────────────────────────────────────────────────────────────────┤
│ Hardware pinout (frozen)                                        │
│   board_pins.h → rows/cols, ENC A/B/SW, I2C OLED, UART          │
├─────────────────────────────────────────────────────────────────┤
│ Flash: MPFL v3 (last 4 KiB) + animation region (128 KiB below)  │
│   active_slot + 5×profile + 5×macro + idle settings · MPAN blob │
└─────────────────────────────────────────────────────────────────┘
```

| Layer | Code | Notes |
|-------|------|--------|
| Pinout | `firmware/include/board_pins.h` | GP8–10 rows, GP11–14 cols, GP2/3/15 encoder, GP4/5 OLED |
| Scan / input | `matrix.c`, `encoder.c` | Debounced matrix events; encoder CW/CCW/press |
| Display | `oled_*.c`, `anim*.c` | Idle title, key toast, on-device profile select, idle animation / blanking |
| Profiles / actions | `profiles.c`, `actions.c`, `macros.c` | RAM slots; TEXT/URL/APP/MACRO/KEY/… |
| USB + protocol | `usb_*.c`, `config_protocol.c` | TinyUSB; `tud_task` via `usb_hid_task` unchanged |
| Flash | `storage.c`, `anim.c` | MPFL v3 image; upload staging; debounced active persist; animation region |
| Host | `configurator/macropad_config/` | Editors, animation editor, Device menu, autoswitch, HIL suite |

## Data flows

### Key press (device)

1. `matrix_task` → press event for key 1–12.
2. If profile-select menu is open → event muted.
3. OLED toast; for non-KEY/SHORTCUT types → `actions_fire`.
4. KEY/SHORTCUT holds feed `usb_hid_update_from_matrix` when idle (not busy / not in menu).
5. Action engine may queue TEXT/URL/APP or start `macros` playback → HID reports on IF0.

### Profile upload (host → device)

1. Host packs JSON → `profile_blob_v1` (148 B). See [`PROFILE_BLOB.md`](PROFILE_BLOB.md).
2. `PROFILE_BEGIN` / `DATA` / `COMMIT` over IF1.
3. Device stages in RAM, CRC-checks, `profiles_write_slot`, then **`storage_save_all`** (full v2 sector).
4. OLED title refreshes if the active slot’s blob changed.
5. Overlapping profile **or** macro upload → NAK `EBUSY`.

### Macro upload (host → device)

1. Host packs library entry → `macro_blob_v1` (162 B). See [`MACRO_BLOB.md`](MACRO_BLOB.md).
2. Same chunked BEGIN/DATA/COMMIT; replaces RAM macro slot (aborts playback if running).
3. COMMIT calls **`storage_save_all`**. Mutually exclusive with profile upload.

### Auto-switch `SET_ACTIVE` (0x30)

1. Host autoswitch matches foreground process → slot (see [`../autoswitch/SCHEMA.md`](../autoswitch/SCHEMA.md)).
2. `SET_ACTIVE` → `profiles_set_active` + OLED toast (**immediate RAM**).
3. OK even while an upload is busy (staging untouched).
4. Schedules a **debounced** flash rewrite (~4 s quiet). Repeated switches cancel/reschedule. UART: `stor debounce save` then `stor save ok|fail`.
5. Immediate rewrite: `SAVE_ALL` (`0x32`) from Device → Save device state.

## Flash vs RAM

| What | Where | Lifetime |
|------|--------|----------|
| Active profile index | RAM (`profiles`) + flash header `active_slot` | Boot loads flash; SET_ACTIVE updates RAM then debounced flash |
| Profile blobs (5) | RAM + flash | Upload COMMIT / SAVE_ALL / debounce rewrite |
| Idle settings (enabled, timeouts) | RAM + flash (MPFL v3) | ANIM_SETTINGS_SET / any storage rewrite |
| Idle animation blob | flash region `0x1DF000` only | ANIM_COMMIT; decoded frame-by-frame into RAM |
| Macro bank (5) | RAM + flash (v2+) | Same; v1 flash keeps factory macros until next save |
| Upload staging buffer | RAM only | Cleared on COMMIT/ABORT |
| Matrix / encoder / OLED / HID state | RAM | Ephemeral |
| Host JSON / rules | Host disk | Source of truth for editors; device holds packed copies |

Flash wear policy: never erase on every auto-switch. Debounce coalesces rapid `SET_ACTIVE`; uploads and `SAVE_ALL` rewrite once intentionally.

## Protocol references

- Wire commands & framing: [`PROTOCOL.md`](PROTOCOL.md)
- Profile binary: [`PROFILE_BLOB.md`](PROFILE_BLOB.md)
- Macro binary: [`MACRO_BLOB.md`](MACRO_BLOB.md)
- Autoswitch rules: [`../autoswitch/SCHEMA.md`](../autoswitch/SCHEMA.md)

## Idle animation

- `anim.c`: ACTIVE → PLAYING (after `idle_timeout_s`) → BLANK (after `blank_timeout_s`); any
  key / encoder input wakes and is swallowed (`usb_hid_suppress_key`; a waking encoder press marks
  the long-press as consumed). Built-in starfield when nothing is stored.
- `oled_driver.c` streams the framebuffer non-blockingly (`oled_driver_task()`, ≤ 2 × 16-byte
  I2C chunks per 1 ms tick ≈ 0.81 ms; a full 1 KiB frame ≈ 26 ms bus time over ~33 ticks).
- Protocol `0x40`–`0x48`, GET_INFO flags bit3; blob format + authoring in
  [`ANIMATION.md`](ANIMATION.md). Host: `macropad_config/animation/` + `widgets/anim_editor.py`.

## Testing and CI

- Host smokes (`configurator/scripts/run_all_smokes.py`) + `ruff check` / `ruff format --check`
  in [`smokes.yml`](../.github/workflows/smokes.yml); firmware build + size / flash-map check in
  [`firmware.yml`](../.github/workflows/firmware.yml) (Pico SDK 2.1.1, zero warnings).
- HIL: `configurator/scripts/hil_test.py` → `macropad_config/hil/` (suite, CLI, mock). `--mock`
  runs the whole suite against a Python model of `config_protocol.c` / `storage.c` / `anim.c`.
  Manual checklist: [`HARDWARE_TEST.md`](HARDWARE_TEST.md).

## Release packaging

- `release.yml` on tag `vX.Y.Z`: version / changelog gate (`packaging/release_tools.py`) →
  firmware (reusable `firmware.yml`) + PyInstaller one-dir matrix (Windows x64, macOS arm64,
  macOS x86_64 experimental, Linux x86_64 on Ubuntu 22.04 for glibc 2.35) → headless
  `--self-test` per package → GitHub prerelease with `SHA256SUMS.txt`; manual run = dry run.
- `macropad_config/paths.py`: frozen builds read bundled defaults from `<bundle>/data`, user data
  in the OS per-user dir (seeded once). Details: [`RELEASE.md`](RELEASE.md),
  versions: [`VERSIONING.md`](VERSIONING.md).

## Flash map

2 MiB W25Q16 on the RP2040-Zero, XIP base `0x10000000`:

| Flash offset | XIP address | Size | Content |
|--------------|-------------|------|---------|
| `0x000000` – image end | `0x10000000` – | ≈ 64 KiB today (UF2 128 KiB incl. boot2) | firmware image (`__flash_binary_end` = `0x1000FF58` with gcc 14.2) |
| image end – `0x1DEFFF` | | ≈ 1.8 MiB | free (headroom checked in CI) |
| `0x1DF000` – `0x1FEFFF` | `0x101DF000` | 128 KiB (32 sectors) | **animation region** (`ANIM_REGION_OFFSET`): `MPAN` blob, sector 0 holds the header |
| `0x1FF000` – `0x1FFFFF` | `0x101FF000` | 4 KiB | **MPFL storage** v3: active slot, 5 profiles, 5 macros, idle settings |

- `anim.c` static-asserts that the region ends exactly at the MPFL sector and is sector aligned;
  at boot it compares `&__flash_binary_end` with the region start and disables stored animations
  (built-in only, ANIM_INFO bit6 clear) if a future image ever grew into it.
- `firmware.yml` fails the build when `__flash_binary_end` > `0x101DF000`.
- Uploads erase + program only the sectors the blob covers (`ceil(total_len / 4096)`), one
  sector per `flash_safe_execute()` call; failed COMMIT / aborted partial upload erase sector 0.
- RAM: +7.3 KiB bss (4 KiB upload sector buffer, 1 KiB decode frame, 1 KiB I2C snapshot, 1 KiB
  validation scratch, star table).

