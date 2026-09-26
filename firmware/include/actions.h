#pragma once

#include "profile_schema.h"
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Step 8 action engine: non-blocking dispatch for every schema action type.
 * Held KEY/SHORTCUT for matrix still go through usb_hid_update_from_matrix().
 * TEXT/URL/APP type via HID in actions_task(); MACRO uses macros_fire().
 */
void actions_init(void);
void actions_task(void);                 /* call from main loop every ~1 ms */
void actions_fire(const action_t *action);
bool actions_busy(void);                 /* true while typing or queue non-empty */
/* Start non-blocking typer (shared with macro MACRO_TEXT). false if busy/bad. */
bool actions_type_string(const char *s, bool append_enter);
bool actions_type_text_id(uint8_t text_id, bool append_enter);

#ifdef __cplusplus
}
#endif
