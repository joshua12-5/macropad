#include "macros.h"

#include "actions.h"
#include "macro_blob.h"
#include "oled_ui.h"
#include "text_table.h"
#include "usb_hid_app.h"

#include "class/hid/hid.h"

#include <stdio.h>
#include <string.h>

#ifndef KEYBOARD_MODIFIER_LEFTCTRL
#define KEYBOARD_MODIFIER_LEFTCTRL 0x01
#endif
#ifndef KEYBOARD_MODIFIER_LEFTSHIFT
#define KEYBOARD_MODIFIER_LEFTSHIFT 0x02
#endif
#ifndef KEYBOARD_MODIFIER_LEFTALT
#define KEYBOARD_MODIFIER_LEFTALT 0x04
#endif
#ifndef HID_KEY_A
#define HID_KEY_A 0x04
#endif
#ifndef HID_KEY_C
#define HID_KEY_C 0x06
#endif
#ifndef HID_KEY_E
#define HID_KEY_E 0x08
#endif
#ifndef HID_KEY_H
#define HID_KEY_H 0x0B
#endif
#ifndef HID_KEY_L
#define HID_KEY_L 0x0F
#endif
#ifndef HID_KEY_O
#define HID_KEY_O 0x12
#endif
#ifndef HID_KEY_Y
#define HID_KEY_Y 0x1C
#endif
#ifndef HID_KEY_Z
#define HID_KEY_Z 0x1D
#endif
#ifndef HID_KEY_TAB
#define HID_KEY_TAB 0x2B
#endif

#define M_END           { MACRO_END, 0, 0, 0, 0 }
#define M_TAP(m, k)     { MACRO_TAP, (m), (k), 0, 0 }
#define M_DOWN(m, k)    { MACRO_KEY_DOWN, (m), (k), 0, 0 }
#define M_UP_ALL        { MACRO_KEY_UP, 0, 0, 0, 0 }
#define M_DELAY(ms)     { MACRO_DELAY_MS, 0, 0, 0, (ms) }
#define M_TEXT(id)      { MACRO_TEXT, 0, 0, 0, (id) }

/* ---- Factory defaults (const flash) ---- */

static const macro_step_t factory_hello[] = {
    M_TAP(0, HID_KEY_H),
    M_DELAY(30),
    M_TAP(0, HID_KEY_E),
    M_DELAY(30),
    M_TAP(0, HID_KEY_L),
    M_DELAY(30),
    M_TAP(0, HID_KEY_L),
    M_DELAY(30),
    M_TAP(0, HID_KEY_O),
    M_END,
};

static const macro_step_t factory_select_copy[] = {
    M_TAP(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_A),
    M_DELAY(40),
    M_TAP(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_C),
    M_END,
};

static const macro_step_t factory_undo_redo[] = {
    M_TAP(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_Z),
    M_DELAY(50),
    M_TAP(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_Y),
    M_END,
};

static const macro_step_t factory_git_status[] = {
    M_TEXT(TEXT_ID_GIT_STATUS),
    M_END,
};

static const macro_step_t factory_alt_tab[] = {
    M_DOWN(KEYBOARD_MODIFIER_LEFTALT, 0),
    M_DELAY(20),
    M_TAP(0, HID_KEY_TAB),
    M_DELAY(80),
    M_UP_ALL,
    M_END,
};

typedef struct {
    const char *name;
    const macro_step_t *steps;
    uint8_t count;
} factory_def_t;

static uint8_t count_steps(const macro_step_t *steps) {
    for (uint8_t i = 0; i < MACRO_MAX_STEPS; i++) {
        if (steps[i].op == MACRO_END) {
            return (uint8_t)(i + 1u);
        }
    }
    return MACRO_MAX_STEPS;
}

static const factory_def_t k_factory[MACRO_BUILTIN_COUNT] = {
    [MACRO_ID_HELLO]       = { "hello",     factory_hello,       0 },
    [MACRO_ID_SELECT_COPY] = { "sel+cpy",   factory_select_copy, 0 },
    [MACRO_ID_UNDO_REDO]   = { "undo/redo", factory_undo_redo,   0 },
    [MACRO_ID_GIT_STATUS]  = { "git st",    factory_git_status,  0 },
    [MACRO_ID_ALT_TAB]     = { "alt-tab",   factory_alt_tab,     0 },
};

/* ---- RAM working set ---- */

static macro_blob_slot_t g_slots[MACRO_BUILTIN_COUNT];

typedef enum {
    MSTATE_IDLE = 0,
    MSTATE_RUN,
    MSTATE_WAIT_TAP,
    MSTATE_WAIT_DELAY,
    MSTATE_WAIT_TEXT,
    MSTATE_WAIT_HOLD,
} mstate_t;

