#include "usb_hid_app.h"

#include "matrix.h"
#include "usb_descriptors.h"

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

typedef struct {
    uint8_t modifier;
    uint8_t keycode;
} key_binding_t;

static const key_binding_t BINDINGS[MATRIX_KEY_COUNT] = {
    {0x00, HID_KEY_A},
    {0x00, HID_KEY_B},
    {KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_C},
    {KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_V},
    {0x00, HID_KEY_C},
    {0x00, HID_KEY_D},
    {0x00, HID_KEY_E},
    {0x00, HID_KEY_F},
    {0x00, HID_KEY_G},
    {0x00, HID_KEY_H},
    {0x00, HID_KEY_I},
    {0x00, HID_KEY_J},
};

static uint8_t last_report[8];
static bool last_valid;

/* Consumer: send usage, then 0 on a later ready tick so the host sees a click. */
static uint16_t consumer_held;
static bool consumer_need_release;
static uint16_t consumer_queue[8];
static uint8_t cq_head, cq_tail;

static void consumer_queue_push(uint16_t usage) {
    uint8_t next = (uint8_t)((cq_head + 1) % 8);
    if (next == cq_tail) {
        return; /* drop if flooded by very fast spins */
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
    } else {
        /* Push back — rare; drop to keep ordering simple. */
    }
}

void usb_hid_task(void) {
    tud_task();
    consumer_service();
}

static void build_report(uint8_t report[8]) {
    memset(report, 0, 8);
    uint8_t mods = 0;
    uint8_t slot = 0;

    for (uint8_t kn = 1; kn <= MATRIX_KEY_COUNT; kn++) {
        if (!matrix_is_pressed(kn)) {
            continue;
        }
        const key_binding_t *b = &BINDINGS[kn - 1];
        mods |= b->modifier;
        if (b->keycode == 0 || slot >= 6) {
            continue;
        }
        bool exists = false;
        for (uint8_t i = 0; i < slot; i++) {
            if (report[2 + i] == b->keycode) {
                exists = true;
                break;
            }
        }
        if (!exists) {
            report[2 + slot++] = b->keycode;
        }
    }
    report[0] = mods;
}

void usb_hid_update_from_matrix(void) {
    if (!tud_mounted() || !tud_hid_n_ready(0)) {
        return;
    }
    /* Don't steal the IN endpoint while a consumer click is in flight. */
    if (consumer_need_release || cq_tail != cq_head) {
        return;
    }

    uint8_t report[8];
    build_report(report);
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

uint16_t tud_hid_get_report_cb(uint8_t instance, uint8_t report_id,
                               hid_report_type_t report_type,
                               uint8_t *buffer, uint16_t reqlen) {
    (void)instance;
    (void)report_id;
    (void)report_type;
    (void)buffer;
    (void)reqlen;
    return 0;
}

void tud_hid_set_report_cb(uint8_t instance, uint8_t report_id,
                           hid_report_type_t report_type,
                           uint8_t const *buffer, uint16_t bufsize) {
    (void)instance;
    (void)report_id;
    (void)report_type;
    (void)buffer;
    (void)bufsize;
}
