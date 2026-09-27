/*
 * On-device menu content (see device_menu.h). Pages are static tables for the
 * menu.c engine; only the profile list is dynamic. Nothing here blocks: flash
 * writes go through storage_schedule_persist() (debounced) except the explicit
 * "Save device state", which is the same immediate rewrite as SAVE_ALL.
 */
#include "device_menu.h"

#include "anim.h"
#include "config_protocol.h"
#include "oled_ui.h"
#include "profiles.h"
#include "storage.h"

#include "pico/stdlib.h"

#include <stdio.h>
#include <string.h>

static menu_t g_menu;
static absolute_time_t g_deadline;
static absolute_time_t g_refresh_at;

/* ---- helpers ------------------------------------------------------------- */

static const char *profile_title(const profile_t *p) {
    if (p == NULL) {
        return "?";
    }
    if (p->oled.title[0]) {
        return p->oled.title;
    }
    return p->name[0] ? p->name : "?";
}

/* Copy at most n-1 chars (no -Wformat-truncation noise for deliberate cuts). */
static void copy_trunc(char *dst, size_t n, const char *src) {
    size_t len = strlen(src);
    if (len >= n) {
        len = n - 1;
    }
    memcpy(dst, src, len);
    dst[len] = '\0';
}

static void fmt_duration(uint32_t s, char *buf, size_t n) {
    if (s == 0) {
        snprintf(buf, n, "Never");
    } else if (s % 3600u == 0) {
        snprintf(buf, n, "%lu h", (unsigned long)(s / 3600u));
    } else if (s % 60u == 0) {
        snprintf(buf, n, "%lu min", (unsigned long)(s / 60u));
    } else {
        snprintf(buf, n, "%lu s", (unsigned long)s);
    }
}

typedef struct {
    bool enabled;
    uint16_t idle_s;
    uint16_t blank_s;
} idle_cfg_t;

static idle_cfg_t idle_get(void) {
    uint8_t b[ANIM_SETTINGS_SIZE];
    anim_settings_pack(b);
    idle_cfg_t c = {b[0] != 0, (uint16_t)(b[2] | (b[3] << 8)), (uint16_t)(b[4] | (b[5] << 8))};
    return c;
}

static void idle_set(idle_cfg_t c) {
    uint8_t b[ANIM_SETTINGS_SIZE];
    anim_settings_pack(b);   /* keeps flags / reserved bytes */
    b[0] = c.enabled ? 1u : 0u;
    b[2] = (uint8_t)(c.idle_s & 0xFFu);
    b[3] = (uint8_t)(c.idle_s >> 8);
    b[4] = (uint8_t)(c.blank_s & 0xFFu);
    b[5] = (uint8_t)(c.blank_s >> 8);
    (void)anim_settings_unpack(b);
    storage_schedule_persist();   /* same debounce as a profile switch */
}

/* ---- Profiles ------------------------------------------------------------ */

static bool profile_is_active(uint8_t slot) {
    return slot == profiles_active_index();
}

static void profile_slot_value(uint8_t slot, char *buf, size_t n) {
    snprintf(buf, n, "%u", (unsigned)slot);
}

static menu_result_t profile_pick(uint8_t slot) {
    return device_select_profile(slot) ? MENU_CLOSE : MENU_STAY;
}

static uint8_t profiles_page_count(void) {
    return (uint8_t)(profiles_count() + 1u);   /* + Back */
}

static void profiles_page_item(uint8_t index, menu_item_t *out, char *label, size_t n) {
    if (index >= profiles_count()) {
        out->kind = MENU_ITEM_BACK;
        out->label = "Back";
        return;
    }
    copy_trunc(label, n, profile_title(profiles_get(index)));
    out->kind = MENU_ITEM_ACTION;
    out->action = profile_pick;
    out->state = profile_is_active;
    out->value = profile_slot_value;
    out->arg = index;
}

static uint8_t profiles_page_initial(void) {
    return profiles_active_index();
}

