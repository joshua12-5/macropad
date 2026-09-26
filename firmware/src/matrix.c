#include "board_pins.h"
#include "matrix.h"

#include "hardware/gpio.h"
#include "pico/stdlib.h"

#include <string.h>

/*
 * COL2ROW matrix:
 *   Rows = outputs (idle high-Z / driven high; active row driven low)
 *   Cols = inputs with pull-ups (pressed reads 0)
 *   Diode cathode toward the ROW, anode toward the COLUMN/switch node.
 */

static const uint ROW_PINS[MATRIX_ROWS] = {PIN_ROW1, PIN_ROW2, PIN_ROW3};
static const uint COL_PINS[MATRIX_COLS] = {PIN_COL1, PIN_COL2, PIN_COL3, PIN_COL4};

/* Debounce: require this many consecutive identical raw samples (at 1 kHz). */
#define DEBOUNCE_MS 5

#define EVENT_QUEUE_SIZE 32

static bool raw[MATRIX_ROWS][MATRIX_COLS];
static bool stable[MATRIX_ROWS][MATRIX_COLS];
static uint8_t debounce_count[MATRIX_ROWS][MATRIX_COLS];

static matrix_event_t queue[EVENT_QUEUE_SIZE];
static uint8_t q_head;
static uint8_t q_tail;

static void queue_push(matrix_event_t ev) {
    uint8_t next = (uint8_t)((q_head + 1) % EVENT_QUEUE_SIZE);
    if (next == q_tail) {
        /* Drop oldest on overflow so we keep recent edges. */
        q_tail = (uint8_t)((q_tail + 1) % EVENT_QUEUE_SIZE);
    }
    queue[q_head] = ev;
    q_head = next;
}

static uint8_t key_number_from_rc(uint8_t row, uint8_t col) {
    return (uint8_t)(row * MATRIX_COLS + col + 1);
}

void matrix_init(void) {
    memset(raw, 0, sizeof raw);
    memset(stable, 0, sizeof stable);
    memset(debounce_count, 0, sizeof debounce_count);
    q_head = 0;
    q_tail = 0;

    for (uint i = 0; i < MATRIX_ROWS; i++) {
        gpio_init(ROW_PINS[i]);
        gpio_set_dir(ROW_PINS[i], GPIO_OUT);
        gpio_put(ROW_PINS[i], 1); /* idle high; inactive rows stay high */
    }

    for (uint i = 0; i < MATRIX_COLS; i++) {
        gpio_init(COL_PINS[i]);
        gpio_set_dir(COL_PINS[i], GPIO_IN);
        gpio_pull_up(COL_PINS[i]);
    }
}

static void scan_raw(void) {
    for (uint r = 0; r < MATRIX_ROWS; r++) {
        /* Drive only this row low; others high. */
        for (uint i = 0; i < MATRIX_ROWS; i++) {
            gpio_put(ROW_PINS[i], i == r ? 0 : 1);
        }

        /* Brief settle for RC / diode path (a few cycles is enough). */
        tight_loop_contents();
        busy_wait_us(5);

        for (uint c = 0; c < MATRIX_COLS; c++) {
            /* Active low: pressed == 0 */
            raw[r][c] = (gpio_get(COL_PINS[c]) == 0);
        }
    }

    /* Leave all rows high when idle between scans. */
    for (uint i = 0; i < MATRIX_ROWS; i++) {
        gpio_put(ROW_PINS[i], 1);
    }
}

void matrix_task(void) {
    scan_raw();

    for (uint r = 0; r < MATRIX_ROWS; r++) {
        for (uint c = 0; c < MATRIX_COLS; c++) {
            if (raw[r][c] == stable[r][c]) {
                debounce_count[r][c] = 0;
                continue;
            }

            debounce_count[r][c]++;
            if (debounce_count[r][c] < DEBOUNCE_MS) {
                continue;
            }

            debounce_count[r][c] = 0;
            stable[r][c] = raw[r][c];

            matrix_event_t ev = {
                .type = stable[r][c] ? MATRIX_EVENT_PRESS : MATRIX_EVENT_RELEASE,
                .key_number = key_number_from_rc((uint8_t)r, (uint8_t)c),
                .row = (uint8_t)r,
                .col = (uint8_t)c,
            };
            queue_push(ev);
        }
    }
}

bool matrix_pop_event(matrix_event_t *out) {
    if (q_tail == q_head || out == NULL) {
        return false;
    }
    *out = queue[q_tail];
    q_tail = (uint8_t)((q_tail + 1) % EVENT_QUEUE_SIZE);
    return true;
}

bool matrix_is_pressed(uint8_t key_number) {
    if (key_number < 1 || key_number > MATRIX_KEY_COUNT) {
        return false;
    }
    uint8_t idx = (uint8_t)(key_number - 1);
    uint8_t row = (uint8_t)(idx / MATRIX_COLS);
    uint8_t col = (uint8_t)(idx % MATRIX_COLS);
    return stable[row][col];
}
