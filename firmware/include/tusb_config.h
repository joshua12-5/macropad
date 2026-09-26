#pragma once

/* TinyUSB device config — Pico SDK supplies CFG_TUSB_MCU / OS via the build. */

#define CFG_TUSB_RHPORT0_MODE   (OPT_MODE_DEVICE)

#define CFG_TUD_ENDPOINT0_SIZE  64

#define CFG_TUD_CDC             0
#define CFG_TUD_MSC             0
#define CFG_TUD_HID             1
#define CFG_TUD_MIDI            0
#define CFG_TUD_VENDOR          0

/* Boot keyboard report is 8 bytes; keep a little headroom. */
#define CFG_TUD_HID_EP_BUFSIZE  16