static const menu_page_t PAGE_PROFILES = {
    .title = "Profiles",
    .kind = MENU_PAGE_LIST,
    .dyn_count = profiles_page_count,
    .dyn_item = profiles_page_item,
    .initial = profiles_page_initial,
};

/* ---- Idle animation ------------------------------------------------------ */

static const uint16_t START_PRESETS[] = {0, 30, 60, 120, 300, 600};
static const uint16_t BLANK_PRESETS[] = {0, 120, 300, 600, 1800, 3600};
#define N_PRESETS 6u
_Static_assert(sizeof START_PRESETS / sizeof START_PRESETS[0] == N_PRESETS, "presets");
_Static_assert(sizeof BLANK_PRESETS / sizeof BLANK_PRESETS[0] == N_PRESETS, "presets");

static uint8_t preset_index(const uint16_t *presets, uint16_t v) {
    for (uint8_t i = 0; i < N_PRESETS; i++) {
        if (presets[i] == v) {
            return i;
        }
    }
    return 0;
}

static menu_result_t idle_preview(uint8_t arg) {
    (void)arg;
    (void)anim_preview(ANIM_PREVIEW_PLAY);   /* next input wakes (and is swallowed) */
    return MENU_CLOSE;
}

static bool idle_enabled(uint8_t arg) {
    (void)arg;
    return idle_get().enabled;
}

static menu_result_t idle_toggle(uint8_t arg) {
    (void)arg;
    idle_cfg_t c = idle_get();
    c.enabled = !c.enabled;
    idle_set(c);
    return MENU_STAY;
}

static void idle_start_value(uint8_t arg, char *buf, size_t n) {
    (void)arg;
    fmt_duration(idle_get().idle_s, buf, n);
}

static void idle_blank_value(uint8_t arg, char *buf, size_t n) {
    (void)arg;
    fmt_duration(idle_get().blank_s, buf, n);
}

static void start_preset_label(uint8_t i, char *buf, size_t n) {
    fmt_duration(START_PRESETS[i], buf, n);
}

static void blank_preset_label(uint8_t i, char *buf, size_t n) {
    fmt_duration(BLANK_PRESETS[i], buf, n);
}

static bool start_is(uint8_t i) {
    return idle_get().idle_s == START_PRESETS[i];
}

static bool blank_is(uint8_t i) {
    return idle_get().blank_s == BLANK_PRESETS[i];
}

static menu_result_t start_pick(uint8_t i) {
    idle_cfg_t c = idle_get();
    c.idle_s = START_PRESETS[i];
    idle_set(c);
    return MENU_BACK;
}

static menu_result_t blank_pick(uint8_t i) {
    idle_cfg_t c = idle_get();
    c.blank_s = BLANK_PRESETS[i];
    idle_set(c);
    return MENU_BACK;
}

static uint8_t presets_count(void) {
    return N_PRESETS;
}

static void start_item(uint8_t index, menu_item_t *out, char *label, size_t n) {
    start_preset_label(index, label, n);
    out->kind = MENU_ITEM_RADIO;
    out->action = start_pick;
    out->state = start_is;
    out->arg = index;
}

static void blank_item(uint8_t index, menu_item_t *out, char *label, size_t n) {
    blank_preset_label(index, label, n);
    out->kind = MENU_ITEM_RADIO;
    out->action = blank_pick;
    out->state = blank_is;
    out->arg = index;
}

static uint8_t start_initial(void) {
    return preset_index(START_PRESETS, idle_get().idle_s);
}

static uint8_t blank_initial(void) {
    return preset_index(BLANK_PRESETS, idle_get().blank_s);
}

static const menu_page_t PAGE_START_AFTER = {
    .title = "Start after",
    .kind = MENU_PAGE_LIST,
    .dyn_count = presets_count,
    .dyn_item = start_item,
    .initial = start_initial,
};

static const menu_page_t PAGE_SCREEN_OFF = {
    .title = "Screen off",
    .kind = MENU_PAGE_LIST,
    .dyn_count = presets_count,
    .dyn_item = blank_item,
    .initial = blank_initial,
};

