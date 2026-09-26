# Firmware

RP2040-Zero · Pico SDK · TinyUSB · SSD1306 · KY-040 · Profiles (schema v1) · Action engine

Build target: `macropad_step8.uf2`

## Step 8 — Action engine

Every schema action type has defined behavior:

| Type | Behavior |
|------|----------|
| KEY / SHORTCUT | Held via matrix HID (unchanged) |
| VOLUME / MEDIA / PROFILE | Immediate consumer / profile switch |
| TEXT | Non-blocking HID typer from `text_table` |
| URL | Type URL string + Enter |
| APP | Type launch string + Enter (needs focused launcher/terminal; host helper later) |
| MACRO | OLED + UART stub; `macros_fire()` weak hook for Step 9 |

Hold encoder ~800 ms to cycle profiles (Default → Gaming → Coding → Browser → Photoshop).

### Demo bindings

- **Default** key 11 → TEXT `Hello`; key 12 → URL (GitHub repo)
- **Browser** key 11 → URL; key 12 → MEDIA next track

### Flash

```bash
export PICO_SDK_PATH=/path/to/pico-sdk
cd firmware && mkdir -p build && cd build
cmake .. && make -j
# Then copy macropad_step8.uf2 to the Pico USB mass-storage bootloader.
```
