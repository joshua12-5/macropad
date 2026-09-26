#include "board_pins.h"
#include "encoder.h"
#include "matrix.h"
#include "usb_hid_app.h"

#include "hardware/uart.h"
#include "pico/stdlib.h"
#include "tusb.h"

#include <stdio.h>

#define UART_ID uart0

int main(void) {
    stdio_uart_init_full(UART_ID, DEBUG_UART_BAUD, PIN_UART_TX, PIN_UART_RX);
    sleep_ms(50);

    printf("\n=== Macropad Step 5: Encoder + Consumer HID ===\n");
    printf("Encoder: CW=VolUp  CCW=VolDown  Press=Mute\n");
    printf("Keys   : 1=A 2=B 3=Ctrl+C 4=Ctrl+V 5..12=C..J\n\n");

    matrix_init();
    encoder_init();
    usb_hid_init();

    absolute_time_t next_tick = get_absolute_time();

    while (true) {
        next_tick = delayed_by_ms(next_tick, 1);

        usb_hid_task();
        matrix_task();
        encoder_task();
        usb_hid_update_from_matrix();

        matrix_event_t mev;
        while (matrix_pop_event(&mev)) {
            const char *name =
                (mev.type == MATRIX_EVENT_PRESS)   ? "KEY PRESS  " :
                (mev.type == MATRIX_EVENT_RELEASE) ? "KEY RELEASE" : "KEY ???    ";
            printf("%s  %2u\n", name, mev.key_number);
        }

        encoder_event_t eev;
        while (encoder_pop_event(&eev)) {
            switch (eev.type) {
            case ENC_EVENT_CW:
                printf("ENC CW   -> Volume Up\n");
                usb_hid_consumer_volume_up();
                break;
            case ENC_EVENT_CCW:
                printf("ENC CCW  -> Volume Down\n");
                usb_hid_consumer_volume_down();
                break;
            case ENC_EVENT_PRESS:
                printf("ENC PRESS -> Mute\n");
                usb_hid_consumer_mute();
                break;
            case ENC_EVENT_RELEASE:
                printf("ENC RELEASE\n");
                break;
            default:
                break;
            }
        }

        sleep_until(next_tick);
    }
}
