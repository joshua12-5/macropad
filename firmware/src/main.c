#include "actions.h"
#include "macros.h"
#include "board_pins.h"
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

/* Hold encoder ~800 ms → enter/cancel profile select; short press confirms. */
#define ENC_LONG_MS        800
#define SELECT_TIMEOUT_MS  9000

int main(void) {
    stdio_uart_init_full(UART_ID, DEBUG_UART_BAUD, PIN_UART_TX, PIN_UART_RX);
    sleep_ms(50);

    printf("\n=== Macropad Step 22: verified firmware build ===\n");

    profiles_init();
    macros_init();   /* factory defaults into RAM before flash may override */
    storage_init();  /* v2 loads profiles+macros; v1 profiles only */
    actions_init();
    matrix_init();
    encoder_init();
    usb_hid_init();
    oled_ui_init();

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
    bool enc_held = false;
    absolute_time_t enc_press_at = get_absolute_time();  /* set on press; init silences gcc 13 -Wmaybe-uninitialized */
    bool enc_long_fired = false;
    absolute_time_t select_deadline = get_absolute_time();

    while (true) {
        next_tick = delayed_by_ms(next_tick, 1);

        usb_hid_task();
        matrix_task();
        encoder_task();
        actions_task();
        macros_task();
        oled_ui_task();
        storage_persist_task();

        const bool in_select = oled_ui_profile_select_active();

        /* Idle timeout cancels profile select without changing the active slot. */
        if (in_select &&
            absolute_time_diff_us(select_deadline, get_absolute_time()) >= 0) {
            oled_ui_profile_select_exit();
            printf("Profile select: cancel (timeout)\n");
        }

        /* While typing/macro OR profile menu open, skip matrix HID reports so
         * KEY/SHORTCUT holds don't fight the engine / menu. */
        if (!in_select && !actions_busy() && !macros_busy()) {
            usb_hid_update_from_matrix();
        }

        /* Long-press encoder → enter select (idle) or cancel (already selecting). */
        if (encoder_switch_pressed()) {
            if (!enc_held) {
                enc_held = true;
                enc_press_at = get_absolute_time();
                enc_long_fired = false;
            } else if (!enc_long_fired &&
                       absolute_time_diff_us(enc_press_at, get_absolute_time()) >=
                           (int64_t)ENC_LONG_MS * 1000) {
                enc_long_fired = true;
                if (oled_ui_profile_select_active()) {
                    oled_ui_profile_select_exit();
                    printf("Profile select: cancel (long-press)\n");
                } else {
                    uint8_t idx = profiles_active_index();
                    oled_ui_profile_select_enter(idx);
                    select_deadline = make_timeout_time_ms(SELECT_TIMEOUT_MS);
                    printf("Profile select: enter (cursor %u)\n", idx);
                }
            }
        } else {
            enc_held = false;
        }

        matrix_event_t mev;
        while (matrix_pop_event(&mev)) {
            if (oled_ui_profile_select_active()) {
                /* Mute key/profile actions while the menu is open. */
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
            if (oled_ui_profile_select_active()) {
                uint8_t count = profiles_count();
                uint8_t cur = oled_ui_profile_select_cursor();
                switch (eev.type) {
                case ENC_EVENT_CW:
                    if (count > 0) {
                        cur = (uint8_t)((cur + 1) % count);
                        oled_ui_profile_select_set_cursor(cur);
                        select_deadline = make_timeout_time_ms(SELECT_TIMEOUT_MS);
                        printf("Profile select: move -> %u\n", cur);
                    }
                    break;
                case ENC_EVENT_CCW:
                    if (count > 0) {
                        cur = (uint8_t)((cur + count - 1) % count);
                        oled_ui_profile_select_set_cursor(cur);
                        select_deadline = make_timeout_time_ms(SELECT_TIMEOUT_MS);
                        printf("Profile select: move -> %u\n", cur);
                    }
                    break;
                case ENC_EVENT_PRESS:
                    if (!enc_long_fired && count > 0) {
                        profiles_set_active(cur);
                        p = profiles_active();
                        oled_ui_profile_select_exit();
                        oled_ui_set_profile_name(p->oled.title);
                        oled_ui_show_toast("PROFILE", p->oled.title, 900);
                        printf("Profile select: confirm -> [%u] %s\n",
                               cur, p->name);
                    }
                    break;
                default:
                    break;
                }
                continue;
            }

            const profile_t *ap = profiles_active();
            switch (eev.type) {
            case ENC_EVENT_CW:
                actions_fire(&ap->encoder.cw);
                break;
            case ENC_EVENT_CCW:
                actions_fire(&ap->encoder.ccw);
                break;
            case ENC_EVENT_PRESS:
                if (!enc_long_fired) {
                    actions_fire(&ap->encoder.press);
                }
                break;
            default:
                break;
            }
        }

        sleep_until(next_tick);
    }
}
