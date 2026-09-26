#pragma once

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

void usb_hid_init(void);
void usb_hid_task(void);

/* Rebuild keyboard report from matrix; send if changed. */
void usb_hid_update_from_matrix(void);

/* Consumer Control: Volume Up / Down / Mute (auto-releases next tick). */
void usb_hid_consumer_volume_up(void);
void usb_hid_consumer_volume_down(void);
void usb_hid_consumer_mute(void);

#ifdef __cplusplus
}
#endif
