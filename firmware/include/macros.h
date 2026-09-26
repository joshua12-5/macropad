#pragma once

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Step 9 hook: full macro sequencing overrides this.
 * Default weak stub in actions.c returns false (not handled).
 */
bool macros_fire(uint8_t macro_id);

#ifdef __cplusplus
}
#endif
