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

/* Brief key tap for one-shot SHORTCUT/KEY actions. */
void usb_hid_tap(uint8_t mods, uint8_t keycode);

#ifdef __cplusplus
}
#endif
