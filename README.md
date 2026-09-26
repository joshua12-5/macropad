# RP2040 Programmable Macropad

Commercial-style 12-key macropad on **Waveshare RP2040-Zero**: matrix + EC11 encoder + SSD1306 OLED, Pico SDK / TinyUSB firmware, and a Python/PySide6 desktop configurator.

## Layout

```
OLED                         ENCODER
1   2   3   4
5   6   7   8
9  10  11  12
```

## Status

| Step | Topic | Status |
|------|--------|--------|
| 1 | System architecture | Done (chat) |
| 2 | RP2040-Zero pinout | Frozen in `firmware/include/board_pins.h` |
| 3 | Matrix scan | Done |
| 4 | USB HID keyboard | Done |
| 5 | Rotary encoder + volume/mute | Done |
| 6 | SSD1306 OLED UI | Done |
| 7 | Profile system (schema v1) | Done |
| 8 | Action engine (TEXT/URL/APP/MACRO stub) | Done |
| 9 | Non-blocking macro engine | Done |
| 10 | PySide6 configurator shell | Done |
| 11 | Key/encoder action editors | Done |
| 12 | Profile manager (new / duplicate / delete) | Done |
| 13 | Macro library editor (host JSON) | Done |
| 14 | On-device profile select UI | Done |
| 15–17 | Protocol / storage / polish | Next (Step 15: protocol) |

**Configurator block (Steps 10–13) is complete.** Firmware Step 14 (encoder OLED profile menu) is done.

## Profiles

Host-side JSON (schema v1): [`profiles/`](profiles/) + [`profiles/SCHEMA.md`](profiles/SCHEMA.md).

## Macros

Host library (configurator source of truth): [`macros/library.json`](macros/library.json) + [`macros/SCHEMA.md`](macros/SCHEMA.md).

Firmware still plays packed step tables in `firmware/src/macros.c` until a USB sync/flash protocol exists — host JSON and firmware may diverge until then.

## Configurator

Desktop app (Step 13 macro library): [`configurator/`](configurator/).

```bash
cd configurator
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m macropad_config
```

Loads `profiles/*.json` (override with `MACROPAD_PROFILES_DIR`) and `macros/library.json` (`MACROPAD_MACROS_PATH`). Edit key/encoder actions and profile name/OLED title; **File → Save** (`Ctrl+S`) writes JSON. **Profile → New / Duplicate / Delete** manage profiles. **Profile → Macro library…** edits the host macro library. USB upload is Steps 15–17.

Headless checks:

```bash
python scripts/smoke_load.py
python scripts/smoke_edit.py
python scripts/smoke_profile_mgr.py
python scripts/smoke_macros.py
```

## Firmware

See [`firmware/README.md`](firmware/README.md).

Build requires [Pico SDK](https://github.com/raspberrypi/pico-sdk). Use `PICO_BOARD=pico` for RP2040-Zero bring-up (same GPIO numbers). Flash target: `macropad_step14.uf2`.

**On-device profile select:** long-press encoder (~800 ms) → OLED menu; rotate to highlight; short-press to confirm; long-press or ~9 s idle to cancel.

## Pinout (locked)

| Function | GPIO |
|----------|------|
| Rows 1–3 | GP8, GP9, GP10 |
| Cols 1–4 | GP11–GP14 |
| Encoder A/B/SW | GP2, GP3, GP15 |
| OLED SDA/SCL | GP4, GP5 (I2C0) |
| NeoPixel (onboard) | GP16 |
| Debug UART | GP0 TX, GP1 RX |

## License

TBD by repo owner.
