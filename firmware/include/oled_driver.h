#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define OLED_WIDTH  128
#define OLED_HEIGHT 64

bool oled_driver_init(void);
void oled_driver_clear(void);
void oled_driver_set_pixel(int x, int y, bool on);
void oled_driver_fill_rect(int x, int y, int w, int h, bool on);
void oled_driver_draw_char(int x, int y, char c, bool on);
void oled_driver_draw_string(int x, int y, const char *s, bool on);
void oled_driver_draw_string_centered(int y, const char *s, bool on);
void oled_driver_update(void);          /* push framebuffer over I2C */
bool oled_driver_ok(void);
uint8_t oled_driver_address(void);      /* 0x3C or 0x3D */

#ifdef __cplusplus
}
#endif