static const menu_item_t IDLE_ITEMS[] = {
    {.kind = MENU_ITEM_ACTION, .label = "Preview now", .action = idle_preview},
    {.kind = MENU_ITEM_TOGGLE, .label = "Play when idle", .action = idle_toggle, .state = idle_enabled},
    {.kind = MENU_ITEM_SUBMENU, .label = "Start after", .submenu = &PAGE_START_AFTER, .value = idle_start_value},
    {.kind = MENU_ITEM_SUBMENU, .label = "Screen off", .submenu = &PAGE_SCREEN_OFF, .value = idle_blank_value},
    {.kind = MENU_ITEM_BACK, .label = "Back"},
};

static const menu_page_t PAGE_IDLE = {
    .title = "Idle",
    .kind = MENU_PAGE_LIST,
    .items = IDLE_ITEMS,
    .count = sizeof IDLE_ITEMS / sizeof IDLE_ITEMS[0],
};

/* ---- Device info ----------------------------------------------------------- */

enum { INFO_FW = 0, INFO_PROTO, INFO_SLOT, INFO_ANIM, INFO_FREE, INFO_UPTIME };

static uint32_t rd32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static void info_value(uint8_t line, char *buf, size_t n) {
    switch (line) {
    case INFO_FW:
        snprintf(buf, n, "%u.%u", (unsigned)FW_VERSION_MAJOR, (unsigned)FW_VERSION_MINOR);
        break;
    case INFO_PROTO:
        snprintf(buf, n, "v%u", (unsigned)CFG_PROTO_VERSION);
        break;
    case INFO_SLOT: {
        char t[9];
        copy_trunc(t, sizeof t, profile_title(profiles_active()));
        snprintf(buf, n, "%u %s", (unsigned)profiles_active_index(), t);
        break;
    }
    case INFO_ANIM:
    case INFO_FREE: {
        uint8_t ai[ANIM_INFO_SIZE];
        anim_info(ai);
        const bool stored = (ai[0] & 0x01u) != 0;
        if (line == INFO_ANIM) {
            if (stored) {
                snprintf(buf, n, "%u frames", (unsigned)(ai[2] | (ai[3] << 8)));
            } else {
                snprintf(buf, n, "Built-in");
            }
        } else {
            uint32_t used = stored ? rd32(&ai[6]) : 0u;
            uint32_t region = rd32(&ai[14]);
            snprintf(buf, n, "%lu KiB", (unsigned long)((region - used) / 1024u));
        }
        break;
    }
    case INFO_UPTIME: {
        uint32_t s = to_ms_since_boot(get_absolute_time()) / 1000u;
        if (s >= 3600u) {
            snprintf(buf, n, "%luh %02lum", (unsigned long)(s / 3600u), (unsigned long)(s / 60u % 60u));
        } else if (s >= 60u) {
            snprintf(buf, n, "%lum %02lus", (unsigned long)(s / 60u), (unsigned long)(s % 60u));
        } else {
            snprintf(buf, n, "%lus", (unsigned long)s);
        }
        break;
    }
    default:
        buf[0] = '\0';
        break;
    }
}

static const menu_item_t INFO_ITEMS[] = {
    {.kind = MENU_ITEM_INFO, .label = "Firmware", .value = info_value, .arg = INFO_FW},
    {.kind = MENU_ITEM_INFO, .label = "Protocol", .value = info_value, .arg = INFO_PROTO},
    {.kind = MENU_ITEM_INFO, .label = "Slot", .value = info_value, .arg = INFO_SLOT},
    {.kind = MENU_ITEM_INFO, .label = "Animation", .value = info_value, .arg = INFO_ANIM},
    {.kind = MENU_ITEM_INFO, .label = "Anim free", .value = info_value, .arg = INFO_FREE},
    {.kind = MENU_ITEM_INFO, .label = "Uptime", .value = info_value, .arg = INFO_UPTIME},
};

static const menu_page_t PAGE_INFO = {
    .title = "Device info",
    .kind = MENU_PAGE_INFO,
    .items = INFO_ITEMS,
    .count = sizeof INFO_ITEMS / sizeof INFO_ITEMS[0],
};

