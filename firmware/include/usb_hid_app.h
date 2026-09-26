#pragma once

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

void usb_hid_init(void);
void usb_hid_task(void);

/* Rebuild the keyboard report from current matrix state and push if changed. */
void usb_hid_update_from_matrix(void);

#ifdef __cplusplus
}
#endif
