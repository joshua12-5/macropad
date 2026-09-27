/*
 * Framebuffer + drawing primitives for the 128x64 SSD1306 (page order: byte =
 * 8 vertical pixels, bit0 on top). Pure C with no Pico SDK dependency, so the
 * OLED UI and menus can be rendered off-target (firmware/tests/host). The I2C
 * side (init, non-blocking streaming) lives in oled_driver.c.
 */
#include "oled_driver.h"
#include "oled_font.h"

#include <string.h>

static uint8_t fb[OLED_FB_BYTES];

const uint8_t *oled_driver_framebuffer(void) {
    return fb;
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

void oled_driver_draw_string_right(int x_right, int y, const char *s, bool on) {
    if (!s) {
        return;
    }
    oled_driver_draw_string(x_right - oled_driver_text_width(s), y, s, on);
}

int oled_driver_text_width(const char *s) {
    size_t n = s ? strlen(s) : 0;
    return n ? (int)n * 6 - 1 : 0;
}

void oled_driver_hline(int x, int y, int w, bool on) {
    oled_driver_fill_rect(x, y, w, 1, on);
}

void oled_driver_draw_rect(int x, int y, int w, int h, bool on) {
    if (w <= 0 || h <= 0) {
        return;
    }
    oled_driver_fill_rect(x, y, w, 1, on);
    oled_driver_fill_rect(x, y + h - 1, w, 1, on);
    oled_driver_fill_rect(x, y, 1, h, on);
    oled_driver_fill_rect(x + w - 1, y, 1, h, on);
}

void oled_driver_load_frame(const uint8_t *frame) {
    memcpy(fb, frame, sizeof fb);
}