/* ---- Main ------------------------------------------------------------------ */

static void main_profile_value(uint8_t arg, char *buf, size_t n) {
    (void)arg;
    copy_trunc(buf, n < 8 ? n : 8, profile_title(profiles_active()));
}

static void main_idle_value(uint8_t arg, char *buf, size_t n) {
    (void)arg;
    snprintf(buf, n, "%s", idle_get().enabled ? "On" : "Off");
}

static menu_result_t main_save(uint8_t arg) {
    (void)arg;
    if (storage_upload_busy() || storage_macro_upload_busy() || anim_upload_busy()) {
        oled_ui_show_toast("Busy", "Upload running", 1200);
        return MENU_STAY;
    }
    bool ok = storage_save_all();
    oled_ui_show_toast(ok ? "Saved" : "Save failed", ok ? "Device state" : "Try again", 1200);
    return MENU_STAY;
}

static const menu_item_t MAIN_ITEMS[] = {
    {.kind = MENU_ITEM_SUBMENU, .label = "Profiles", .submenu = &PAGE_PROFILES, .value = main_profile_value},
    {.kind = MENU_ITEM_SUBMENU, .label = "Idle animation", .submenu = &PAGE_IDLE, .value = main_idle_value},
    {.kind = MENU_ITEM_SUBMENU, .label = "Device info", .submenu = &PAGE_INFO},
    {.kind = MENU_ITEM_ACTION, .label = "Save device state", .action = main_save},
    {.kind = MENU_ITEM_BACK, .label = "Exit"},
};

static const menu_page_t PAGE_MAIN = {
    .title = "Menu",
    .kind = MENU_PAGE_LIST,
    .items = MAIN_ITEMS,
    .count = sizeof MAIN_ITEMS / sizeof MAIN_ITEMS[0],
};

/* ---- public ---------------------------------------------------------------- */

static void touch(void) {
    g_deadline = make_timeout_time_ms(DEVICE_MENU_TIMEOUT_MS);
    g_refresh_at = make_timeout_time_ms(1000);
}

void device_menu_open(void) {
    menu_open(&g_menu, &PAGE_MAIN);
    touch();
    oled_ui_show_menu(&g_menu);
    printf("menu: open\n");
}

void device_menu_close(void) {
    if (!menu_is_open(&g_menu)) {
        return;
    }
    menu_close(&g_menu);
    oled_ui_hide_menu();
    printf("menu: close\n");
}

bool device_menu_active(void) {
    return menu_is_open(&g_menu);
}

const menu_t *device_menu_state(void) {
    return &g_menu;
}

void device_menu_input(menu_input_t in) {
    if (!menu_is_open(&g_menu)) {
        return;
    }
    touch();
    if (!menu_input(&g_menu, in)) {
        oled_ui_hide_menu();
        printf("menu: close\n");
        return;
    }
    oled_ui_menu_changed();
}

void device_menu_task(void) {
    if (!menu_is_open(&g_menu)) {
        return;
    }
    absolute_time_t now = get_absolute_time();
    if (absolute_time_diff_us(g_deadline, now) >= 0) {
        printf("menu: timeout\n");
        device_menu_close();
        return;
    }
    if (menu_page(&g_menu) == &PAGE_INFO && absolute_time_diff_us(g_refresh_at, now) >= 0) {
        g_refresh_at = make_timeout_time_ms(1000);
        oled_ui_menu_changed();   /* uptime ticks */
    }
}

bool device_select_profile(uint8_t slot) {
    if (!profiles_set_active(slot)) {
        return false;
    }
    const profile_t *p = profiles_active();
    if (menu_is_open(&g_menu)) {
        menu_close(&g_menu);
        oled_ui_hide_menu();
    }
    oled_ui_set_profile_name(p->oled.title);
    oled_ui_show_toast("Switched to", profile_title(p), 1200);
    storage_schedule_persist();
    printf("profile -> [%u] %s\n", (unsigned)slot, p->name);
    return true;
}
