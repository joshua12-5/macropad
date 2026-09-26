#include "encoder.h"
#include "board_pins.h"

#include "hardware/gpio.h"
#include "hardware/sync.h"
#include "pico/stdlib.h"

#include <string.h>

/*
 * EC11 quadrature on GP2/GP3 with shared GPIO IRQ (both edges).
 * One detent typically produces 4 valid Gray-code transitions.
 * Switch on GP15, active-low, polled + debounced in encoder_task().
 */

#define DETENTS_PER_CLICK 4
#define SW_DEBOUNCE_MS    20
#define EVENT_QUEUE_SIZE  32

/* Transition table: index = (prev_ab << 2) | curr_ab */
static const int8_t QUAD_TABLE[16] = {
     0, -1, +1,  0,
    +1,  0,  0, -1,
    -1,  0,  0, +1,
     0, +1, -1,  0
};

static volatile int16_t rot_accum;
static volatile uint8_t ab_prev;
static volatile int32_t detent_cw;
static volatile int32_t detent_ccw;

static bool sw_raw;
static bool sw_stable;
static uint8_t sw_count;

static encoder_event_t queue[EVENT_QUEUE_SIZE];
static uint8_t q_head, q_tail;

static void queue_push(encoder_event_type_t type) {
    uint8_t next = (uint8_t)((q_head + 1) % EVENT_QUEUE_SIZE);
    if (next == q_tail) {
        q_tail = (uint8_t)((q_tail + 1) % EVENT_QUEUE_SIZE);
    }
    queue[q_head].type = type;
    q_head = next;
}

static uint8_t read_ab(void) {
    uint8_t a = gpio_get(PIN_ENC_A) ? 1u : 0u;
    uint8_t b = gpio_get(PIN_ENC_B) ? 1u : 0u;
    return (uint8_t)((a << 1) | b);
}

static void on_quad_edge(void) {
    uint8_t curr = read_ab();
    uint8_t idx = (uint8_t)((ab_prev << 2) | curr);
    int8_t delta = QUAD_TABLE[idx];
    ab_prev = curr;
    if (delta == 0) {
        return;
    }

    rot_accum = (int16_t)(rot_accum + delta);

    while (rot_accum >= DETENTS_PER_CLICK) {
        rot_accum = (int16_t)(rot_accum - DETENTS_PER_CLICK);
        detent_cw++;
    }
    while (rot_accum <= -DETENTS_PER_CLICK) {
        rot_accum = (int16_t)(rot_accum + DETENTS_PER_CLICK);
        detent_ccw++;
    }
}

static void gpio_irq_handler(uint gpio, uint32_t events) {
    (void)events;
    if (gpio == PIN_ENC_A || gpio == PIN_ENC_B) {
        on_quad_edge();
    }
}

void encoder_init(void) {
    rot_accum = 0;
    detent_cw = 0;
    detent_ccw = 0;
    q_head = q_tail = 0;
    sw_raw = false;
    sw_stable = false;
    sw_count = 0;

    gpio_init(PIN_ENC_A);
    gpio_set_dir(PIN_ENC_A, GPIO_IN);
    gpio_pull_up(PIN_ENC_A);

    gpio_init(PIN_ENC_B);
    gpio_set_dir(PIN_ENC_B, GPIO_IN);
    gpio_pull_up(PIN_ENC_B);

    gpio_init(PIN_ENC_SW);
    gpio_set_dir(PIN_ENC_SW, GPIO_IN);
    gpio_pull_up(PIN_ENC_SW);

    ab_prev = read_ab();

    gpio_set_irq_enabled_with_callback(
        PIN_ENC_A, GPIO_IRQ_EDGE_RISE | GPIO_IRQ_EDGE_FALL, true, &gpio_irq_handler);
    gpio_set_irq_enabled(
        PIN_ENC_B, GPIO_IRQ_EDGE_RISE | GPIO_IRQ_EDGE_FALL, true);
}

void encoder_task(void) {
    /* Move IRQ-counted detents into the event queue (safe outside ISR). */
    uint32_t irq = save_and_disable_interrupts();
    int32_t cw = detent_cw;
    int32_t ccw = detent_ccw;
    detent_cw = 0;
    detent_ccw = 0;
    restore_interrupts(irq);

    while (cw-- > 0) {
        queue_push(ENC_EVENT_CW);
    }
    while (ccw-- > 0) {
        queue_push(ENC_EVENT_CCW);
    }

    /* Active-low switch debounce */
    bool pressed = (gpio_get(PIN_ENC_SW) == 0);
    if (pressed == sw_stable) {
        sw_count = 0;
        sw_raw = pressed;
        return;
    }

    if (pressed != sw_raw) {
        sw_raw = pressed;
        sw_count = 1;
        return;
    }

    sw_count++;
    if (sw_count < SW_DEBOUNCE_MS) {
        return;
    }

    sw_count = 0;
    sw_stable = sw_raw;
    queue_push(sw_stable ? ENC_EVENT_PRESS : ENC_EVENT_RELEASE);
}

bool encoder_pop_event(encoder_event_t *out) {
    if (q_tail == q_head || out == NULL) {
        return false;
    }
    *out = queue[q_tail];
    q_tail = (uint8_t)((q_tail + 1) % EVENT_QUEUE_SIZE);
    return true;
}

bool encoder_switch_pressed(void) {
    return sw_stable;
}
