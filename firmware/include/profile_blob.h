#pragma once

#include "profile_schema.h"

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Explicit little-endian wire format for one profile (no C struct padding).
 * See protocol/PROFILE_BLOB.md.
 *
 * Layout:
 *   u16 schema_version
 *   char id[16], name[16]          (NUL-padded)
 *   12 × action (6 B each)         type, mods, keycode, aux, usage LE
 *   4  × action (encoder cw/ccw/press/long_press)
 *   char oled_title[16]
 *   u8  animation
 *   u8  pad                        (=0)
 */
#define PROFILE_BLOB_V1_SIZE        148u
#define PROFILE_BLOB_ACTION_SIZE    6u
#define PROFILE_BLOB_KEY_COUNT      12u
#define PROFILE_BLOB_ENC_COUNT      4u

/* Offsets within the blob (for documentation / host parity). */
#define PROFILE_BLOB_OFF_SCHEMA     0u
#define PROFILE_BLOB_OFF_ID         2u
#define PROFILE_BLOB_OFF_NAME       18u
#define PROFILE_BLOB_OFF_KEYS       34u
#define PROFILE_BLOB_OFF_ENCODER    106u   /* 34 + 12*6 */
#define PROFILE_BLOB_OFF_OLED_TITLE 130u   /* 106 + 4*6 */
#define PROFILE_BLOB_OFF_OLED_ANIM  146u
#define PROFILE_BLOB_OFF_PAD        147u

bool profile_blob_unpack(const uint8_t *src, size_t len, profile_t *dst);
bool profile_blob_pack(const profile_t *src, uint8_t *dst, size_t dst_len);

#ifdef __cplusplus
}
#endif
