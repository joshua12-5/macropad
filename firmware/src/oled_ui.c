#include "oled_ui.h"
#include "anim.h"
#include "oled_driver.h"
#include "profiles.h"

#include "pico/stdlib.h"

#include <stdio.h>
#include <string.h>

/* Visible rows on 128x64 with 5x7 font (~12 px pitch). */
#define SELECT_VISIBLE   4
#define SELECT_TITLE_Y   2
#define SELECT_LIST_Y0   16
#define SELECT_LINE_H    12

static oled_page_t page;
static absolute_time_t boot_until;
static absolute_time_t toast_until;
static char profile_name[24];
static char toast_l1[22];
static char toast_l2[22];
static int volume_level; /* display-only estimate 0..100 */
static bool dirty;
static bool muted;

static uint8_t select_cursor;
static uint8_t select_window; /* first visible profile index */

static void mark_dirty(void) {
    dirty = true;
}

static void select_ensure_visible(void) {
    uint8_t count = profiles_count();
    if (count == 0) {
        select_window = 0;
        return;
    }
    if (select_cursor >= count) {
        select_cursor = (uint8_t)(count - 1);
    }
    if (select_cursor < select_window) {
        select_window = select_cursor;
    } else if (select_cursor >= (uint8_t)(select_window + SELECT_VISIBLE)) {
        select_window = (uint8_t)(select_cursor - SELECT_VISIBLE + 1);
    }
    if (select_window + SELECT_VISIBLE > count && count >= SELECT_VISIBLE) {
        select_window = (uint8_t)(count - SELECT_VISIBLE);
    }
}

static void render_boot(void) {
    oled_driver_clear();
    oled_driver_draw_string_centered(16, "MACROPAD", true);
    oled_driver_draw_string_centered(32, "RP2040-Zero", true);
    oled_driver_draw_string_centered(48, "Starting...", true);
}

static void render_idle(void) {
    char vol[24];
    oled_driver_clear();
    oled_driver_draw_string_centered(4, "MACROPAD", true);
    oled_driver_draw_string_centered(24, profile_name, true);
    if (muted) {
        snprintf(vol, sizeof vol, "Muted");
    } else {
        snprintf(vol, sizeof vol, "Volume %d%%", volume_level);
    }
    oled_driver_draw_string_centered(48, vol, true);
}

static void render_toast(void) {
    oled_driver_clear();
    oled_driver_draw_string_centered(16, toast_l1, true);
    if (toast_l2[0]) {
        oled_driver_draw_string_centered(36, toast_l2, true);
    }
}

static void render_profile_select(void) {
    uint8_t count = profiles_count();
    char line[22];

    oled_driver_clear();
    oled_driver_draw_string_centered(SELECT_TITLE_Y, "PROFILES", true);

    select_ensure_visible();

    for (uint8_t row = 0; row < SELECT_VISIBLE; row++) {
        uint8_t idx = (uint8_t)(select_window + row);
        if (idx >= count) {
            break;
        }
        const profile_t *p = profiles_get(idx);
        const char *title = "????";
        if (p) {
            if (p->oled.title[0]) {
                title = p->oled.title;
            } else if (p->name[0]) {
                title = p->name;
            }
        }

        int y = SELECT_LIST_Y0 + (int)row * SELECT_LINE_H;
        bool selected = (idx == select_cursor);

        if (selected) {
            snprintf(line, sizeof line, ">%u %s", idx, title);
            /* Inverse highlight bar across the row. */
            oled_driver_fill_rect(0, y - 1, OLED_WIDTH, SELECT_LINE_H - 1, true);
            oled_driver_draw_string(2, y, line, false);
        } else {
            snprintf(line, sizeof line, " %u %s", idx, title);
            oled_driver_draw_string(2, y, line, true);
        }
    }
}

static void render(void) {
    switch (page) {
    case OLED_PAGE_BOOT:
        render_boot();
        break;
    case OLED_PAGE_TOAST:
        render_toast();
        break;
    case OLED_PAGE_PROFILE_SELECT:
        render_profile_select();
        break;
    case OLED_PAGE_IDLE:
    default:
        render_idle();
        break;
    }
    oled_driver_update();
    dirty = false;
}

