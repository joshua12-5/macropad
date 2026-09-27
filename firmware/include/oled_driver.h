#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define OLED_WIDTH  128
#define OLED_HEIGHT 64
#define OLED_FB_BYTES (OLED_WIDTH * OLED_HEIGHT / 8)

/* Drawing (oled_gfx.c; no SDK dependency, also built for host tests). */
void oled_driver_clear(void);
void oled_driver_set_pixel(int x, int y, bool on);
void oled_driver_fill_rect(int x, int y, int w, int h, bool on);
void oled_driver_draw_char(int x, int y, char c, bool on);
void oled_driver_draw_string(int x, int y, const char *s, bool on);
void oled_driver_draw_string_centered(int y, const char *s, bool on);
void oled_driver_draw_string_right(int x_right, int y, const char *s, bool on);
int oled_driver_text_width(const char *s);   /* 6 px per glyph, minus the trailing gap */
void oled_driver_hline(int x, int y, int w, bool on);
void oled_driver_draw_rect(int x, int y, int w, int h, bool on);   /* 1 px outline */
void oled_driver_load_frame(const uint8_t *frame); /* 1024 B, SSD1306 page order */
const uint8_t *oled_driver_framebuffer(void);      /* OLED_FB_BYTES, page order */

/* Hardware (oled_driver.c). */
bool oled_driver_init(void);
void oled_driver_update(void);          /* queue framebuffer push (non-blocking) */
void oled_driver_task(void);            /* stream queued frame: call every main-loop tick */
bool oled_driver_busy(void);            /* push queued or in progress */
void oled_driver_update_blocking(void); /* queue + drain (init only) */
void oled_driver_display_on(bool on);   /* 0xAF / 0xAE (blank for burn-in protection) */
void oled_driver_last_frame_us(uint32_t *bus_us, uint32_t *wall_us);
bool oled_driver_ok(void);
uint8_t oled_driver_address(void);      /* 0x3C or 0x3D */

#ifdef __cplusplus
}
#endif
