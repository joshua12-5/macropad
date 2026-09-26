# Firmware

RP2040-Zero · Pico SDK · TinyUSB

## Current bring-up (Step 5)

- 3×4 matrix keyboard → HID boot keyboard
- **KY-040** rotary encoder breakout → Consumer Control (volume / mute)
- Pins frozen in `include/board_pins.h`

### KY-040 → RP2040-Zero

| KY-040 label | Meaning | RP2040-Zero |
|--------------|---------|-------------|
| **CLK** | Encoder A | **GP2** |
| **DT** | Encoder B | **GP3** |
| **SW** | Push button | **GP15** |
| **+** | VCC | **3V3** (not 5V) |
| **GND** | Ground | **GND** |

Power the module from **3.3 V**. The RP2040 GPIOs are not 5 V tolerant; a 5 V KY-040 supply can damage the MCU when A/B/SW go high.

If CW/CCW feel reversed, swap **CLK** and **DT** only.

If one click changes volume by too much or too little, adjust `DETENTS_PER_CLICK` in `src/encoder.c` (try `4` default, then `2`).

### Build

```bash
export PICO_SDK_PATH=/path/to/pico-sdk
cd firmware && mkdir -p build && cd build
cmake .. -G Ninja && ninja
```

Flash `macropad_step5.uf2` via BOOT+RESET → `RPI-RP2`.
