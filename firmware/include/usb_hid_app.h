#pragma once

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

void usb_hid_init(void);
void usb_hid_task(void);

/* Held keys from active profile matrix bindings. */
void usb_hid_update_from_matrix(void);

void usb_hid_consumer_volume_up(void);
void usb_hid_consumer_volume_down(void);
void usb_hid_consumer_mute(void);
void usb_hid_consumer_usage(uint16_t usage);

/* Brief key tap for one-shot SHORTCUT/KEY / typer actions. */
void usb_hid_tap(uint8_t mods, uint8_t keycode);

/* True when no tap is in progress (safe to start another tap). */
bool usb_hid_tap_idle(void);

/* Direct keyboard report (macro KEY_DOWN/UP / sticky holds).
 * Ignored while a tap is in progress. keys may be NULL (all zero). */
void usb_hid_set_report(uint8_t mods, const uint8_t keys[6]);

#ifdef __cplusplus
}
#endif
