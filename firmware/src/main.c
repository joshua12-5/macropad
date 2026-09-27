#include "actions.h"
#include "anim.h"
#include "macros.h"
#include "board_pins.h"
#include "config_protocol.h"
#include "device_menu.h"
#include "encoder.h"
#include "matrix.h"
#include "oled_driver.h"
#include "oled_ui.h"
#include "profiles.h"
#include "storage.h"
#include "usb_hid_app.h"

#include "hardware/uart.h"
#include "pico/stdlib.h"
#include "tusb.h"

#include <stdio.h>

#define UART_ID uart0

/*
 * Knob button: a press shorter than ENC_HOLD_MS is a "short press" and acts
 * on release (the profile's Press action on the home screen, open / confirm in
 * the menu). Holding for ENC_HOLD_MS opens the OLED menu, or goes back one
 * level while it is open; the release that ends a hold does nothing. The
 * encoder long_press action slot is therefore reserved (never fired).
 */
#define ENC_HOLD_MS  800

int main(void) {
    stdio_uart_init_full(UART_ID, DEBUG_UART_BAUD, PIN_UART_TX, PIN_UART_RX);
    sleep_ms(50);

    printf("\n=== Macropad firmware %u.%u ===\n", (unsigned)FW_VERSION_MAJOR, (unsigned)FW_VERSION_MINOR);

    profiles_init();
    macros_init();   /* factory defaults into RAM before flash may override */
    storage_init();  /* v2 loads profiles+macros; v1 profiles only */
    actions_init();
    matrix_init();
    encoder_init();
    usb_hid_init();
    oled_ui_init();
    anim_init();     /* after storage (settings) + OLED */

    const profile_t *p = profiles_active();
    oled_ui_set_profile_name(p->oled.title);
    printf("Active profile [%u] %s (%s)\n",
           profiles_active_index(), p->id, p->name);
    for (uint8_t i = 0; i < profiles_count(); i++) {
        const profile_t *s = profiles_get(i);
        printf("  slot %u: %s\n", i, s->name);
    }

    if (oled_driver_ok()) {
        printf("OLED OK at I2C 0x%02X\n", oled_driver_address());
    } else {
        printf("OLED NOT FOUND\n");
    }

    absolute_time_t next_tick = get_absolute_time();
    bool enc_down = false;        /* a press cycle we own is in progress */
    bool enc_hold_fired = false;  /* this press already acted as a hold */
    absolute_time_t enc_press_at = get_absolute_time();  /* init silences gcc 13 -Wmaybe-uninitialized */

    while (true) {
        next_tick = delayed_by_ms(next_tick, 1);

        usb_hid_task();
        matrix_task();
        encoder_task();
        actions_task();
        macros_task();
        oled_ui_task();
        anim_task();
        oled_driver_task();   /* non-blocking framebuffer streaming */
        storage_persist_task();
        device_menu_task();   /* 9 s idle → back to the home screen */

        const bool in_menu = device_menu_active();

        /* Idle animation: held keys count as activity. A key that
         * wakes the display is swallowed until released (no HID, no action). */
        {
            bool woke = false;
            for (uint8_t kn = 1; kn <= MATRIX_KEY_COUNT; kn++) {
                if (!matrix_is_pressed(kn) || usb_hid_key_suppressed(kn)) {
                    continue;
                }
                if (woke || anim_wake()) {
                    woke = true;
                    usb_hid_suppress_key(kn);
                }
            }
            if (encoder_switch_pressed() || in_menu) {
                /* An open menu counts as activity too, so a short idle
                 * timeout never starts the animation over it; the menu
                 * closes itself after 9 s anyway. */
                anim_note_input();
            }
        }

        /* While typing/macro OR the menu is open, skip matrix HID reports so
         * KEY/SHORTCUT holds don't fight the engine / menu. */
        if (!in_menu && !actions_busy() && !macros_busy()) {
            usb_hid_update_from_matrix();
        }

        /* Hold: open the menu from home, or back one level inside it. */
        if (enc_down && !enc_hold_fired &&
            absolute_time_diff_us(enc_press_at, get_absolute_time()) >= (int64_t)ENC_HOLD_MS * 1000) {
            enc_hold_fired = true;
            if (device_menu_active()) {
                device_menu_input(MENU_IN_BACK);
            } else {
                device_menu_open();
            }
        }

        matrix_event_t mev;
        while (matrix_pop_event(&mev)) {
            anim_note_input();
            if (usb_hid_key_suppressed(mev.key_number)) {
                continue;   /* woke the idle animation: swallowed */
            }
            if (device_menu_active()) {
                /* Keys are ignored while the menu is open. */
                continue;
            }
            if (mev.type == MATRIX_EVENT_PRESS) {
                printf("KEY %u (%s)\n", mev.key_number, profiles_active()->name);
                oled_ui_notify_key(mev.key_number);
                /* Non KEY/SHORTCUT actions fire on press (queued if busy). */
                const action_t *a = &profiles_active()->keys[mev.key_number - 1];
                if (a->type != ACTION_KEY && a->type != ACTION_SHORTCUT &&
                    a->type != ACTION_DISABLED) {
                    actions_fire(a);
                }
            }
        }

        encoder_event_t eev;
        while (encoder_pop_event(&eev)) {
            if (eev.type == ENC_EVENT_RELEASE) {
                anim_note_input();
                if (!enc_down) {
                    continue;   /* end of a swallowed (waking) press */
                }
                enc_down = false;
                if (enc_hold_fired) {
                    continue;   /* the hold already acted */
                }
                if (device_menu_active()) {
                    device_menu_input(MENU_IN_SELECT);
                } else {
                    actions_fire(&profiles_active()->encoder.press);
                }
                continue;
            }
            if (anim_wake()) {
                /* Waking input is swallowed; a swallowed press is neither a
                 * short press nor a hold. */
                if (eev.type == ENC_EVENT_PRESS) {
                    enc_down = false;
                }
                continue;
            }
            const profile_t *ap = profiles_active();
            switch (eev.type) {
            case ENC_EVENT_PRESS:
                enc_down = true;
                enc_hold_fired = false;
                enc_press_at = get_absolute_time();
                break;
            case ENC_EVENT_CW:
                if (device_menu_active()) {
                    device_menu_input(MENU_IN_NEXT);
                } else {
                    actions_fire(&ap->encoder.cw);
                }
                break;
            case ENC_EVENT_CCW:
                if (device_menu_active()) {
                    device_menu_input(MENU_IN_PREV);
                } else {
                    actions_fire(&ap->encoder.ccw);
                }
                break;
            default:
                break;
            }
        }

        sleep_until(next_tick);
    }
}
