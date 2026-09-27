#pragma once

#include "profile_schema.h"

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

void profiles_init(void);

uint8_t profiles_count(void);
uint8_t profiles_active_index(void);
const profile_t *profiles_active(void);
const profile_t *profiles_get(uint8_t index);

/* Returns false if index out of range. */
bool profiles_set_active(uint8_t index);

/* Replace RAM contents of one slot (host upload / flash load). */
bool profiles_write_slot(uint8_t index, const profile_t *p);

/* Cycle helpers for later profile-select UI. */

#ifdef __cplusplus
}
#endif