void oled_ui_init(void) {
    page = OLED_PAGE_BOOT;
    boot_until = make_timeout_time_ms(1500);
    toast_until = get_absolute_time();
    strncpy(profile_name, "CODING", sizeof profile_name - 1);
    toast_l1[0] = toast_l2[0] = '\0';
    volume_level = 50;
    muted = false;
    select_cursor = 0;
    select_window = 0;
    dirty = true;

    if (!oled_driver_init()) {
        /* Keep running without display; UI calls become no-ops via driver_ok. */
        return;
    }
    render();
}

void oled_ui_task(void) {
    if (!oled_driver_ok()) {
        return;
    }

    absolute_time_t now = get_absolute_time();

    if (page == OLED_PAGE_BOOT && absolute_time_diff_us(boot_until, now) >= 0) {
        page = OLED_PAGE_IDLE;
        mark_dirty();
    }

    if (page == OLED_PAGE_TOAST && absolute_time_diff_us(toast_until, now) >= 0) {
        page = OLED_PAGE_IDLE;
        mark_dirty();
    }

    /* Step 24b: the idle animation / blanking owns the framebuffer; keep the
     * dirty flag so the UI repaints as soon as it is released. */
    if (dirty && !anim_screen_owned()) {
        render();
    }
}

void oled_ui_invalidate(void) {
    mark_dirty();
}

void oled_ui_set_profile_name(const char *name) {
    if (!name) {
        return;
    }
    strncpy(profile_name, name, sizeof profile_name - 1);
    profile_name[sizeof profile_name - 1] = '\0';
    if (page == OLED_PAGE_IDLE) {
        mark_dirty();
    }
}

void oled_ui_show_toast(const char *line1, const char *line2, uint32_t ms) {
    strncpy(toast_l1, line1 ? line1 : "", sizeof toast_l1 - 1);
    toast_l1[sizeof toast_l1 - 1] = '\0';
    strncpy(toast_l2, line2 ? line2 : "", sizeof toast_l2 - 1);
    toast_l2[sizeof toast_l2 - 1] = '\0';
    page = OLED_PAGE_TOAST;
    toast_until = make_timeout_time_ms(ms ? ms : 800);
    mark_dirty();
}

void oled_ui_notify_volume(int delta) {
    muted = false;
    volume_level += (delta > 0) ? 2 : -2;
    if (volume_level < 0) {
        volume_level = 0;
    }
    if (volume_level > 100) {
        volume_level = 100;
    }
    char line[22];
    snprintf(line, sizeof line, "Volume %d%%", volume_level);
    oled_ui_show_toast(delta > 0 ? "VOL UP" : "VOL DOWN", line, 700);
}

void oled_ui_notify_mute(void) {
    muted = !muted;
    oled_ui_show_toast(muted ? "MUTE ON" : "MUTE OFF", "", 900);
}

void oled_ui_notify_key(uint8_t key_number) {
    char line[22];
    snprintf(line, sizeof line, "Key %u", key_number);
    oled_ui_show_toast(line, profile_name, 500);
}

bool oled_ui_profile_select_active(void) {
    return page == OLED_PAGE_PROFILE_SELECT;
}

void oled_ui_profile_select_enter(uint8_t initial_index) {
    uint8_t count = profiles_count();
    if (count == 0) {
        return;
    }
    if (initial_index >= count) {
        initial_index = 0;
    }
    select_cursor = initial_index;
    select_window = 0;
    select_ensure_visible();
    page = OLED_PAGE_PROFILE_SELECT;
    mark_dirty();
}

void oled_ui_profile_select_set_cursor(uint8_t index) {
    uint8_t count = profiles_count();
    if (count == 0 || page != OLED_PAGE_PROFILE_SELECT) {
        return;
    }
    if (index >= count) {
        index = (uint8_t)(count - 1);
    }
    select_cursor = index;
    select_ensure_visible();
    mark_dirty();
}

uint8_t oled_ui_profile_select_cursor(void) {
    return select_cursor;
}

void oled_ui_profile_select_exit(void) {
    if (page == OLED_PAGE_PROFILE_SELECT) {
        page = OLED_PAGE_IDLE;
        mark_dirty();
    }
}
