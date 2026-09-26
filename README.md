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
| 1 | System architecture | Done (chat) |
| 2 | RP2040-Zero pinout | Frozen in `firmware/include/board_pins.h` |
| 3 | Matrix scan | Done |
| 4 | USB HID keyboard | Done |
| 5 | Rotary encoder + volume/mute | Done |
| 6 | SSD1306 OLED UI | Done |
| 7+ | Profiles, configurator, PCB, enclosure | Next |

## Firmware

See [`firmware/README.md`](firmware/README.md).

Build requires [Pico SDK](https://github.com/raspberrypi/pico-sdk). Use `PICO_BOARD=pico` for RP2040-Zero bring-up (same GPIO numbers).

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
