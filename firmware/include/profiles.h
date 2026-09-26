#pragma once

#include "profile_schema.h"

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

/* Cycle helpers for later profile-select UI. */
bool profiles_next(void);
bool profiles_prev(void);

#ifdef __cplusplus
}
#endif
