#include "profiles.h"

#include "macros.h"
#include "text_table.h"

#include "class/hid/hid.h"

#include <string.h>

#ifndef HID_KEY_SLASH
#define HID_KEY_SLASH 0x38
#endif
#ifndef HID_KEY_BRACKET_LEFT
#define HID_KEY_BRACKET_LEFT 0x2F
#endif
#ifndef HID_KEY_BRACKET_RIGHT
#define HID_KEY_BRACKET_RIGHT 0x30
#endif
#ifndef HID_KEY_EQUAL
#define HID_KEY_EQUAL 0x2E
#endif
#ifndef HID_KEY_MINUS
#define HID_KEY_MINUS 0x2D
#endif
#ifndef HID_KEY_ARROW_LEFT
#define HID_KEY_ARROW_LEFT 0x50
#endif
#ifndef HID_KEY_ARROW_RIGHT
#define HID_KEY_ARROW_RIGHT 0x4F
#endif
#ifndef HID_KEY_TAB
#define HID_KEY_TAB 0x2B
#endif
#ifndef HID_KEY_SPACE
#define HID_KEY_SPACE 0x2C
#endif
#ifndef HID_KEY_F11
#define HID_KEY_F11 0x44
#endif

#ifndef HID_USAGE_CONSUMER_MUTE
#define HID_USAGE_CONSUMER_MUTE 0x00E2
#endif
#ifndef HID_USAGE_CONSUMER_PLAY_PAUSE
#define HID_USAGE_CONSUMER_PLAY_PAUSE 0x00CD
#endif
#ifndef HID_USAGE_CONSUMER_SCAN_NEXT
#define HID_USAGE_CONSUMER_SCAN_NEXT 0x00B5
#endif
#ifndef KEYBOARD_MODIFIER_LEFTCTRL
#define KEYBOARD_MODIFIER_LEFTCTRL 0x01
#endif
#ifndef KEYBOARD_MODIFIER_LEFTGUI
#define KEYBOARD_MODIFIER_LEFTGUI 0x08
#endif
#ifndef KEYBOARD_MODIFIER_LEFTALT
#define KEYBOARD_MODIFIER_LEFTALT 0x04
#endif
#ifndef KEYBOARD_MODIFIER_LEFTSHIFT
#define KEYBOARD_MODIFIER_LEFTSHIFT 0x02
#endif

static profile_t slots[PROFILE_SLOT_COUNT];
static uint8_t active;

static void fill_oled(profile_t *p, const char *title) {
    memset(&p->oled, 0, sizeof p->oled);
    strncpy(p->oled.title, title, PROFILE_NAME_MAX - 1);
    p->oled.animation = OLED_ANIM_STATIC;
}

static void set_meta(profile_t *p, const char *id, const char *name) {
    memset(p, 0, sizeof(*p));
    p->schema_version = PROFILE_SCHEMA_VERSION;
    strncpy(p->id, id, PROFILE_NAME_MAX - 1);
    strncpy(p->name, name, PROFILE_NAME_MAX - 1);
    fill_oled(p, name);
    for (int i = 0; i < PROFILE_KEY_COUNT; i++) {
        p->keys[i] = action_disabled();
    }
    p->encoder.cw = action_volume(VOLUME_UP);
    p->encoder.ccw = action_volume(VOLUME_DOWN);
    p->encoder.press = action_volume(VOLUME_MUTE);
    p->encoder.long_press = action_disabled();
}

