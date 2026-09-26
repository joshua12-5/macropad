# Firmware

RP2040-Zero · Pico SDK · TinyUSB · SSD1306 · KY-040 · Profiles (schema v1) · Action engine · Macro engine · On-device profile select · USB config protocol

Build target: `macropad_step15.uf2`

## Step 15 — USB config protocol

Second HID interface (vendor usage page `0xFF00`) carries 64-byte framed config packets. Host uses hidapi on the same VID/PID filtered by usage page.

| Module | Role |
|--------|------|
| `config_protocol.c` / `.h` | Frame CRC, PING / GET_INFO / ECHO, NAK, deferred TX |
| `usb_descriptors.c` | IF0 keyboard+consumer; IF1 vendor IN/OUT 64-byte |
| `usb_hid_app.c` | Instance 0 = keys/media; instance 1 → config protocol |
| `tusb_config.h` | `CFG_TUD_HID=2`, `CFG_TUD_HID_EP_BUFSIZE=64` |

Protocol doc: [`../protocol/PROTOCOL.md`](../protocol/PROTOCOL.md).

### UART

```
cfg ping seq=N
cfg info seq=N
cfg echo seq=N len=N
cfg nak err=N …
```

### Flash

```bash
export PICO_SDK_PATH=/path/to/pico-sdk
cd firmware && mkdir -p build && cd build
cmake .. && make -j
# Copy macropad_step15.uf2 to the Pico USB mass-storage bootloader.
```

Build may be unverified on this host if Pico SDK / arm-none-eabi is not installed.

## Step 14 — On-device profile select UI

Long-press the encoder (~800 ms) while idle to open a scrollable profile menu on the OLED. Rotate to move the cursor; short-press to confirm; long-press again or wait ~9 s with no input to cancel. Matrix keys and encoder volume/media actions are muted while the menu is open.

| Module | Role |
|--------|------|
| `oled_ui.c` / `oled_ui.h` | `OLED_PAGE_PROFILE_SELECT`, cursor/window, live render from `profiles.h` |
| `main.c` | Enter / move / confirm / cancel / timeout; UART logs |

### OLED menu

- Title: `PROFILES`
- Rows: `>2 CODING` (cursor) / ` 3 BROWSER` — inverse bar on selected row
- ~4 visible lines; window scrolls so the cursor stays on-screen

## Earlier: Step 9 — Non-blocking macro engine

| Module | Role |
|--------|------|
| `macros.c` / `macros.h` | Step opcodes, built-in tables, `macros_fire` / `macros_task` |
| `actions.c` | TEXT/URL/APP typer; `ACTION_MACRO` → `macros_fire`; shared `actions_type_text_id` |
| `usb_hid_app.c` | `usb_hid_tap` + `usb_hid_set_report` for sticky KEY_DOWN/UP |

### Built-in macros

| id | Name | Sequence |
|----|------|----------|
| 0 | hello | H E L L O taps |
| 1 | sel+cpy | Ctrl+A, Ctrl+C |
| 2 | undo/redo | Ctrl+Z, Ctrl+Y |
| 3 | git st | TEXT `git status\n` |
| 4 | alt-tab | Alt hold + Tab |

### Demo bindings

- **Default** key 10 → MACRO hello (0); key 11 TEXT; key 12 URL
- **Coding** key 12 → MACRO select-all + copy (1)
- **Browser** key 11 URL; key 12 MEDIA next

Step format for a future configurator: [`macros/SCHEMA.md`](../macros/SCHEMA.md).

UART (115200 on GP0/GP1) logs profile-select lines, `MACRO start` / `MACRO end`, action typer lines, and `cfg …` protocol lines.

## Deferred (Step 16+)

Flash storage of profiles/macros and binary upload commands — not in this step.