static mstate_t state;
static uint8_t active_id;
static uint8_t step_index;
static uint16_t delay_left;
static uint8_t settle_ticks;

static uint8_t sticky_mods;
static uint8_t sticky_keys[6];

static void sticky_clear(void) {
    sticky_mods = 0;
    memset(sticky_keys, 0, sizeof sticky_keys);
}

static void sticky_send(void) {
    usb_hid_set_report(sticky_mods, sticky_keys);
}

static void sticky_add_key(uint8_t keycode) {
    if (keycode == 0) {
        return;
    }
    for (int i = 0; i < 6; i++) {
        if (sticky_keys[i] == keycode) {
            return;
        }
    }
    for (int i = 0; i < 6; i++) {
        if (sticky_keys[i] == 0) {
            sticky_keys[i] = keycode;
            return;
        }
    }
}

static void sticky_remove_key(uint8_t keycode) {
    for (int i = 0; i < 6; i++) {
        if (sticky_keys[i] == keycode) {
            for (int j = i; j < 5; j++) {
                sticky_keys[j] = sticky_keys[j + 1];
            }
            sticky_keys[5] = 0;
            return;
        }
    }
}

static void finish_macro(void) {
    const char *name = (active_id < MACRO_BUILTIN_COUNT)
                           ? g_slots[active_id].name
                           : "?";
    printf("MACRO end id=%u (%s)\n", (unsigned)active_id, name);
    sticky_clear();
    if (usb_hid_tap_idle()) {
        uint8_t empty[6] = {0};
        usb_hid_set_report(0, empty);
    }
    state = MSTATE_IDLE;
    step_index = 0;
    delay_left = 0;
    settle_ticks = 0;
}

static bool try_step(const macro_step_t *s) {
    switch (s->op) {
    case MACRO_END:
        finish_macro();
        return false;

    case MACRO_DELAY_MS:
        delay_left = s->arg;
        state = MSTATE_WAIT_DELAY;
        return true;

    case MACRO_TAP:
        if (!usb_hid_tap_idle()) {
            state = MSTATE_WAIT_TAP;
            return false;
        }
        usb_hid_tap((uint8_t)(sticky_mods | s->mods), s->keycode);
        state = MSTATE_WAIT_TAP;
        return true;

    case MACRO_KEY_DOWN:
        sticky_mods |= s->mods;
        sticky_add_key(s->keycode);
        sticky_send();
        settle_ticks = 2;
        state = MSTATE_WAIT_HOLD;
        return true;

    case MACRO_KEY_UP:
        if (s->keycode == 0 && s->mods == 0) {
            sticky_clear();
        } else {
            sticky_mods &= (uint8_t)~s->mods;
            sticky_remove_key(s->keycode);
        }
        sticky_send();
        settle_ticks = 2;
        state = MSTATE_WAIT_HOLD;
        return true;

    case MACRO_TEXT:
        if (actions_busy() || !usb_hid_tap_idle()) {
            state = MSTATE_WAIT_TEXT;
            return false;
        }
        if (!actions_type_text_id((uint8_t)s->arg, false)) {
            printf("MACRO TEXT: failed id=%u\n", (unsigned)s->arg);
            state = MSTATE_RUN;
            return true;
        }
        state = MSTATE_WAIT_TEXT;
        return true;

    case MACRO_CONSUMER:
        usb_hid_consumer_usage(s->arg);
        settle_ticks = 4;
        state = MSTATE_WAIT_HOLD;
        return true;

    default:
        printf("MACRO: unknown op %u\n", s->op);
        finish_macro();
        return false;
    }
}

static void advance(void) {
    if (active_id >= MACRO_BUILTIN_COUNT) {
        finish_macro();
        return;
    }
    const macro_blob_slot_t *slot = &g_slots[active_id];
    if (step_index >= slot->step_count) {
        finish_macro();
        return;
    }
    const macro_step_t *s = &slot->steps[step_index];
    if (try_step(s)) {
        step_index++;
    }
}

static bool load_factory_slot(uint8_t id) {
    if (id >= MACRO_BUILTIN_COUNT) {
        return false;
    }
    const factory_def_t *f = &k_factory[id];
    uint8_t n = f->count ? f->count : count_steps(f->steps);
    return macros_replace(id, f->name, f->steps, n);
}

void macros_factory_reset_all(void) {
    for (uint8_t i = 0; i < MACRO_BUILTIN_COUNT; i++) {
        (void)load_factory_slot(i);
    }
}

