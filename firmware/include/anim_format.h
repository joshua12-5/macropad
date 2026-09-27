#pragma once

/*
 * OLED idle animation — on-flash format v1 (Step 24b).
 * Pure C (no Pico SDK) so the codec can be compiled on the host for tests.
 *
 * Blob = 32-byte header + frame records, stored verbatim at the start of the
 * animation flash region (see anim.h for the flash map). Little-endian.
 *
 *   off size field
 *    0   4   magic 'MPAN' (bytes 4D 50 41 4E)
 *    4   1   version = 1
 *    5   1   flags: bit0 loop (0 = play once, hold last frame)
 *    6   2   frame_count (1..ANIM_MAX_FRAMES)
 *    8   1   fps (1..ANIM_MAX_FPS)
 *    9   1   width  = 128
 *   10   1   height = 64
 *   11   1   reserved (0)
 *   12   4   data_len  = bytes of frame records after the header
 *   16   4   data_crc  = CRC32 (IEEE, as cfg_crc32) of the frame records
 *   20   8   name, ASCII, NUL padded
 *   28   4   header_crc = CRC32 of bytes 0..27
 *
 * Frame record: enc u8, reserved u8, len u16, then len payload bytes.
 *   enc 0 RAW    : len == 1024, the frame itself
 *   enc 1 RLE    : PackBits of the 1024-byte frame
 *   enc 2 DELTA  : PackBits of (frame XOR previous frame); not allowed for frame 0
 * A frame is 128x64 1bpp in SSD1306 page order: byte[x + 128*page],
 * bit (y & 7) of page (y >> 3); bit set = pixel on.
 *
 * PackBits: control c (0..127) → copy next c+1 literal bytes;
 *           c (129..255) → repeat next byte 257-c times (2..128); 128 invalid.
 */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define ANIM_MAGIC            0x4E41504Du  /* 'MPAN' LE */
#define ANIM_VERSION          1u
#define ANIM_HEADER_SIZE      32u
#define ANIM_REC_HDR_SIZE     4u
#define ANIM_FRAME_BYTES      1024u
#define ANIM_WIDTH            128u
#define ANIM_HEIGHT           64u
#define ANIM_MAX_FPS          30u
#define ANIM_MAX_FRAMES       1024u
#define ANIM_FLAG_LOOP        0x01u

#define ANIM_ENC_RAW          0u
#define ANIM_ENC_RLE          1u
#define ANIM_ENC_DELTA        2u

typedef uint32_t (*anim_crc_fn)(const uint8_t *data, size_t len);

typedef struct {
    uint8_t  version;
    uint8_t  flags;
    uint16_t frame_count;
    uint8_t  fps;
    uint32_t data_len;
    uint32_t data_crc;
    char     name[9];
} anim_header_t;

/* Parse + check header fields and header CRC (not the data CRC). */
bool anim_parse_header(const uint8_t *blob, size_t avail, anim_header_t *out,
                       anim_crc_fn crc);

/* Full validation: header, data CRC, every record decodes to exactly 1024
 * bytes, frame 0 is not DELTA, record count == frame_count, total fits avail.
 * On success *total_len = header + data_len. */
bool anim_validate(const uint8_t *blob, size_t avail, anim_crc_fn crc,
                   anim_header_t *hdr_out, uint32_t *total_len);

/* PackBits-decode exactly out_len bytes. xor_into: XOR decoded bytes into out
 * (DELTA) instead of overwriting. Returns false on malformed input or if the
 * input is not consumed exactly. */
bool anim_packbits_decode(const uint8_t *in, size_t in_len, uint8_t *out,
                          size_t out_len, bool xor_into);

/* Decode the record at rec (must be within a validated blob) into frame.
 * frame holds the previous frame for DELTA. Returns bytes consumed (header +
 * payload) or 0 on error. */
size_t anim_decode_record(const uint8_t *rec, size_t avail, uint8_t *frame);

#ifdef __cplusplus
}
#endif
