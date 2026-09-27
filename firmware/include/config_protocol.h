#pragma once

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Step 15–24 — USB vendor-HID config channel (v1 framing). */

#define CFG_PROTO_MAGIC         0x4D50u   /* 'MP' little-endian */
#define CFG_PROTO_VERSION       1u

#define FW_VERSION_MAJOR        0u
#define FW_VERSION_MINOR        24u

#define CFG_REPORT_SIZE         64u
#define CFG_HEADER_SIZE         8u
#define CFG_PAYLOAD_MAX         52u
#define CFG_CRC_OFFSET          60u

#define CFG_FLAG_RESPONSE       0x01u

#define CFG_CMD_PING            0x01u
#define CFG_CMD_GET_INFO        0x02u
#define CFG_CMD_ECHO            0x03u

/* Step 16 — chunked profile upload */
#define CFG_CMD_PROFILE_BEGIN   0x10u
#define CFG_CMD_PROFILE_DATA    0x11u
#define CFG_CMD_PROFILE_COMMIT  0x12u
#define CFG_CMD_PROFILE_ABORT   0x13u
#define CFG_CMD_PROFILE_GET     0x14u  /* metadata only: slot,len,crc */
#define CFG_CMD_PROFILE_READ    0x15u  /* Step 23: slot,offset → slot,offset,bytes */

/* Step 17 — macro bank sync */
#define CFG_CMD_MACRO_BEGIN     0x20u
#define CFG_CMD_MACRO_DATA      0x21u
#define CFG_CMD_MACRO_COMMIT    0x22u
#define CFG_CMD_MACRO_ABORT     0x23u
#define CFG_CMD_MACRO_GET       0x24u  /* metadata only: id,len,crc */
#define CFG_CMD_MACRO_READ      0x25u  /* Step 23: id,offset → id,offset,bytes */

/* Step 23 — max blob bytes per PROFILE_READ / MACRO_READ response
 * (payload = id u8 + offset u16 LE + up to 48 bytes). */
#define CFG_READ_CHUNK_MAX      48u

/* Step 18 — host-driven active profile (RAM + OLED only) */
#define CFG_CMD_SET_ACTIVE      0x30u  /* payload: slot u8 */
#define CFG_CMD_GET_ACTIVE      0x31u  /* response: slot u8 */

/* Step 19 — immediate full storage rewrite (Device menu Save) */
#define CFG_CMD_SAVE_ALL        0x32u  /* empty payload */

#define CFG_CMD_NAK             0x7Fu

/* Compact err codes in NAK payload[0] (not full errno). */
#define CFG_ERR_OK              0u
#define CFG_ERR_EINVAL          1u
#define CFG_ERR_EBADMSG         2u
#define CFG_ERR_ENOSYS          3u
#define CFG_ERR_EBUSY           4u

#define CFG_INFO_FLAG_STORAGE   0x01u  /* bit0: flash profile storage present */
#define CFG_INFO_FLAG_MACRO_BANK 0x02u /* bit1: flash macro bank present */
#define CFG_INFO_FLAG_READBACK  0x04u  /* bit2: PROFILE_READ / MACRO_READ (Step 23) */

#define CFG_PRODUCT_TAG         "MACROPAD"  /* exactly 8 chars on the wire */
#define CFG_PRODUCT_TAG_LEN     8u

#define CFG_USAGE_PAGE          0xFF00u
#define CFG_USAGE               0x01u

/*
 * Frame is a flat 64-byte buffer (no packed struct) so Cortex-M0+ never
 * performs unaligned uint16/uint32 loads. Layout:
 *   [0..1] magic LE, [2] ver, [3] flags, [4] cmd, [5] seq,
 *   [6..7] length LE, [8..59] payload, [60..63] crc32 LE.
 */

uint32_t cfg_crc32(const uint8_t *data, size_t len);

/* Validate magic/version/length/crc on a 64-byte buffer. Returns CFG_ERR_* . */
uint8_t cfg_frame_validate(const uint8_t *buf);

/* Build a response frame into out[64] (sets FLAG_RESPONSE + CRC). */
void cfg_frame_build(uint8_t *out, uint8_t cmd, uint8_t seq,
                     const uint8_t *payload, uint16_t length);

/* Parse request in `req` (64 bytes), fill `resp` (64 bytes).
 * Returns true if a response should be sent. */
bool config_protocol_handle(const uint8_t *req, uint8_t *resp);

/* Deferred TX when HID IN is busy — call from main/usb task loop. */
void config_protocol_task(void);

/* Called by HID layer when vendor OUT arrives (instance 1). */
void config_protocol_on_host_report(const uint8_t *report, uint16_t len);

#ifdef __cplusplus
}
#endif
