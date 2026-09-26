# Firmware

RP2040-Zero · Pico SDK · TinyUSB · SSD1306 · KY-040 · Profiles (schema v1) · Action engine · Macro engine

Build target: `macropad_step9.uf2`

## Step 9 — Non-blocking macro engine

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

Hold encoder ~800 ms to cycle profiles.

Step format for a future configurator: [`macros/SCHEMA.md`](../macros/SCHEMA.md).

### Flash

```bash
export PICO_SDK_PATH=/path/to/pico-sdk
cd firmware && mkdir -p build && cd build
cmake .. && make -j
# Copy macropad_step9.uf2 to the Pico USB mass-storage bootloader.
```

UART (115200 on GP0/GP1) logs `MACRO start` / `MACRO end` and action typer lines.
