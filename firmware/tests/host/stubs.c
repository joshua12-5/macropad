/*
 * Host stand-ins for the firmware modules the OLED UI / menu touch (profiles,
 * idle-animation settings, storage, the I2C side of the OLED driver). They
 * record what was called so oled_menu_test.c can assert on it.
 */
#include "stubs.h"

#include "anim.h"
#include "config_protocol.h"
#include "oled_driver.h"
#include "profiles.h"
#include "storage.h"

#include <string.h>

uint64_t host_now_us;

host_calls_t host_calls;

/* ---- profiles ----------------------------------------------------------- */

static profile_t g_slots[PROFILE_SLOT_COUNT];
static uint8_t g_active;

void host_profiles_reset(uint8_t active) {
    static const char *names[PROFILE_SLOT_COUNT] = {"DEFAULT", "GAMING", "CODING", "BROWSER", "PHOTOSHOP"};
    static const char *ids[PROFILE_SLOT_COUNT] = {"default", "gaming", "coding", "browser", "photoshop"};
    memset(g_slots, 0, sizeof g_slots);
    for (uint8_t i = 0; i < PROFILE_SLOT_COUNT; i++) {
        g_slots[i].schema_version = PROFILE_SCHEMA_VERSION;
        strncpy(g_slots[i].id, ids[i], PROFILE_NAME_MAX - 1);
        strncpy(g_slots[i].name, names[i], PROFILE_NAME_MAX - 1);
        strncpy(g_slots[i].oled.title, names[i], PROFILE_NAME_MAX - 1);
    }
    g_active = active;
}

uint8_t profiles_count(void) {
    return PROFILE_SLOT_COUNT;
}

uint8_t profiles_active_index(void) {
    return g_active;
}

const profile_t *profiles_active(void) {
    return &g_slots[g_active];
}

const profile_t *profiles_get(uint8_t index) {
    return index < PROFILE_SLOT_COUNT ? &g_slots[index] : NULL;
}

bool profiles_set_active(uint8_t index) {
    if (index >= PROFILE_SLOT_COUNT) {
        return false;
    }
    g_active = index;
    return true;
}

/* ---- idle animation ------------------------------------------------------ */

static uint8_t g_anim_settings[ANIM_SETTINGS_SIZE] = {1, 0, 60, 0, 0x58, 0x02, 0, 0};

void anim_settings_pack(uint8_t out[ANIM_SETTINGS_SIZE]) {
    memcpy(out, g_anim_settings, ANIM_SETTINGS_SIZE);
}

bool anim_settings_unpack(const uint8_t in[ANIM_SETTINGS_SIZE]) {
    if (in[0] > 1u) {
        return false;
    }
    memcpy(g_anim_settings, in, ANIM_SETTINGS_SIZE);
    return true;
}

bool anim_screen_owned(void) {
    return false;
}

bool anim_upload_busy(void) {
    return false;
}

uint8_t anim_preview(uint8_t mode) {
    host_calls.anim_preview++;
    host_calls.last_preview_mode = mode;
    return 0;
}

void anim_info(uint8_t out[ANIM_INFO_SIZE]) {
    /* A stored 60-frame, 13 705-byte animation in the 128 KiB region. */
    memset(out, 0, ANIM_INFO_SIZE);
    const uint32_t len = 13705u, region = ANIM_REGION_SIZE;
    out[0] = 0x41u;
    out[2] = 60;
    out[6] = (uint8_t)len;
    out[7] = (uint8_t)(len >> 8);
    out[14] = (uint8_t)region;
    out[15] = (uint8_t)(region >> 8);
    out[16] = (uint8_t)(region >> 16);
    memcpy(&out[32], "bounce", 6);
}

/* ---- storage -------------------------------------------------------------- */

void storage_schedule_persist(void) {
    host_calls.persist_scheduled++;
}

bool storage_save_all(void) {
    host_calls.save_all++;
    return true;
}

bool storage_upload_busy(void) {
    return false;
}

bool storage_macro_upload_busy(void) {
    return false;
}

/* ---- OLED hardware side ------------------------------------------------------ */

bool oled_driver_init(void) {
    oled_driver_clear();
    return true;
}

bool oled_driver_ok(void) {
    return true;
}

void oled_driver_update(void) {
    host_calls.frames_pushed++;
}
