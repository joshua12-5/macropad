#pragma once

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PROFILE_SCHEMA_VERSION  1
#define PROFILE_NAME_MAX        16
#define PROFILE_KEY_COUNT       12
#define PROFILE_SLOT_COUNT      5

/*
 * Action types (schema v1). Step 8 expands the engine; Step 9 adds macros.
 * Pack payloads small — these live in RAM on RP2040.
 *
 * aux usage by type:
 *   VOLUME  → volume_dir_t
 *   PROFILE → profile slot index
 *   TEXT    → text_id (firmware text_table)
 *   URL     → text_id (URL string in text_table)
 *   APP     → text_id (launch string; types string + Enter — host helper later)
 *   MACRO   → macro_id (Step 9)
 */
typedef enum {
    ACTION_DISABLED = 0,
    ACTION_KEY      = 1,  /* single HID key */
    ACTION_SHORTCUT = 2,  /* modifiers + key */
    ACTION_MACRO    = 3,  /* macro_id (Step 9) */
    ACTION_TEXT     = 4,  /* text_id → firmware string table */
    ACTION_MEDIA    = 5,  /* consumer usage */
    ACTION_VOLUME   = 6,  /* up/down/mute */
    ACTION_APP      = 7,  /* text_id launch string + Enter (best-effort) */
    ACTION_URL      = 8,  /* text_id URL + Enter */
    ACTION_PROFILE  = 9,  /* switch to profile slot */
} action_type_t;

typedef enum {
    VOLUME_UP = 1,
    VOLUME_DOWN = 2,
    VOLUME_MUTE = 3,
} volume_dir_t;

typedef struct {
    uint8_t type;       /* action_type_t */
    uint8_t mods;       /* keyboard modifier bitmap */
    uint8_t keycode;    /* HID keycode or media usage lo-byte helper */
    uint8_t aux;        /* volume_dir, profile slot, text_id, macro_id, etc. */
    uint16_t usage;     /* full consumer usage when type=MEDIA */
} action_t;

typedef enum {
    OLED_ANIM_STATIC = 0,
    OLED_ANIM_SCROLL = 1,
    OLED_ANIM_MATRIX = 2,
} oled_anim_t;

typedef struct {
    char title[PROFILE_NAME_MAX];
    uint8_t animation;  /* oled_anim_t */
} profile_oled_t;

typedef struct {
    action_t cw;
    action_t ccw;
    action_t press;
    action_t long_press; /* reserved Step 14 */
} profile_encoder_t;

typedef struct {
    uint16_t schema_version;
    char id[PROFILE_NAME_MAX];    /* stable id: "coding" */
    char name[PROFILE_NAME_MAX];  /* display: "CODING" */
    action_t keys[PROFILE_KEY_COUNT];
    profile_encoder_t encoder;
    profile_oled_t oled;
} profile_t;

static inline action_t action_disabled(void) {
    action_t a = {ACTION_DISABLED, 0, 0, 0, 0};
    return a;
}

static inline action_t action_key(uint8_t hid_keycode) {
    action_t a = {ACTION_KEY, 0, hid_keycode, 0, 0};
    return a;
}

static inline action_t action_shortcut(uint8_t mods, uint8_t hid_keycode) {
    action_t a = {ACTION_SHORTCUT, mods, hid_keycode, 0, 0};
    return a;
}

static inline action_t action_volume(volume_dir_t dir) {
    action_t a = {ACTION_VOLUME, 0, 0, (uint8_t)dir, 0};
    return a;
}

static inline action_t action_media(uint16_t usage) {
    action_t a = {ACTION_MEDIA, 0, 0, 0, usage};
    return a;
}

static inline action_t action_profile(uint8_t slot) {
    action_t a = {ACTION_PROFILE, 0, 0, slot, 0};
    return a;
}

static inline action_t action_text(uint8_t text_id) {
    action_t a = {ACTION_TEXT, 0, 0, text_id, 0};
    return a;
}

static inline action_t action_url(uint8_t text_id) {
    action_t a = {ACTION_URL, 0, 0, text_id, 0};
    return a;
}

static inline action_t action_app(uint8_t text_id) {
    action_t a = {ACTION_APP, 0, 0, text_id, 0};
    return a;
}

static inline action_t action_macro(uint8_t macro_id) {
    action_t a = {ACTION_MACRO, 0, 0, macro_id, 0};
    return a;
}

#ifdef __cplusplus
}
#endif
