#include "anim_format.h"

#include <string.h>

static uint16_t rd16(const uint8_t *p) {
    return (uint16_t)(p[0] | ((uint16_t)p[1] << 8));
}

static uint32_t rd32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) |
           ((uint32_t)p[3] << 24);
}

bool anim_parse_header(const uint8_t *blob, size_t avail, anim_header_t *out,
                       anim_crc_fn crc) {
    if (blob == NULL || out == NULL || crc == NULL || avail < ANIM_HEADER_SIZE) {
        return false;
    }
    if (rd32(&blob[0]) != ANIM_MAGIC || blob[4] != ANIM_VERSION) {
        return false;
    }
    if (crc(blob, 28) != rd32(&blob[28])) {
        return false;
    }
    uint16_t frames = rd16(&blob[6]);
    uint8_t fps = blob[8];
    if (frames == 0 || frames > ANIM_MAX_FRAMES || fps == 0 || fps > ANIM_MAX_FPS) {
        return false;
    }
    if (blob[9] != ANIM_WIDTH || blob[10] != ANIM_HEIGHT) {
        return false;
    }
    out->version = blob[4];
    out->flags = blob[5];
    out->frame_count = frames;
    out->fps = fps;
    out->data_len = rd32(&blob[12]);
    out->data_crc = rd32(&blob[16]);
    memcpy(out->name, &blob[20], 8);
    out->name[8] = '\0';
    return true;
}

bool anim_packbits_decode(const uint8_t *in, size_t in_len, uint8_t *out,
                          size_t out_len, bool xor_into) {
    size_t i = 0;
    size_t o = 0;
    while (i < in_len) {
        uint8_t c = in[i++];
        if (c < 128u) {
            size_t n = (size_t)c + 1u;
            if (i + n > in_len || o + n > out_len) {
                return false;
            }
            for (size_t k = 0; k < n; k++) {
                out[o + k] = xor_into ? (uint8_t)(out[o + k] ^ in[i + k]) : in[i + k];
            }
            i += n;
            o += n;
        } else if (c > 128u) {
            size_t n = 257u - (size_t)c;
            if (i >= in_len || o + n > out_len) {
                return false;
            }
            uint8_t v = in[i++];
            for (size_t k = 0; k < n; k++) {
                out[o + k] = xor_into ? (uint8_t)(out[o + k] ^ v) : v;
            }
            o += n;
        } else {
            return false; /* 128 is reserved */
        }
    }
    return o == out_len;
}

size_t anim_decode_record(const uint8_t *rec, size_t avail, uint8_t *frame) {
    if (avail < ANIM_REC_HDR_SIZE) {
        return 0;
    }
    uint8_t enc = rec[0];
    uint16_t len = rd16(&rec[2]);
    if ((size_t)len + ANIM_REC_HDR_SIZE > avail) {
        return 0;
    }
    const uint8_t *pl = &rec[ANIM_REC_HDR_SIZE];
    switch (enc) {
    case ANIM_ENC_RAW:
        if (len != ANIM_FRAME_BYTES) {
            return 0;
        }
        memcpy(frame, pl, ANIM_FRAME_BYTES);
        break;
    case ANIM_ENC_RLE:
        if (!anim_packbits_decode(pl, len, frame, ANIM_FRAME_BYTES, false)) {
            return 0;
        }
        break;
    case ANIM_ENC_DELTA:
        if (!anim_packbits_decode(pl, len, frame, ANIM_FRAME_BYTES, true)) {
            return 0;
        }
        break;
    default:
        return 0;
    }
    return (size_t)len + ANIM_REC_HDR_SIZE;
}

bool anim_validate(const uint8_t *blob, size_t avail, anim_crc_fn crc,
                   anim_header_t *hdr_out, uint32_t *total_len) {
    anim_header_t h;
    if (!anim_parse_header(blob, avail, &h, crc)) {
        return false;
    }
    if (h.data_len > avail - ANIM_HEADER_SIZE) {
        return false;
    }
    const uint8_t *data = &blob[ANIM_HEADER_SIZE];
    if (crc(data, h.data_len) != h.data_crc) {
        return false;
    }
    /* Structural walk. Scratch frame on the stack would be 1 KiB — too much
     * for the 2 KiB core-0 stack in the USB callback path, so decode into a
     * static buffer (validation is never re-entered). */
    static uint8_t scratch[ANIM_FRAME_BYTES];
    memset(scratch, 0, sizeof scratch);
    size_t off = 0;
    for (uint16_t f = 0; f < h.frame_count; f++) {
        if (f == 0 && off < h.data_len && data[off] == ANIM_ENC_DELTA) {
            return false;
        }
        size_t used = anim_decode_record(&data[off], h.data_len - off, scratch);
        if (used == 0) {
            return false;
        }
        off += used;
    }
    if (off != h.data_len) {
        return false;
    }
    if (hdr_out) {
        *hdr_out = h;
    }
    if (total_len) {
        *total_len = ANIM_HEADER_SIZE + h.data_len;
    }
    return true;
}
