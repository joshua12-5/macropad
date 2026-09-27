#pragma once

#include "macros.h"

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Explicit little-endian wire format for one macro slot (no C struct padding).
 * See docs/MACRO_BLOB.md.
 *
 * Layout:
 *   char name[16]          (NUL-padded)
 *   u8  step_count         (1..MACRO_MAX_STEPS, includes final END)
 *   u8  reserved           (=0)
 *   steps[MACRO_MAX_STEPS] each: op, mods, keycode, pad, arg LE
 */
#define MACRO_NAME_MAX              16u
#define MACRO_MAX_STEPS             24u
#define MACRO_STEP_WIRE_SIZE        6u
#define MACRO_BLOB_V1_SIZE          (MACRO_NAME_MAX + 2u + MACRO_MAX_STEPS * MACRO_STEP_WIRE_SIZE)
#define MACRO_BANK_BLOB_SIZE        (MACRO_BUILTIN_COUNT * MACRO_BLOB_V1_SIZE)

#define MACRO_BLOB_OFF_NAME         0u
#define MACRO_BLOB_OFF_STEP_COUNT   16u
#define MACRO_BLOB_OFF_RESERVED     17u
#define MACRO_BLOB_OFF_STEPS        18u

/* Working-set view used by pack/unpack (matches RAM slot shape). */
typedef struct {
    char name[MACRO_NAME_MAX];
    uint8_t step_count;
    macro_step_t steps[MACRO_MAX_STEPS];
} macro_blob_slot_t;

bool macro_blob_unpack(const uint8_t *src, size_t len, macro_blob_slot_t *dst);
bool macro_blob_pack(const macro_blob_slot_t *src, uint8_t *dst, size_t dst_len);

#ifdef __cplusplus
}
#endif
