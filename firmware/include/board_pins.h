#pragma once

/*
 * Step 2 frozen pinout — RP2040-Zero (edge pins only).
 * Do not change without revising the architecture pin table.
 */

/* Matrix 3x4 */
#define PIN_ROW1  8
#define PIN_ROW2  9
#define PIN_ROW3 10
#define PIN_COL1 11
#define PIN_COL2 12
#define PIN_COL3 13
#define PIN_COL4 14

#define MATRIX_ROWS 3
#define MATRIX_COLS 4

/* Encoder: KY-040 breakout (CLK=A, DT=B, SW) — same as EC11 */
#define PIN_ENC_A   2  /* KY-040 CLK */
#define PIN_ENC_B   3  /* KY-040 DT  */
#define PIN_ENC_SW 15  /* KY-040 SW  */

/* OLED SSD1306 I2C0 (wired in Step 6) */
#define PIN_OLED_SDA 4
#define PIN_OLED_SCL 5

/* Onboard WS2812 on RP2040-Zero */
#define PIN_NEOPIXEL 16

/* Optional debug UART0 */
#define PIN_UART_TX 0
#define PIN_UART_RX 1
#define DEBUG_UART_BAUD 115200
