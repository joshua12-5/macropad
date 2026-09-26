#include "config_protocol.h"

#include "oled_ui.h"
#include "profiles.h"
#include "storage.h"
#include "usb_descriptors.h"

#include "tusb.h"

#include <stdio.h>
#include <string.h>

/* Pending response when tud_hid_n_ready(1) was false. */
static uint8_t pending_resp[CFG_REPORT_SIZE];
static bool pending_valid;

static uint16_t rd_u16_le(const uint8_t *p) {
    return (uint16_t)(p[0] | ((uint16_t)p[1] << 8));
}

static uint32_t rd_u32_le(const uint8_t *p) {
    return (uint32_t)p[0]
         | ((uint32_t)p[1] << 8)
         | ((uint32_t)p[2] << 16)
         | ((uint32_t)p[3] << 24);
}

static void wr_u16_le(uint8_t *p, uint16_t v) {
    p[0] = (uint8_t)(v & 0xFFu);
    p[1] = (uint8_t)((v >> 8) & 0xFFu);
}

static void wr_u32_le(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)(v & 0xFFu);
    p[1] = (uint8_t)((v >> 8) & 0xFFu);
    p[2] = (uint8_t)((v >> 16) & 0xFFu);
    p[3] = (uint8_t)((v >> 24) & 0xFFu);
}

uint32_t cfg_crc32(const uint8_t *data, size_t len) {
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int b = 0; b < 8; b++) {
            uint32_t mask = -(crc & 1u);
            crc = (crc >> 1) ^ (0xEDB88320u & mask);
        }
    }
    return ~crc;
}

uint8_t cfg_frame_validate(const uint8_t *buf) {
    if (rd_u16_le(&buf[0]) != CFG_PROTO_MAGIC) {
        return CFG_ERR_EBADMSG;
    }
    if (buf[2] != CFG_PROTO_VERSION) {
        return CFG_ERR_EINVAL;
    }
    uint16_t length = rd_u16_le(&buf[6]);
    if (length > CFG_PAYLOAD_MAX) {
        return CFG_ERR_EINVAL;
    }
    uint32_t expect = cfg_crc32(buf, CFG_CRC_OFFSET);
    if (expect != rd_u32_le(&buf[CFG_CRC_OFFSET])) {
        return CFG_ERR_EBADMSG;
    }
    return CFG_ERR_OK;
}

void cfg_frame_build(uint8_t *out, uint8_t cmd, uint8_t seq,
                     const uint8_t *payload, uint16_t length) {
    memset(out, 0, CFG_REPORT_SIZE);
    wr_u16_le(&out[0], CFG_PROTO_MAGIC);
    out[2] = CFG_PROTO_VERSION;
    out[3] = CFG_FLAG_RESPONSE;
    out[4] = cmd;
    out[5] = seq;
    if (length > CFG_PAYLOAD_MAX) {
        length = CFG_PAYLOAD_MAX;
    }
    wr_u16_le(&out[6], length);
    if (payload && length > 0) {
        memcpy(&out[8], payload, length);
    }
    wr_u32_le(&out[CFG_CRC_OFFSET], cfg_crc32(out, CFG_CRC_OFFSET));
}

static void send_or_queue(const uint8_t *resp) {
    if (tud_mounted() && tud_hid_n_ready(ITF_NUM_HID_CONFIG)) {
        if (tud_hid_n_report(ITF_NUM_HID_CONFIG, 0, resp, CFG_REPORT_SIZE)) {
            pending_valid = false;
            return;
        }
    }
    memcpy(pending_resp, resp, CFG_REPORT_SIZE);
    pending_valid = true;
}

static void nak(uint8_t *resp, uint8_t seq, uint8_t err) {
    uint8_t pl[1] = {err};
    cfg_frame_build(resp, CFG_CMD_NAK, seq, pl, 1);
    printf("cfg nak err=%u\n", err);
}

