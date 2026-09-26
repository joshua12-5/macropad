#include "macro_blob.h"

#include <string.h>

static uint16_t rd_u16_le(const uint8_t *p) {
    return (uint16_t)(p[0] | ((uint16_t)p[1] << 8));
}

static void wr_u16_le(uint8_t *p, uint16_t v) {
    p[0] = (uint8_t)(v & 0xFFu);
    p[1] = (uint8_t)((v >> 8) & 0xFFu);
}

static void copy_name(char *dst, const uint8_t *src, size_t n) {
    memcpy(dst, src, n);
    dst[n - 1] = '\0';
    for (size_t i = 0; i < n; i++) {
        if (dst[i] == '\0') {
            memset(&dst[i], 0, n - i);
            break;
        }
    }
}

static void unpack_step(const uint8_t *p, macro_step_t *s) {
    s->op = p[0];
    s->mods = p[1];
    s->keycode = p[2];
    s->pad = p[3];
    s->arg = rd_u16_le(&p[4]);
}

static void pack_step(uint8_t *p, const macro_step_t *s) {
    p[0] = s->op;
    p[1] = s->mods;
    p[2] = s->keycode;
    p[3] = 0;
    wr_u16_le(&p[4], s->arg);
}

bool macro_blob_unpack(const uint8_t *src, size_t len, macro_blob_slot_t *dst) {
    if (src == NULL || dst == NULL || len < MACRO_BLOB_V1_SIZE) {
        return false;
    }

    memset(dst, 0, sizeof(*dst));
    copy_name(dst->name, &src[MACRO_BLOB_OFF_NAME], MACRO_NAME_MAX);

    uint8_t count = src[MACRO_BLOB_OFF_STEP_COUNT];
    if (count < 1u || count > MACRO_MAX_STEPS) {
        return false;
    }
    dst->step_count = count;

    for (uint8_t i = 0; i < MACRO_MAX_STEPS; i++) {
        unpack_step(&src[MACRO_BLOB_OFF_STEPS + i * MACRO_STEP_WIRE_SIZE],
                    &dst->steps[i]);
    }

    /* Require a terminating END within the declared count (append if missing
     * only when there is room — otherwise reject). */
    bool has_end = false;
    for (uint8_t i = 0; i < count; i++) {
        if (dst->steps[i].op == MACRO_END) {
            has_end = true;
            /* Truncate declared count to first END inclusive. */
            dst->step_count = (uint8_t)(i + 1u);
            break;
        }
    }
    if (!has_end) {
        if (count >= MACRO_MAX_STEPS) {
            return false;
        }
        dst->steps[count].op = MACRO_END;
        dst->step_count = (uint8_t)(count + 1u);
    }

    /* Zero unused step slots for a clean working set. */
    for (uint8_t i = dst->step_count; i < MACRO_MAX_STEPS; i++) {
        memset(&dst->steps[i], 0, sizeof(dst->steps[i]));
    }
    return true;
}

bool macro_blob_pack(const macro_blob_slot_t *src, uint8_t *dst, size_t dst_len) {
    if (src == NULL || dst == NULL || dst_len < MACRO_BLOB_V1_SIZE) {
        return false;
    }

    uint8_t count = src->step_count;
    if (count < 1u || count > MACRO_MAX_STEPS) {
        return false;
    }

    memset(dst, 0, MACRO_BLOB_V1_SIZE);

    size_t namelen = strnlen(src->name, MACRO_NAME_MAX - 1u);
    memcpy(&dst[MACRO_BLOB_OFF_NAME], src->name, namelen);

    dst[MACRO_BLOB_OFF_STEP_COUNT] = count;
    dst[MACRO_BLOB_OFF_RESERVED] = 0;

    for (uint8_t i = 0; i < MACRO_MAX_STEPS; i++) {
        if (i < count) {
            pack_step(&dst[MACRO_BLOB_OFF_STEPS + i * MACRO_STEP_WIRE_SIZE],
                      &src->steps[i]);
        }
        /* else already zeroed */
    }
    return true;
}
