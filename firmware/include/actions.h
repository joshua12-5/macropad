#pragma once

#include "profile_schema.h"
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Step 8 action engine: non-blocking dispatch for every schema action type.
 * Held KEY/SHORTCUT for matrix still go through usb_hid_update_from_matrix().
 * TEXT/URL/APP type via HID in actions_task(); MACRO stubs to Step 9.
 */
void actions_init(void);
void actions_task(void);                 /* call from main loop every ~1 ms */
void actions_fire(const action_t *action);
bool actions_busy(void);                 /* true while typing or queue non-empty */

#ifdef __cplusplus
}
#endif
