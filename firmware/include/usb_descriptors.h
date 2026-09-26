#pragma once

#include "tusb.h"

/* IF0 report IDs (keyboard + consumer composite). */
enum {
    REPORT_ID_KEYBOARD = 1,
    REPORT_ID_CONSUMER = 2,
};

/* IF1 vendor config HID uses a single 64-byte report with NO report ID. */
enum {
    ITF_NUM_HID = 0,          /* keyboard + consumer */
    ITF_NUM_HID_CONFIG = 1,   /* vendor config channel */
    ITF_NUM_TOTAL
};

enum {
    EPNUM_HID_KB_IN     = 0x81,
    EPNUM_HID_CFG_OUT   = 0x02,
    EPNUM_HID_CFG_IN    = 0x82,
};
