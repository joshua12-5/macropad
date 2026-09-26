# Macropad architecture (Step 19)

Hardening / polish overview of the shipping stack after Steps 1–18.
No PCB work here — firmware + host + docs only.

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
│ Matrix / encoder / OLED UI                                      │
│   3×4 scan · EC11 · SSD1306 toasts / profile select             │
├─────────────────────────────────────────────────────────────────┤
│ Hardware pinout (frozen)                                        │
│   board_pins.h → rows/cols, ENC A/B/SW, I2C OLED, UART          │
├─────────────────────────────────────────────────────────────────┤
│ Flash storage v2 (last 4 KiB sector, magic MPFL)                │
│   active_slot + 5×profile_blob + 5×macro_blob + CRC             │
└─────────────────────────────────────────────────────────────────┘
```

| Layer | Code | Notes |
|-------|------|--------|
| Pinout | `firmware/include/board_pins.h` | GP8–10 rows, GP11–14 cols, GP2/3/15 encoder, GP4/5 OLED |
| Scan / input | `matrix.c`, `encoder.c` | Debounced matrix events; encoder CW/CCW/press |
| Display | `oled_*.c` | Idle title, key toast, on-device profile select |
| Profiles / actions | `profiles.c`, `actions.c`, `macros.c` | RAM slots; TEXT/URL/APP/MACRO/KEY/… |
| USB + protocol | `usb_*.c`, `config_protocol.c` | TinyUSB; `tud_task` via `usb_hid_task` unchanged |
| Flash | `storage.c` | v2 image; upload staging; debounced active persist |
| Host | `configurator/macropad_config/` | Editors, Device menu, autoswitch |

## Data flows

### Key press (device)

1. `matrix_task` → press event for key 1–12.
2. If profile-select menu is open → event muted.
3. OLED toast; for non-KEY/SHORTCUT types → `actions_fire`.
4. KEY/SHORTCUT holds feed `usb_hid_update_from_matrix` when idle (not busy / not in menu).
5. Action engine may queue TEXT/URL/APP or start `macros` playback → HID reports on IF0.

### Profile upload (host → device)

1. Host packs JSON → `profile_blob_v1` (148 B). See [`../protocol/PROFILE_BLOB.md`](../protocol/PROFILE_BLOB.md).
2. `PROFILE_BEGIN` / `DATA` / `COMMIT` over IF1.
3. Device stages in RAM, CRC-checks, `profiles_write_slot`, then **`storage_save_all`** (full v2 sector).
4. OLED title refreshes if the active slot’s blob changed.
5. Overlapping profile **or** macro upload → NAK `EBUSY`.

### Macro upload (host → device)

1. Host packs library entry → `macro_blob_v1` (162 B). See [`../protocol/MACRO_BLOB.md`](../protocol/MACRO_BLOB.md).
2. Same chunked BEGIN/DATA/COMMIT; replaces RAM macro slot (aborts playback if running).
3. COMMIT calls **`storage_save_all`**. Mutually exclusive with profile upload.

### Auto-switch `SET_ACTIVE` (0x30)

1. Host autoswitch matches foreground process → slot (see [`../autoswitch/SCHEMA.md`](../autoswitch/SCHEMA.md)).
2. `SET_ACTIVE` → `profiles_set_active` + OLED toast (**immediate RAM**).
3. OK even while an upload is busy (staging untouched).
4. **Step 19:** schedules a **debounced** flash rewrite (~4 s quiet). Repeated switches cancel/reschedule. UART: `stor debounce save` then `stor save ok|fail`.
5. Immediate rewrite: `SAVE_ALL` (`0x32`) from Device → Save device state.

## Flash vs RAM

| What | Where | Lifetime |
|------|--------|----------|
| Active profile index | RAM (`profiles`) + flash header `active_slot` | Boot loads flash; SET_ACTIVE updates RAM then debounced flash |
| Profile blobs (5) | RAM + flash | Upload COMMIT / SAVE_ALL / debounce rewrite |
| Macro bank (5) | RAM + flash (v2) | Same; v1 flash keeps factory macros until next save |
| Upload staging buffer | RAM only | Cleared on COMMIT/ABORT |
| Matrix / encoder / OLED / HID state | RAM | Ephemeral |
| Host JSON / rules | Host disk | Source of truth for editors; device holds packed copies |

Flash wear policy: never erase on every auto-switch. Debounce coalesces rapid `SET_ACTIVE`; uploads and `SAVE_ALL` rewrite once intentionally.

## Protocol references

- Wire commands & framing: [`../protocol/PROTOCOL.md`](../protocol/PROTOCOL.md)
- Profile binary: [`../protocol/PROFILE_BLOB.md`](../protocol/PROFILE_BLOB.md)
- Macro binary: [`../protocol/MACRO_BLOB.md`](../protocol/MACRO_BLOB.md)
- Autoswitch rules: [`../autoswitch/SCHEMA.md`](../autoswitch/SCHEMA.md)

## Step 19 hardening summary

- `FW_VERSION_MINOR = 19`, CMake target `macropad_step19`
- Debounced `active_slot` persist after `SET_ACTIVE`
- `CFG_CMD_SAVE_ALL = 0x32` for explicit Device menu save (`EBUSY` if upload in progress)
- Host: `save_all()`, clearer NAK errors, disconnect-safe autoswitch, smoke runner
- Next: **Step 20** testing / versioning polish
