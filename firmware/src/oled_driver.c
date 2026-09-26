#include "oled_driver.h"
#include "oled_font.h"
#include "board_pins.h"

#include "hardware/i2c.h"
#include "pico/stdlib.h"

#include <string.h>

#define OLED_I2C          i2c0
#define OLED_I2C_BAUD     (400 * 1000)
#define OLED_ADDR_PRIMARY 0x3C
#define OLED_ADDR_ALT     0x3D

static uint8_t fb[OLED_WIDTH * OLED_HEIGHT / 8];
static uint8_t i2c_addr;
static bool ready;

static bool i2c_write_raw(const uint8_t *data, size_t len) {
    int written = i2c_write_blocking(OLED_I2C, i2c_addr, data, len, false);
    return written == (int)len;
}

static bool cmd1(uint8_t c) {
    uint8_t buf[2] = {0x00, c};
    return i2c_write_raw(buf, 2);
}

static bool cmd_list(const uint8_t *cmds, size_t n) {
    for (size_t i = 0; i < n; i++) {
        if (!cmd1(cmds[i])) {
            return false;
        }
    }
    return true;
}

static bool probe_addr(uint8_t addr) {
    uint8_t probe = 0x00;
    int r = i2c_write_blocking(OLED_I2C, addr, &probe, 1, false);
    return r >= 0;
}

bool oled_driver_init(void) {
    ready = false;
    memset(fb, 0, sizeof fb);
    i2c_addr = OLED_ADDR_PRIMARY;

    i2c_init(OLED_I2C, OLED_I2C_BAUD);
    gpio_set_function(PIN_OLED_SDA, GPIO_FUNC_I2C);
    gpio_set_function(PIN_OLED_SCL, GPIO_FUNC_I2C);
    gpio_pull_up(PIN_OLED_SDA);
    gpio_pull_up(PIN_OLED_SCL);
    sleep_ms(50);

    if (probe_addr(OLED_ADDR_PRIMARY)) {
        i2c_addr = OLED_ADDR_PRIMARY;
    } else if (probe_addr(OLED_ADDR_ALT)) {
        i2c_addr = OLED_ADDR_ALT;
    } else {
        return false;
    }

    /* SSD1306 128x64 init sequence (charge pump, horizontal addressing) */
    static const uint8_t init_cmds[] = {
        0xAE,       /* display off */
        0xD5, 0x80, /* clock */
        0xA8, 0x3F, /* multiplex 1/64 */
        0xD3, 0x00, /* display offset */
        0x40,       /* start line */
        0x8D, 0x14, /* charge pump on */
        0x20, 0x00, /* horizontal addressing */
        0xA1,       /* segment remap */
        0xC8,       /* COM scan dec */
        0xDA, 0x12, /* COM pins */
        0x81, 0xCF, /* contrast */
        0xD9, 0xF1, /* precharge */
        0xDB, 0x40, /* VCOM detect */
        0xA4,       /* resume RAM */
        0xA6,       /* normal display */
        0xAF,       /* display on */
    };

    if (!cmd_list(init_cmds, sizeof init_cmds)) {
        return false;
    }

    ready = true;
    oled_driver_clear();
    oled_driver_update();
    return true;
}

bool oled_driver_ok(void) {
    return ready;
}

uint8_t oled_driver_address(void) {
    return i2c_addr;
}

void oled_driver_clear(void) {
    memset(fb, 0, sizeof fb);
}

void oled_driver_set_pixel(int x, int y, bool on) {
    if ((unsigned)x >= OLED_WIDTH || (unsigned)y >= OLED_HEIGHT) {
        return;
    }
    uint16_t i = (uint16_t)(x + (y / 8) * OLED_WIDTH);
    uint8_t mask = (uint8_t)(1u << (y & 7));
    if (on) {
        fb[i] |= mask;
    } else {
        fb[i] &= (uint8_t)~mask;
    }
}

void oled_driver_fill_rect(int x, int y, int w, int h, bool on) {
    for (int yy = y; yy < y + h; yy++) {
        for (int xx = x; xx < x + w; xx++) {
            oled_driver_set_pixel(xx, yy, on);
        }
    }
}

void oled_driver_draw_char(int x, int y, char c, bool on) {
    const uint8_t *g = oled_font_glyph(c);
    for (int col = 0; col < 5; col++) {
        uint8_t bits = g[col];
        for (int row = 0; row < 7; row++) {
            if (bits & (1u << row)) {
                oled_driver_set_pixel(x + col, y + row, on);
            }
        }
    }
}

void oled_driver_draw_string(int x, int y, const char *s, bool on) {
    if (!s) {
        return;
    }
    int cx = x;
    while (*s) {
        if (*s == '\n') {
            cx = x;
            y += 8;
            s++;
            continue;
        }
        oled_driver_draw_char(cx, y, *s, on);
        cx += 6; /* 5 px glyph + 1 px gap */
        s++;
    }
}

void oled_driver_draw_string_centered(int y, const char *s, bool on) {
    if (!s) {
        return;
    }
    size_t n = strlen(s);
    int w = (int)n * 6;
    int x = (OLED_WIDTH - w) / 2;
    if (x < 0) {
        x = 0;
    }
    oled_driver_draw_string(x, y, s, on);
}

void oled_driver_update(void) {
    if (!ready) {
        return;
    }

    /* Set column/page window then stream framebuffer with 0x40 data prefix. */
    if (!cmd1(0x21) || !cmd1(0) || !cmd1(127)) {
        return;
    }
    if (!cmd1(0x22) || !cmd1(0) || !cmd1(7)) {
        return;
    }

    uint8_t chunk[1 + 16];
    chunk[0] = 0x40;
    size_t off = 0;
    while (off < sizeof fb) {
        size_t n = sizeof fb - off;
        if (n > 16) {
            n = 16;
        }
        memcpy(&chunk[1], &fb[off], n);
        if (!i2c_write_raw(chunk, 1 + n)) {
            return;
        }
        off += n;
    }
}
