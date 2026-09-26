#include "board_pins.h"
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

    printf("\n=== Macropad Step 4: USB HID Keyboard ===\n");
    printf("Board : RP2040-Zero + TinyUSB\n");
    printf("Map   : 1=A  2=B  3=Ctrl+C  4=Ctrl+V  5..12=C..J\n");
    printf("Open a text editor on the host and press keys.\n\n");

    matrix_init();
    usb_hid_init();

    absolute_time_t next_tick = get_absolute_time();

    while (true) {
        next_tick = delayed_by_ms(next_tick, 1);

        usb_hid_task();   /* TinyUSB event pump — never block this */
        matrix_task();
        usb_hid_update_from_matrix();

        matrix_event_t ev;
        while (matrix_pop_event(&ev)) {
            const char *name =
                (ev.type == MATRIX_EVENT_PRESS)   ? "PRESS  " :
                (ev.type == MATRIX_EVENT_RELEASE) ? "RELEASE" : "???    ";
            printf("%s  key %2u  usb=%s\n",
                   name, ev.key_number,
                   tud_mounted() ? "mounted" : "not-mounted");
        }

        sleep_until(next_tick);
    }
}