bool macros_replace(uint8_t id, const char *name,
                    const macro_step_t *steps, uint8_t count) {
    if (id >= MACRO_BUILTIN_COUNT || steps == NULL || name == NULL) {
        return false;
    }
    if (count < 1u || count > MACRO_MAX_STEPS) {
        return false;
    }

    /* Abort if replacing the macro currently playing. */
    if (state != MSTATE_IDLE && active_id == id) {
        macros_abort();
    }

    macro_blob_slot_t *slot = &g_slots[id];
    memset(slot, 0, sizeof(*slot));

    size_t namelen = strnlen(name, MACRO_NAME_MAX - 1u);
    memcpy(slot->name, name, namelen);

    /* Copy steps; truncate at first END or append END if missing. */
    uint8_t n = 0;
    bool has_end = false;
    for (uint8_t i = 0; i < count; i++) {
        slot->steps[i] = steps[i];
        slot->steps[i].pad = 0;
        n = (uint8_t)(i + 1u);
        if (steps[i].op == MACRO_END) {
            has_end = true;
            break;
        }
    }
    if (!has_end) {
        if (count >= MACRO_MAX_STEPS) {
            return false;
        }
        slot->steps[count].op = MACRO_END;
        n = (uint8_t)(count + 1u);
    }
    slot->step_count = n;
    return true;
}

bool macros_apply_blob(uint8_t id, const uint8_t *blob, size_t len) {
    if (id >= MACRO_BUILTIN_COUNT || blob == NULL) {
        return false;
    }
    macro_blob_slot_t tmp;
    if (!macro_blob_unpack(blob, len, &tmp)) {
        return false;
    }
    return macros_replace(id, tmp.name, tmp.steps, tmp.step_count);
}

bool macros_pack_slot(uint8_t id, uint8_t *dst, size_t dst_len) {
    if (id >= MACRO_BUILTIN_COUNT || dst == NULL) {
        return false;
    }
    return macro_blob_pack(&g_slots[id], dst, dst_len);
}

void macros_init(void) {
    state = MSTATE_IDLE;
    active_id = 0;
    step_index = 0;
    delay_left = 0;
    settle_ticks = 0;
    sticky_clear();
    macros_factory_reset_all();
}

bool macros_busy(void) {
    return state != MSTATE_IDLE;
}

void macros_abort(void) {
    if (state == MSTATE_IDLE) {
        return;
    }
    printf("MACRO abort id=%u\n", (unsigned)active_id);
    sticky_clear();
    if (usb_hid_tap_idle()) {
        uint8_t empty[6] = {0};
        usb_hid_set_report(0, empty);
    }
    state = MSTATE_IDLE;
    step_index = 0;
    delay_left = 0;
    settle_ticks = 0;
}

const char *macros_name(uint8_t macro_id) {
    if (macro_id >= MACRO_BUILTIN_COUNT) {
        return NULL;
    }
    return g_slots[macro_id].name;
}

bool macros_fire(uint8_t macro_id) {
    if (macro_id >= MACRO_BUILTIN_COUNT) {
        printf("MACRO: invalid id=%u\n", (unsigned)macro_id);
        return false;
    }
    if (state != MSTATE_IDLE) {
        printf("MACRO: busy, ignore id=%u\n", (unsigned)macro_id);
        return false;
    }
    if (actions_busy() || !usb_hid_tap_idle()) {
        printf("MACRO: HID/actions busy, ignore id=%u\n", (unsigned)macro_id);
        return false;
    }

    active_id = macro_id;
    step_index = 0;
    delay_left = 0;
    settle_ticks = 0;
    sticky_clear();
    state = MSTATE_RUN;

    const char *name = g_slots[macro_id].name;
    oled_ui_show_toast("MACRO", name, 800);
    printf("MACRO start id=%u (%s)\n", (unsigned)macro_id, name);
    return true;
}

void macros_task(void) {
    switch (state) {
    case MSTATE_IDLE:
        return;

    case MSTATE_RUN:
        advance();
        return;

    case MSTATE_WAIT_TAP:
        if (!usb_hid_tap_idle()) {
            return;
        }
        if (sticky_mods || sticky_keys[0]) {
            sticky_send();
        }
        state = MSTATE_RUN;
        return;

    case MSTATE_WAIT_DELAY:
        if (delay_left > 0) {
            delay_left--;
            return;
        }
        state = MSTATE_RUN;
        return;

    case MSTATE_WAIT_TEXT:
        if (!actions_busy() && usb_hid_tap_idle()) {
            state = MSTATE_RUN;
        }
        return;

    case MSTATE_WAIT_HOLD:
        if (settle_ticks > 0) {
            settle_ticks--;
            return;
        }
        state = MSTATE_RUN;
        return;

    default:
        state = MSTATE_IDLE;
        return;
    }
}
