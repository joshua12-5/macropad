#include "usb_descriptors.h"

#include "tusb.h"

#include <string.h>

#define USB_VID   0x2E8Au
#define USB_PID   0xC001u
#define USB_BCD   0x0114u  /* bcdDevice 1.20 (Step 20) */

tusb_desc_device_t const desc_device = {
    .bLength            = sizeof(tusb_desc_device_t),
    .bDescriptorType    = TUSB_DESC_DEVICE,
    .bcdUSB             = 0x0200,
    .bDeviceClass       = 0x00,
    .bDeviceSubClass    = 0x00,
    .bDeviceProtocol    = 0x00,
    .bMaxPacketSize0    = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor           = USB_VID,
    .idProduct          = USB_PID,
    .bcdDevice          = USB_BCD,
    .iManufacturer      = 0x01,
    .iProduct           = 0x02,
    .iSerialNumber      = 0x03,
    .bNumConfigurations = 0x01,
};

uint8_t const *tud_descriptor_device_cb(void) {
    return (uint8_t const *)&desc_device;
}

/* IF0: keyboard (id 1) + consumer (id 2) — unchanged from prior steps. */
uint8_t const desc_hid_report_kb[] = {
    TUD_HID_REPORT_DESC_KEYBOARD(HID_REPORT_ID(REPORT_ID_KEYBOARD)),
    TUD_HID_REPORT_DESC_CONSUMER(HID_REPORT_ID(REPORT_ID_CONSUMER)),
};

/*
 * IF1: vendor config HID — Usage Page 0xFF00, Usage 0x01.
 * Single 64-byte Input + Output report, no Report ID byte on the wire.
 * Host (hidapi) may still prepend/strip a leading 0x00 report-id byte.
 */
uint8_t const desc_hid_report_config[] = {
    0x06, 0x00, 0xFF,              /* Usage Page (Vendor-Defined 0xFF00) */
    0x09, 0x01,                    /* Usage (0x01) */
    0xA1, 0x01,                    /* Collection (Application) */
    0x15, 0x00,                    /*   Logical Minimum (0) */
    0x26, 0xFF, 0x00,              /*   Logical Maximum (255) */
    0x75, 0x08,                    /*   Report Size (8) */
    0x95, 0x40,                    /*   Report Count (64) */
    0x09, 0x01,                    /*   Usage (0x01) */
    0x81, 0x02,                    /*   Input (Data, Var, Abs) */
    0x09, 0x01,                    /*   Usage (0x01) */
    0x91, 0x02,                    /*   Output (Data, Var, Abs) */
    0xC0,                          /* End Collection */
};

uint8_t const *tud_hid_descriptor_report_cb(uint8_t instance) {
    if (instance == ITF_NUM_HID_CONFIG) {
        return desc_hid_report_config;
    }
    return desc_hid_report_kb;
}

#define CONFIG_TOTAL_LEN  (TUD_CONFIG_DESC_LEN + TUD_HID_DESC_LEN + TUD_HID_INOUT_DESC_LEN)

uint8_t const desc_configuration[] = {
    TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN,
                          TUSB_DESC_CONFIG_ATT_REMOTE_WAKEUP, 100),

    /* IF0: keyboard+consumer, IN only, 16-byte packets (EP buf is 64). */
    TUD_HID_DESCRIPTOR(ITF_NUM_HID, 0, HID_ITF_PROTOCOL_NONE,
                       sizeof(desc_hid_report_kb), EPNUM_HID_KB_IN, 16, 1),

    /* IF1: vendor config, IN+OUT, 64-byte packets. */
    TUD_HID_INOUT_DESCRIPTOR(ITF_NUM_HID_CONFIG, 0, HID_ITF_PROTOCOL_NONE,
                             sizeof(desc_hid_report_config),
                             EPNUM_HID_CFG_OUT, EPNUM_HID_CFG_IN, 64, 1),
};

uint8_t const *tud_descriptor_configuration_cb(uint8_t index) {
    (void)index;
    return desc_configuration;
}

char const *string_desc_arr[] = {
    (const char[]){0x09, 0x04},
    "Macropad",
    "RP2040 Macropad",
    "20400001",
};

static uint16_t _desc_str[32];

uint16_t const *tud_descriptor_string_cb(uint8_t index, uint16_t langid) {
    (void)langid;
    uint8_t chr_count;

    if (index == 0) {
        memcpy(&_desc_str[1], string_desc_arr[0], 2);
        chr_count = 1;
    } else {
        if (!(index < sizeof(string_desc_arr) / sizeof(string_desc_arr[0]))) {
            return NULL;
        }
        const char *str = string_desc_arr[index];
        chr_count = (uint8_t)strlen(str);
        if (chr_count > 31) {
            chr_count = 31;
        }
        for (uint8_t i = 0; i < chr_count; i++) {
            _desc_str[1 + i] = str[i];
        }
    }

    _desc_str[0] = (uint16_t)((TUSB_DESC_STRING << 8) | (2 * chr_count + 2));
    return _desc_str;
}
