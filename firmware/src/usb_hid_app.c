#include "usb_hid_app.h"

#include "matrix.h"
#include "usb_descriptors.h"

#include "tusb.h"

#include <string.h>

/*
 * Step 4 hardcoded keymap (profiles replace this in Step 7+):
 *   1 → A
 *   2 → B
 *   3 → LeftCtrl + C
 *   4 → LeftCtrl + V
 *   5..12 → C..J  (so every key produces a visible character while testing)
 */

typedef struct {
    uint8_t modifier; /* HID keyboard modifier bitmap */
    uint8_t keycode;  /* HID usage, 0 = none */
} key_binding_t;

static const key_binding_t BINDINGS[MATRIX_KEY_COUNT] = {
    /* 1 */ {0x00, HID_KEY_A},
    /* 2 */ {0x00, HID_KEY_B},
    /* 3 */ {KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_C},
    /* 4 */ {KEYBOARD_MODIFIER_LEFTCTRL, HID_KEY_V},
    /* 5 */ {0x00, HID_KEY_C},
    /* 6 */ {0x00, HID_KEY_D},
    /* 7 */ {0x00, HID_KEY_E},
    /* 8 */ {0x00, HID_KEY_F},
    /* 9 */ {0x00, HID_KEY_G},
    /*10 */ {0x00, HID_KEY_H},
    /*11 */ {0x00, HID_KEY_I},
    /*12 */ {0x00, HID_KEY_J},
};

static uint8_t last_report[8];
static bool last_valid;

void usb_hid_init(void) {
    memset(last_report, 0, sizeof last_report);
    last_valid = false;
    tusb_init();
}

void usb_hid_task(void) {
    tud_task();
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
        if (b->keycode != 0 && slot < 6) {
            /* Avoid duplicate keycodes in the 6KRO array. */
            bool exists = false;
            for (uint8_t i = 0; i < slot; i++) {
                if (report[2 + i] == b->keycode) {
                    exists = true;
                    break;
                }
            }
            if (!exists) {
                report[2 + slot] = b->keycode;
                slot++;
            }
        }
    }

    report[0] = mods;
    /* report[1] reserved = 0 */
}

void usb_hid_update_from_matrix(void) {
    if (!tud_mounted() || !tud_hid_n_ready(0)) {
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

/* TinyUSB required callbacks */

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
