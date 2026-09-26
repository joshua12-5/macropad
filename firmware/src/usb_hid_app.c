#include "usb_hid_app.h"

#include "matrix.h"
#include "profiles.h"
#include "usb_descriptors.h"
#include "config_protocol.h"

#include "class/hid/hid.h"
#include "tusb.h"

#include <string.h>

#ifndef HID_USAGE_CONSUMER_VOLUME_INCREMENT
#define HID_USAGE_CONSUMER_VOLUME_INCREMENT   0x00E9
#endif
#ifndef HID_USAGE_CONSUMER_VOLUME_DECREMENT
#define HID_USAGE_CONSUMER_VOLUME_DECREMENT   0x00EA
#endif
#ifndef HID_USAGE_CONSUMER_MUTE
#define HID_USAGE_CONSUMER_MUTE               0x00E2
#endif

static uint8_t last_report[8];
static bool last_valid;

static uint16_t consumer_held;
static bool consumer_need_release;
static uint16_t consumer_queue[8];
static uint8_t cq_head, cq_tail;

/* Simple tap state machine */
static enum { TAP_IDLE, TAP_DOWN, TAP_UP } tap_state;
static uint8_t tap_mods, tap_key;
static uint8_t tap_ticks;

static void consumer_queue_push(uint16_t usage) {
    uint8_t next = (uint8_t)((cq_head + 1) % 8);
    if (next == cq_tail) {
        return;
    }
    consumer_queue[cq_head] = usage;
    cq_head = next;
}

static bool consumer_queue_pop(uint16_t *usage) {
    if (cq_tail == cq_head) {
        return false;
    }
    *usage = consumer_queue[cq_tail];
    cq_tail = (uint8_t)((cq_tail + 1) % 8);
    return true;
}

void usb_hid_init(void) {
    memset(last_report, 0, sizeof last_report);
    last_valid = false;
    consumer_held = 0;
    consumer_need_release = false;
    cq_head = cq_tail = 0;
    tap_state = TAP_IDLE;
    tusb_init();
}

static void consumer_service(void) {
    if (!tud_mounted() || !tud_hid_n_ready(0)) {
        return;
    }

    if (consumer_need_release) {
        uint16_t zero = 0;
        if (tud_hid_n_report(0, REPORT_ID_CONSUMER, &zero, sizeof zero)) {
            consumer_need_release = false;
            consumer_held = 0;
        }
        return;
    }

    uint16_t usage;
    if (!consumer_queue_pop(&usage)) {
        return;
    }
    if (tud_hid_n_report(0, REPORT_ID_CONSUMER, &usage, sizeof usage)) {
        consumer_held = usage;
        consumer_need_release = true;
    }
}

static void tap_service(void) {
    if (tap_state == TAP_IDLE) {
        return;
    }
    if (!tud_mounted() || !tud_hid_n_ready(0)) {
        return;
    }

    if (tap_state == TAP_DOWN) {
        uint8_t keys[6] = {tap_key, 0, 0, 0, 0, 0};
        if (tud_hid_n_keyboard_report(0, REPORT_ID_KEYBOARD, tap_mods, keys)) {
            tap_state = TAP_UP;
            tap_ticks = 0;
            last_valid = false;
        }
        return;
    }

    if (tap_state == TAP_UP) {
        if (tap_ticks++ < 2) {
            return;
        }
        uint8_t keys[6] = {0};
        if (tud_hid_n_keyboard_report(0, REPORT_ID_KEYBOARD, 0, keys)) {
            tap_state = TAP_IDLE;
            last_valid = false;
        }
    }
}

void usb_hid_task(void) {
    tud_task();
    consumer_service();
    tap_service();
    config_protocol_task();
}

static void build_report_from_profile(uint8_t report[8]) {
    memset(report, 0, 8);
    const profile_t *p = profiles_active();
    if (!p) {
        return;
    }

    uint8_t mods = 0;
    uint8_t slot = 0;

    for (uint8_t kn = 1; kn <= PROFILE_KEY_COUNT; kn++) {
        if (!matrix_is_pressed(kn)) {
            continue;
        }
        const action_t *a = &p->keys[kn - 1];
        if (a->type != ACTION_KEY && a->type != ACTION_SHORTCUT) {
            continue;
        }
        mods |= a->mods;
        if (a->keycode == 0 || slot >= 6) {
            continue;
        }
        bool exists = false;
        for (uint8_t i = 0; i < slot; i++) {
            if (report[2 + i] == a->keycode) {
                exists = true;
                break;
            }
        }
        if (!exists) {
            report[2 + slot++] = a->keycode;
        }
    }
    report[0] = mods;
}

void usb_hid_update_from_matrix(void) {
    if (tap_state != TAP_IDLE) {
        return;
    }
    if (!tud_mounted() || !tud_hid_n_ready(0)) {
        return;
    }
    if (consumer_need_release || cq_tail != cq_head) {
        return;
    }

    uint8_t report[8];
    build_report_from_profile(report);
    if (last_valid && memcmp(report, last_report, 8) == 0) {
        return;
    }
    if (tud_hid_n_keyboard_report(0, REPORT_ID_KEYBOARD, report[0], &report[2])) {
        memcpy(last_report, report, 8);
        last_valid = true;
    }
}

void usb_hid_consumer_volume_up(void) {
    consumer_queue_push(HID_USAGE_CONSUMER_VOLUME_INCREMENT);
}

void usb_hid_consumer_volume_down(void) {
    consumer_queue_push(HID_USAGE_CONSUMER_VOLUME_DECREMENT);
}

void usb_hid_consumer_mute(void) {
    consumer_queue_push(HID_USAGE_CONSUMER_MUTE);
}

void usb_hid_consumer_usage(uint16_t usage) {
    consumer_queue_push(usage);
}

void usb_hid_tap(uint8_t mods, uint8_t keycode) {
    if (keycode == 0) {
        return;
    }
    tap_mods = mods;
    tap_key = keycode;
    tap_state = TAP_DOWN;
    tap_ticks = 0;
}

bool usb_hid_tap_idle(void) {
    return tap_state == TAP_IDLE;
}

void usb_hid_set_report(uint8_t mods, const uint8_t keys[6]) {
    if (tap_state != TAP_IDLE) {
        return;
    }
    if (!tud_mounted() || !tud_hid_n_ready(0)) {
        return;
    }
    uint8_t k[6] = {0};
    if (keys) {
        memcpy(k, keys, 6);
    }
    if (tud_hid_n_keyboard_report(0, REPORT_ID_KEYBOARD, mods, k)) {
        last_report[0] = mods;
        last_report[1] = 0;
        memcpy(&last_report[2], k, 6);
        last_valid = true;
    }
}


uint16_t tud_hid_get_report_cb(uint8_t instance, uint8_t report_id,
                               hid_report_type_t report_type,
                               uint8_t *buffer, uint16_t reqlen) {
    (void)instance; (void)report_id; (void)report_type;
    (void)buffer; (void)reqlen;
    /* No Feature reports in v1; interrupt IN carries responses. */
    return 0;
}

void tud_hid_set_report_cb(uint8_t instance, uint8_t report_id,
                           hid_report_type_t report_type,
                           uint8_t const *buffer, uint16_t bufsize) {
    (void)report_id;
    /* Vendor config IF: interrupt OUT (TinyUSB passes OUTPUT). */
    if (instance == ITF_NUM_HID_CONFIG &&
        report_type == HID_REPORT_TYPE_OUTPUT) {
        config_protocol_on_host_report(buffer, bufsize);
        return;
    }
    (void)buffer; (void)bufsize;
}
