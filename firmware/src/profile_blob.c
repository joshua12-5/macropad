#include "profile_blob.h"

#include <string.h>

static uint16_t rd_u16_le(const uint8_t *p) {
    return (uint16_t)(p[0] | ((uint16_t)p[1] << 8));
}

static void wr_u16_le(uint8_t *p, uint16_t v) {
    p[0] = (uint8_t)(v & 0xFFu);
    p[1] = (uint8_t)((v >> 8) & 0xFFu);
}

static void unpack_action(const uint8_t *p, action_t *a) {
    a->type = p[0];
    a->mods = p[1];
    a->keycode = p[2];
    a->aux = p[3];
    a->usage = rd_u16_le(&p[4]);
}

static void pack_action(uint8_t *p, const action_t *a) {
    p[0] = a->type;
    p[1] = a->mods;
    p[2] = a->keycode;
    p[3] = a->aux;
    wr_u16_le(&p[4], a->usage);
}

static void copy_name(char *dst, const uint8_t *src, size_t n) {
    memcpy(dst, src, n);
    dst[n - 1] = '\0';
    /* Ensure any earlier NUL is fine; force trailing NUL for safety. */
    for (size_t i = 0; i < n; i++) {
        if (dst[i] == '\0') {
            memset(&dst[i], 0, n - i);
            break;
        }
    }
}

bool profile_blob_unpack(const uint8_t *src, size_t len, profile_t *dst) {
    if (src == NULL || dst == NULL || len < PROFILE_BLOB_V1_SIZE) {
        return false;
    }

    memset(dst, 0, sizeof(*dst));
    dst->schema_version = rd_u16_le(&src[PROFILE_BLOB_OFF_SCHEMA]);
    if (dst->schema_version != PROFILE_SCHEMA_VERSION) {
        return false;
    }

    copy_name(dst->id, &src[PROFILE_BLOB_OFF_ID], PROFILE_NAME_MAX);
    copy_name(dst->name, &src[PROFILE_BLOB_OFF_NAME], PROFILE_NAME_MAX);

    for (uint8_t i = 0; i < PROFILE_BLOB_KEY_COUNT; i++) {
        unpack_action(&src[PROFILE_BLOB_OFF_KEYS + i * PROFILE_BLOB_ACTION_SIZE],
                      &dst->keys[i]);
    }

    unpack_action(&src[PROFILE_BLOB_OFF_ENCODER + 0 * PROFILE_BLOB_ACTION_SIZE],
                  &dst->encoder.cw);
    unpack_action(&src[PROFILE_BLOB_OFF_ENCODER + 1 * PROFILE_BLOB_ACTION_SIZE],
                  &dst->encoder.ccw);
    unpack_action(&src[PROFILE_BLOB_OFF_ENCODER + 2 * PROFILE_BLOB_ACTION_SIZE],
                  &dst->encoder.press);
    unpack_action(&src[PROFILE_BLOB_OFF_ENCODER + 3 * PROFILE_BLOB_ACTION_SIZE],
                  &dst->encoder.long_press);

    copy_name(dst->oled.title, &src[PROFILE_BLOB_OFF_OLED_TITLE], PROFILE_NAME_MAX);
    dst->oled.animation = src[PROFILE_BLOB_OFF_OLED_ANIM];
    return true;
}

bool profile_blob_pack(const profile_t *src, uint8_t *dst, size_t dst_len) {
    if (src == NULL || dst == NULL || dst_len < PROFILE_BLOB_V1_SIZE) {
        return false;
    }

    memset(dst, 0, PROFILE_BLOB_V1_SIZE);
    wr_u16_le(&dst[PROFILE_BLOB_OFF_SCHEMA], src->schema_version);
    memcpy(&dst[PROFILE_BLOB_OFF_ID], src->id, PROFILE_NAME_MAX);
    memcpy(&dst[PROFILE_BLOB_OFF_NAME], src->name, PROFILE_NAME_MAX);

    for (uint8_t i = 0; i < PROFILE_BLOB_KEY_COUNT; i++) {
        pack_action(&dst[PROFILE_BLOB_OFF_KEYS + i * PROFILE_BLOB_ACTION_SIZE],
                    &src->keys[i]);
    }

    pack_action(&dst[PROFILE_BLOB_OFF_ENCODER + 0 * PROFILE_BLOB_ACTION_SIZE],
                &src->encoder.cw);
    pack_action(&dst[PROFILE_BLOB_OFF_ENCODER + 1 * PROFILE_BLOB_ACTION_SIZE],
                &src->encoder.ccw);
    pack_action(&dst[PROFILE_BLOB_OFF_ENCODER + 2 * PROFILE_BLOB_ACTION_SIZE],
                &src->encoder.press);
    pack_action(&dst[PROFILE_BLOB_OFF_ENCODER + 3 * PROFILE_BLOB_ACTION_SIZE],
                &src->encoder.long_press);

    memcpy(&dst[PROFILE_BLOB_OFF_OLED_TITLE], src->oled.title, PROFILE_NAME_MAX);
    dst[PROFILE_BLOB_OFF_OLED_ANIM] = src->oled.animation;
    dst[PROFILE_BLOB_OFF_PAD] = 0;
    return true;
}
