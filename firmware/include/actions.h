#pragma once

#include "profile_schema.h"
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Step 7/8 bridge: execute one-shot actions (encoder / future tap).
 * Held KEY/SHORTCUT for matrix are handled via profiles_active()->keys
 * inside usb_hid_update_from_matrix().
 */
void actions_init(void);
void actions_fire(const action_t *action);

#ifdef __cplusplus
}
#endif
