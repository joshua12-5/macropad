#pragma once

#include "board_pins.h"

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MATRIX_KEY_COUNT (MATRIX_ROWS * MATRIX_COLS)

typedef enum {
    MATRIX_EVENT_NONE = 0,
    MATRIX_EVENT_PRESS,
    MATRIX_EVENT_RELEASE
} matrix_event_type_t;

typedef struct {
    matrix_event_type_t type;
    uint8_t key_number; /* 1..12, matches physical legend */
    uint8_t row;        /* 0..2 */
    uint8_t col;        /* 0..3 */
} matrix_event_t;

void matrix_init(void);

/* Call every 1 ms from the main loop (or a 1 kHz timer). */
void matrix_task(void);

/* Non-blocking: returns true and fills *out when an edge is available. */
bool matrix_pop_event(matrix_event_t *out);

/* Live debounced state: true if key_number 1..12 is held. */
bool matrix_is_pressed(uint8_t key_number);

#ifdef __cplusplus
}
#endif
