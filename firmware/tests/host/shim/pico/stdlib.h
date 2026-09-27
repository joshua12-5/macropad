/*
 * Host-test shim for the few Pico SDK time helpers the OLED UI / menu code
 * uses. The clock is a plain variable the test advances (host_now_us).
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

typedef uint64_t absolute_time_t;

extern uint64_t host_now_us;

static inline absolute_time_t get_absolute_time(void) {
    return host_now_us;
}

static inline absolute_time_t make_timeout_time_ms(uint32_t ms) {
    return host_now_us + (uint64_t)ms * 1000u;
}

static inline int64_t absolute_time_diff_us(absolute_time_t from, absolute_time_t to) {
    return (int64_t)(to - from);
}

static inline uint32_t to_ms_since_boot(absolute_time_t t) {
    return (uint32_t)(t / 1000u);
}

static inline uint64_t time_us_64(void) {
    return host_now_us;
}
