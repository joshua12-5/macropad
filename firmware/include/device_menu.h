#pragma once

/*
 * The macropad's on-device menu (tables for menu.c) and the shared "switch
 * profile" path.
 *
 * Tree:
 *   Menu
 *     Profiles         > one row per slot, dot on the active one
 *     Idle animation   > Preview now / Play when idle [x] / Start after > / Screen off > / Back
 *     Device info      > firmware, protocol, active slot, stored animation,
 *                        free animation flash, uptime
 *     Save device state
 *     Exit
 *
 * Controls (main.c): turn = move (wraps), short press = open / confirm,
 * hold = back one level (closes at the top), 9 s without input = close.
 */

#include "menu.h"

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define DEVICE_MENU_TIMEOUT_MS  9000u

void device_menu_open(void);
void device_menu_close(void);
bool device_menu_active(void);
void device_menu_input(menu_input_t in);   /* also restarts the idle timeout */
void device_menu_task(void);               /* timeout + live Device info refresh */
const menu_t *device_menu_state(void);

/*
 * Make slot the active profile (RAM + OLED at once), close the menu, show
 * "Switched to <title>" and schedule the debounced flash persist
 * (storage_schedule_persist: written once the slot has been stable for ~4 s,
 * skipped when flash already matches). Used by the menu, PROFILE keys and
 * SET_ACTIVE. False if slot is out of range.
 */
bool device_select_profile(uint8_t slot);

#ifdef __cplusplus
}
#endif
