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
    OLED_PAGE_PROFILE_SELECT  /* reserved; used fully in Step 14 */
} oled_page_t;

void oled_ui_init(void);
void oled_ui_task(void);   /* call every 1 ms */

void oled_ui_set_profile_name(const char *name);
void oled_ui_show_toast(const char *line1, const char *line2, uint32_t ms);
void oled_ui_notify_volume(int delta);   /* +1 / -1; updates local display level */
void oled_ui_notify_mute(void);
void oled_ui_notify_key(uint8_t key_number);

#ifdef __cplusplus
}
#endif
