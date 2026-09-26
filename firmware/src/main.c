#include "actions.h"
#include "board_pins.h"
#include "encoder.h"
#include "matrix.h"
#include "oled_driver.h"
#include "oled_ui.h"
#include "profiles.h"
#include "usb_hid_app.h"

#include "hardware/uart.h"
#include "pico/stdlib.h"
#include "tusb.h"

#include <stdio.h>

#define UART_ID uart0

/* Hold encoder 800ms → next profile (preview of Step 14; short press still mute). */
#define ENC_LONG_MS 800

int main(void) {
    stdio_uart_init_full(UART_ID, DEBUG_UART_BAUD, PIN_UART_TX, PIN_UART_RX);
    sleep_ms(50);

    printf("\n=== Macropad Step 7: Profiles ===\n");

    profiles_init();
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
    absolute_time_t enc_press_at;
    bool enc_long_fired = false;

    while (true) {
        next_tick = delayed_by_ms(next_tick, 1);

        usb_hid_task();
        matrix_task();
        encoder_task();
        oled_ui_task();
        usb_hid_update_from_matrix();

        /* Long-press encoder → next profile (hold); short press → profile press action */
        if (encoder_switch_pressed()) {
            if (!enc_held) {
                enc_held = true;
                enc_press_at = get_absolute_time();
                enc_long_fired = false;
            } else if (!enc_long_fired &&
                       absolute_time_diff_us(enc_press_at, get_absolute_time()) >=
                           (int64_t)ENC_LONG_MS * 1000) {
                enc_long_fired = true;
                profiles_next();
                p = profiles_active();
                oled_ui_set_profile_name(p->oled.title);
                oled_ui_show_toast("PROFILE", p->oled.title, 900);
                printf("Long-press -> profile %s\n", p->name);
            }
        } else {
            enc_held = false;
        }

        matrix_event_t mev;
        while (matrix_pop_event(&mev)) {
            if (mev.type == MATRIX_EVENT_PRESS) {
                printf("KEY %u (%s)\n", mev.key_number, profiles_active()->name);
                oled_ui_notify_key(mev.key_number);
                /* Non KEY/SHORTCUT actions fire on press */
                const action_t *a = &profiles_active()->keys[mev.key_number - 1];
                if (a->type != ACTION_KEY && a->type != ACTION_SHORTCUT &&
                    a->type != ACTION_DISABLED) {
                    actions_fire(a);
                }
            }
        }

        encoder_event_t eev;
        while (encoder_pop_event(&eev)) {
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
