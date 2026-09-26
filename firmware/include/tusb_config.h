#pragma once

/* TinyUSB device config — Pico SDK supplies CFG_TUSB_MCU / OS via the build. */

#define CFG_TUSB_RHPORT0_MODE   (OPT_MODE_DEVICE)

#define CFG_TUD_ENDPOINT0_SIZE  64

#define CFG_TUD_CDC             0
#define CFG_TUD_MSC             0
#define CFG_TUD_HID             2
#define CFG_TUD_MIDI            0
#define CFG_TUD_VENDOR          0

/* Shared HID EP buffer size: vendor config needs 64; keyboard still fine. */
#define CFG_TUD_HID_EP_BUFSIZE  64
