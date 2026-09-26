#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    ENC_EVENT_NONE = 0,
    ENC_EVENT_CW,       /* clockwise detent */
    ENC_EVENT_CCW,      /* counter-clockwise detent */
    ENC_EVENT_PRESS,    /* switch pressed (debounced) */
    ENC_EVENT_RELEASE   /* switch released (debounced) */
} encoder_event_type_t;

typedef struct {
    encoder_event_type_t type;
} encoder_event_t;

void encoder_init(void);

/* Call every 1 ms: button debounce + drain IRQ detent counts into events. */
void encoder_task(void);

bool encoder_pop_event(encoder_event_t *out);

bool encoder_switch_pressed(void);

#ifdef __cplusplus
}
#endif
