#pragma once

#include "macro_blob.h"
#include "profile_blob.h"
#include "profile_schema.h"

#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Flash-backed profile + macro bank (Step 16/17).
 *
 * Image lives in the last 4 KiB sector of on-chip flash:
 *   STORAGE_FLASH_OFFSET = PICO_FLASH_SIZE_BYTES - FLASH_SECTOR_SIZE
 *
 * On-disk layout v2 (little-endian):
 *   magic u32 'MPFL' (bytes 4D 50 46 4C)
 *   version u16 = 2
 *   active_slot u8
 *   flags u8
 *   profile_blob[5][PROFILE_BLOB_V1_SIZE]
 *   macro_blob[5][MACRO_BLOB_V1_SIZE]
 *   crc32 of everything before the crc field
 *
 * v1 images (profiles only) are loaded and macros stay at factory defaults;
 * the next save rewrites as v2.
 */

#define STORAGE_MAGIC           0x4C46504Du  /* 'MPFL' LE */
#define STORAGE_VERSION_1       1u
#define STORAGE_VERSION_2       2u
#define STORAGE_VERSION         STORAGE_VERSION_2
#define STORAGE_FLAG_PRESENT    0x01u        /* GET_INFO flags bit0 */
#define STORAGE_FLAG_MACRO_BANK 0x02u        /* GET_INFO flags bit1 */

/* Profile upload staging (PROFILE_BEGIN / DATA / COMMIT / ABORT). */
bool storage_upload_begin(uint8_t slot, uint16_t total_len, uint32_t blob_crc);
bool storage_upload_data(uint16_t offset, const uint8_t *data, uint16_t len);
uint8_t storage_upload_commit(void);   /* CFG_ERR_* */
void storage_upload_abort(void);
bool storage_upload_busy(void);

/* Macro upload staging (MACRO_BEGIN / DATA / COMMIT / ABORT).
 * Mutually exclusive with profile upload → EBUSY if the other is active. */
bool storage_macro_upload_begin(uint8_t id, uint16_t total_len, uint32_t blob_crc);
bool storage_macro_upload_data(uint16_t offset, const uint8_t *data, uint16_t len);
uint8_t storage_macro_upload_commit(void);
void storage_macro_upload_abort(void);
bool storage_macro_upload_busy(void);

/* Slot metadata for PROFILE_GET / MACRO_GET (no full download). */
bool storage_profile_meta(uint8_t slot, uint16_t *out_len, uint32_t *out_crc);
bool storage_macro_meta(uint8_t id, uint16_t *out_len, uint32_t *out_crc);

void storage_init(void);
bool storage_save_all(void);
bool storage_save_slot(uint8_t index); /* rewrites full image (same sector) */
bool storage_loaded_from_flash(void);

#ifdef __cplusplus
}
#endif
