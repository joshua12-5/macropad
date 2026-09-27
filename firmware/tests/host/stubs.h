#pragma once

#include <stdint.h>

typedef struct {
    unsigned persist_scheduled;
    unsigned save_all;
    unsigned anim_preview;
    unsigned last_preview_mode;
    unsigned frames_pushed;
} host_calls_t;

extern host_calls_t host_calls;
extern uint64_t host_now_us;

void host_profiles_reset(uint8_t active);