static void build_defaults(void) {
    /* 0 Default */
    set_meta(&slots[0], "default", "DEFAULT");
    slots[0].keys[0] = action_key(HID_KEY_A);
    slots[0].keys[1] = action_key(HID_KEY_B);
    slots[0].keys[2] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_C);
    slots[0].keys[3] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_V);
    slots[0].keys[4] = action_key(HID_KEY_C);
    slots[0].keys[5] = action_key(HID_KEY_D);
    slots[0].keys[6] = action_key(HID_KEY_E);
    slots[0].keys[7] = action_key(HID_KEY_F);
    slots[0].keys[8] = action_key(HID_KEY_G);
    slots[0].keys[9] = action_macro(MACRO_ID_HELLO);          /* key 10: hello macro */
    slots[0].keys[10] = action_text(TEXT_ID_HELLO);         /* key 11: TEXT */
    slots[0].keys[11] = action_url(TEXT_ID_GITHUB_URL);      /* key 12: URL */

    /* 1 Gaming */
    set_meta(&slots[1], "gaming", "GAMING");
    slots[1].keys[0] = action_key(HID_KEY_W);
    slots[1].keys[1] = action_key(HID_KEY_A);
    slots[1].keys[2] = action_key(HID_KEY_S);
    slots[1].keys[3] = action_key(HID_KEY_D);
    slots[1].keys[4] = action_key(HID_KEY_Q);
    slots[1].keys[5] = action_key(HID_KEY_E);
    slots[1].keys[6] = action_key(HID_KEY_R);
    slots[1].keys[7] = action_key(HID_KEY_F);
    slots[1].keys[8] = action_key(HID_KEY_1);
    slots[1].keys[9] = action_key(HID_KEY_2);
    slots[1].keys[10] = action_key(HID_KEY_3);
    slots[1].keys[11] = action_key(HID_KEY_SPACE);
    slots[1].encoder.press = action_media(HID_USAGE_CONSUMER_PLAY_PAUSE);

    /* 2 Coding */
    set_meta(&slots[2], "coding", "CODING");
    slots[2].keys[0] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_C);
    slots[2].keys[1] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_V);
    slots[2].keys[2] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_X);
    slots[2].keys[3] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_Z);
    slots[2].keys[4] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_S);
    slots[2].keys[5] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL | KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_S);
    slots[2].keys[6] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_F);
    slots[2].keys[7] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_H);
    slots[2].keys[8] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_SLASH);
    slots[2].keys[9] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL | KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_F);
    slots[2].keys[10] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_B);
    slots[2].keys[11] = action_macro(MACRO_ID_SELECT_COPY);  /* key 12: select-all + copy */

    /* 3 Browser */
    set_meta(&slots[3], "browser", "BROWSER");
    slots[3].keys[0] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_T);
    slots[3].keys[1] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_W);
    slots[3].keys[2] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL | KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_T);
    slots[3].keys[3] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_L);
    slots[3].keys[4] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_R);
    slots[3].keys[5] = action_shortcut(KEYBOARD_MODIFIER_LEFTALT, HID_KEY_ARROW_LEFT);
    slots[3].keys[6] = action_shortcut(KEYBOARD_MODIFIER_LEFTALT, HID_KEY_ARROW_RIGHT);
    slots[3].keys[7] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_1);
    slots[3].keys[8] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_TAB);
    slots[3].keys[9] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL | KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_TAB);
    slots[3].keys[10] = action_url(TEXT_ID_GITHUB_URL);       /* key 11: URL demo */
    slots[3].keys[11] = action_media(HID_USAGE_CONSUMER_SCAN_NEXT); /* key 12: next track */

    /* 4 Photoshop-ish */
    set_meta(&slots[4], "photoshop", "PHOTOSHOP");
    slots[4].keys[0] = action_key(HID_KEY_B); /* brush */
    slots[4].keys[1] = action_key(HID_KEY_E); /* eraser */
    slots[4].keys[2] = action_key(HID_KEY_V); /* move */
    slots[4].keys[3] = action_key(HID_KEY_M); /* marquee */
    slots[4].keys[4] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_Z);
    slots[4].keys[5] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL | KEYBOARD_MODIFIER_LEFTSHIFT, HID_KEY_Z);
    slots[4].keys[6] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_S);
    slots[4].keys[7] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_T);
    slots[4].keys[8] = action_key(HID_KEY_BRACKET_LEFT);
    slots[4].keys[9] = action_key(HID_KEY_BRACKET_RIGHT);
    slots[4].keys[10] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_EQUAL);
    slots[4].keys[11] = action_shortcut(KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_MINUS);
}

void profiles_init(void) {
    build_defaults();
    active = 2; /* Coding — matches earlier OLED default */
}

uint8_t profiles_count(void) {
    return PROFILE_SLOT_COUNT;
}

uint8_t profiles_active_index(void) {
    return active;
}

const profile_t *profiles_active(void) {
    return &slots[active];
}

const profile_t *profiles_get(uint8_t index) {
    if (index >= PROFILE_SLOT_COUNT) {
        return NULL;
    }
    return &slots[index];
}


bool profiles_write_slot(uint8_t index, const profile_t *p) {
    if (index >= PROFILE_SLOT_COUNT || p == NULL) {
        return false;
    }
    slots[index] = *p;
    return true;
}

bool profiles_set_active(uint8_t index) {
    if (index >= PROFILE_SLOT_COUNT) {
        return false;
    }
    active = index;
    return true;
}

bool profiles_next(void) {
    active = (uint8_t)((active + 1) % PROFILE_SLOT_COUNT);
    return true;
}

bool profiles_prev(void) {
    active = (uint8_t)((active + PROFILE_SLOT_COUNT - 1) % PROFILE_SLOT_COUNT);
    return true;
}
