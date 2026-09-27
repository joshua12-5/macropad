#pragma once

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    OLED_PAGE_BOOT = 0,
    OLED_PAGE_IDLE,
    OLED_PAGE_TOAST,
    OLED_PAGE_PROFILE_SELECT
} oled_page_t;

void oled_ui_init(void);
void oled_ui_task(void);   /* call every 1 ms */
void oled_ui_invalidate(void);   /* force a full repaint (after idle animation) */

void oled_ui_set_profile_name(const char *name);
void oled_ui_show_toast(const char *line1, const char *line2, uint32_t ms);
void oled_ui_notify_volume(int delta);   /* +1 / -1; updates local display level */
void oled_ui_notify_mute(void);
void oled_ui_notify_key(uint8_t key_number);

/* On-device profile select menu. Render reads live from profiles.h. */
bool oled_ui_profile_select_active(void);
void oled_ui_profile_select_enter(uint8_t initial_index);
void oled_ui_profile_select_set_cursor(uint8_t index);
uint8_t oled_ui_profile_select_cursor(void);
void oled_ui_profile_select_exit(void);

#ifdef __cplusplus
}
#endif
