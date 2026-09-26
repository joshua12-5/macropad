# RP2040 Programmable Macropad

Commercial-style 12-key macropad on **Waveshare RP2040-Zero**: matrix + EC11 encoder + SSD1306 OLED, Pico SDK / TinyUSB firmware, and a Python/PySide6 desktop configurator (in progress).

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
| 1 | System architecture | Documented in chat / docs to follow |
| 2 | RP2040-Zero pinout | Frozen in `firmware/include/board_pins.h` |
| 3 | Matrix scan | In `firmware/` |
| 4 | USB HID keyboard | In `firmware/` (TinyUSB) |
| 5+ | Encoder, OLED, profiles, configurator, PCB, enclosure | Next |

## Firmware (Steps 3–4)

See [`firmware/README.md`](firmware/README.md).

Build requires [Pico SDK](https://github.com/raspberrypi/pico-sdk). Target board: RP2040-Zero (use `PICO_BOARD=pico` for GPIO-identical bring-up).

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
