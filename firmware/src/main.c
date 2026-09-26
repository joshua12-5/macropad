#include "board_pins.h"
#include "encoder.h"
#include "matrix.h"
#include "oled_driver.h"
#include "oled_ui.h"
#include "usb_hid_app.h"

#include "hardware/uart.h"
#include "pico/stdlib.h"
#include "tusb.h"

#include <stdio.h>

#define UART_ID uart0

int main(void) {
    stdio_uart_init_full(UART_ID, DEBUG_UART_BAUD, PIN_UART_TX, PIN_UART_RX);
    sleep_ms(50);

    printf("\n=== Macropad Step 6: OLED + Encoder + HID ===\n");

    matrix_init();
    encoder_init();
    usb_hid_init();
    oled_ui_init();
    oled_ui_set_profile_name("CODING");

    if (oled_driver_ok()) {
        printf("OLED OK at I2C 0x%02X\n", oled_driver_address());
    } else {
        printf("OLED NOT FOUND (check wiring / power)\n");
    }

    absolute_time_t next_tick = get_absolute_time();

    while (true) {
        next_tick = delayed_by_ms(next_tick, 1);

        usb_hid_task();
        matrix_task();
        encoder_task();
        oled_ui_task();
        usb_hid_update_from_matrix();

        matrix_event_t mev;
        while (matrix_pop_event(&mev)) {
            if (mev.type == MATRIX_EVENT_PRESS) {
                printf("KEY PRESS %u\n", mev.key_number);
                oled_ui_notify_key(mev.key_number);
            }
        }

        encoder_event_t eev;
        while (encoder_pop_event(&eev)) {
            switch (eev.type) {
            case ENC_EVENT_CW:
                printf("ENC CW\n");
                usb_hid_consumer_volume_up();
                oled_ui_notify_volume(+1);
                break;
            case ENC_EVENT_CCW:
                printf("ENC CCW\n");
                usb_hid_consumer_volume_down();
                oled_ui_notify_volume(-1);
                break;
            case ENC_EVENT_PRESS:
                printf("ENC PRESS\n");
                usb_hid_consumer_mute();
                oled_ui_notify_mute();
                break;
            default:
                break;
            }
        }

        sleep_until(next_tick);
    }
}
