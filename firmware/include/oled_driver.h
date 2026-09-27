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
void oled_driver_update(void);          /* queue framebuffer push (non-blocking) */
void oled_driver_task(void);            /* stream queued frame: call every main-loop tick */
bool oled_driver_busy(void);            /* push queued or in progress */
void oled_driver_update_blocking(void); /* queue + drain (init only) */
void oled_driver_load_frame(const uint8_t *frame); /* 1024 B, SSD1306 page order */
void oled_driver_display_on(bool on);   /* 0xAF / 0xAE (blank for burn-in protection) */
void oled_driver_last_frame_us(uint32_t *bus_us, uint32_t *wall_us);
bool oled_driver_ok(void);
uint8_t oled_driver_address(void);      /* 0x3C or 0x3D */

#ifdef __cplusplus
}
#endif