bool config_protocol_handle(const uint8_t *req, uint8_t *resp) {
    uint8_t verr = cfg_frame_validate(req);
    uint8_t seq = req[5];

    if (verr != CFG_ERR_OK) {
        nak(resp, seq, verr);
        return true;
    }

    /* Ignore host frames that already look like responses. */
    if (req[3] & CFG_FLAG_RESPONSE) {
        return false;
    }

    uint8_t cmd = req[4];
    uint16_t length = rd_u16_le(&req[6]);
    const uint8_t *payload = &req[8];

    switch (cmd) {
    case CFG_CMD_PING: {
        static const uint8_t pong[] = {'P', 'O', 'N', 'G'};
        cfg_frame_build(resp, CFG_CMD_PING, seq, pong, 4);
        printf("cfg ping seq=%u\n", seq);
        return true;
    }
    case CFG_CMD_GET_INFO: {
        uint8_t pl[6 + CFG_PRODUCT_TAG_LEN];
        memset(pl, 0, sizeof(pl));
        pl[0] = FW_VERSION_MAJOR;
        pl[1] = FW_VERSION_MINOR;
        pl[2] = CFG_PROTO_VERSION;
        pl[3] = profiles_active_index();
        pl[4] = profiles_count();
        pl[5] = CFG_INFO_FLAG_STORAGE;
        memcpy(&pl[6], CFG_PRODUCT_TAG, CFG_PRODUCT_TAG_LEN);
        cfg_frame_build(resp, CFG_CMD_GET_INFO, seq, pl, (uint16_t)sizeof(pl));
        printf("cfg info seq=%u\n", seq);
        return true;
    }
    case CFG_CMD_ECHO: {
        cfg_frame_build(resp, CFG_CMD_ECHO, seq, payload, length);
        printf("cfg echo seq=%u len=%u\n", seq, length);
        return true;
    }

    case CFG_CMD_PROFILE_BEGIN: {
        if (length < 7) {
            nak(resp, seq, CFG_ERR_EINVAL);
            return true;
        }
        if (storage_upload_busy()) {
            nak(resp, seq, CFG_ERR_EBUSY);
            return true;
        }
        uint8_t slot = payload[0];
        uint16_t total_len = rd_u16_le(&payload[1]);
        uint32_t blob_crc = rd_u32_le(&payload[3]);
        if (!storage_upload_begin(slot, total_len, blob_crc)) {
            nak(resp, seq, CFG_ERR_EINVAL);
            return true;
        }
        cfg_frame_build(resp, CFG_CMD_PROFILE_BEGIN, seq, NULL, 0);
        printf("cfg profile begin slot=%u len=%u\n", slot, total_len);
        return true;
    }

    case CFG_CMD_PROFILE_DATA: {
        if (length < 2) {
            nak(resp, seq, CFG_ERR_EINVAL);
            return true;
        }
        if (!storage_upload_busy()) {
            nak(resp, seq, CFG_ERR_EINVAL);
            return true;
        }
        uint16_t offset = rd_u16_le(&payload[0]);
        uint16_t data_len = (uint16_t)(length - 2u);
        if (!storage_upload_data(offset, &payload[2], data_len)) {
            nak(resp, seq, CFG_ERR_EINVAL);
            return true;
        }
        cfg_frame_build(resp, CFG_CMD_PROFILE_DATA, seq, NULL, 0);
        return true;
    }

    case CFG_CMD_PROFILE_COMMIT: {
        uint8_t err = storage_upload_commit();
        if (err != CFG_ERR_OK) {
            nak(resp, seq, err);
            return true;
        }
        /* Refresh OLED title if the active slot was rewritten. */
        const profile_t *p = profiles_active();
        if (p != NULL) {
            oled_ui_set_profile_name(p->oled.title);
        }
        cfg_frame_build(resp, CFG_CMD_PROFILE_COMMIT, seq, NULL, 0);
        printf("cfg profile commit ok\n");
        return true;
    }

    case CFG_CMD_PROFILE_ABORT: {
        storage_upload_abort();
        cfg_frame_build(resp, CFG_CMD_PROFILE_ABORT, seq, NULL, 0);
        printf("cfg profile abort\n");
        return true;
    }

    case CFG_CMD_PROFILE_GET: {
        if (length < 1) {
            nak(resp, seq, CFG_ERR_EINVAL);
            return true;
        }
        uint8_t slot = payload[0];
        uint16_t blen = 0;
        uint32_t bcrc = 0;
        if (!storage_profile_meta(slot, &blen, &bcrc)) {
            nak(resp, seq, CFG_ERR_EINVAL);
            return true;
        }
        uint8_t pl[7];
        pl[0] = slot;
        wr_u16_le(&pl[1], blen);
        wr_u32_le(&pl[3], bcrc);
        cfg_frame_build(resp, CFG_CMD_PROFILE_GET, seq, pl, 7);
        printf("cfg profile get slot=%u\n", slot);
        return true;
    }

    case CFG_CMD_MACRO_BEGIN:
    case CFG_CMD_MACRO_DATA:
    case CFG_CMD_MACRO_COMMIT:
    case CFG_CMD_MACRO_ABORT: {
        /* Full macro-bank flash sync is Step 17. */
        nak(resp, seq, CFG_ERR_ENOSYS);
        return true;
    }

    default: {
        nak(resp, seq, CFG_ERR_EINVAL);
        printf("cfg nak unknown cmd 0x%02X\n", cmd);
        return true;
    }
    }
}

void config_protocol_on_host_report(const uint8_t *report, uint16_t len) {
    if (report == NULL || len < CFG_REPORT_SIZE) {
        if (report && len >= 6) {
            uint8_t resp[CFG_REPORT_SIZE];
            nak(resp, report[5], CFG_ERR_EBADMSG);
            send_or_queue(resp);
        }
        return;
    }

    uint8_t resp[CFG_REPORT_SIZE];
    if (config_protocol_handle(report, resp)) {
        send_or_queue(resp);
    }
}

void config_protocol_task(void) {
    if (!pending_valid) {
        return;
    }
    if (!tud_mounted() || !tud_hid_n_ready(ITF_NUM_HID_CONFIG)) {
        return;
    }
    if (tud_hid_n_report(ITF_NUM_HID_CONFIG, 0, pending_resp, CFG_REPORT_SIZE)) {
        pending_valid = false;
    }
}
