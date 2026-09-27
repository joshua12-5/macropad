#pragma once

#include <stdint.h>
#include <stdbool.h>

#include "menu.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    OLED_PAGE_BOOT = 0,
    OLED_PAGE_IDLE,
    OLED_PAGE_TOAST,
    OLED_PAGE_MENU
} oled_page_t;

void oled_ui_init(void);
void oled_ui_task(void);   /* call every 1 ms */
void oled_ui_invalidate(void);   /* force a full repaint (after idle animation) */

void oled_ui_set_profile_name(const char *name);
void oled_ui_show_toast(const char *line1, const char *line2, uint32_t ms);
void oled_ui_notify_volume(int delta);   /* +1 / -1; updates local display level */
void oled_ui_notify_mute(void);
void oled_ui_notify_key(uint8_t key_number);

/* On-device menu (device_menu.c owns the menu_t; this only draws it). A toast
 * shown while the menu is open is drawn over it and returns to it. */
void oled_ui_show_menu(const menu_t *menu);
void oled_ui_hide_menu(void);
void oled_ui_menu_changed(void);   /* repaint after navigation / value change */
bool oled_ui_menu_shown(void);
oled_page_t oled_ui_page(void);

#ifdef __cplusplus
}
#endif
