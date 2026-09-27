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
 * Flash-backed profile + macro bank.
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
 *
 * v3 (current): the v2 body followed by an 8-byte idle-animation
 * settings block (anim.h: enabled u8, flags u8, idle_timeout_s u16,
 * blank_timeout_s u16, reserved u16), then the crc32. v1/v2 images still load
 * (idle settings at defaults); every save writes v3. The animation frames
 * themselves live in their own 128 KiB region below this sector (anim.h).
 *
 * A profile switch (SET_ACTIVE, the OLED menu, a PROFILE key) or an idle
 * setting changed on the device schedules a debounced persist (~4 s quiet);
 * CFG_CMD_SAVE_ALL / "Save device state" force an immediate rewrite.
 * The debounced persist is skipped when the flash image already equals the
 * image RAM would produce, so switching back and forth does not wear flash.
 */

#define STORAGE_MAGIC           0x4C46504Du  /* 'MPFL' LE */
#define STORAGE_VERSION_1       1u
#define STORAGE_VERSION_2       2u
#define STORAGE_VERSION_3       3u
#define STORAGE_VERSION         STORAGE_VERSION_3
#define STORAGE_FLAG_PRESENT    0x01u        /* GET_INFO flags bit0 */
#define STORAGE_FLAG_MACRO_BANK 0x02u        /* GET_INFO flags bit1 */

/* Quiet window before a debounced rewrite (ms). */
#define STORAGE_ACTIVE_DEBOUNCE_MS  4000u

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

/* PROFILE_READ / MACRO_READ: copy up to max_len bytes of the packed
 * RAM blob starting at offset. False on bad slot/id or offset >= blob size. */
bool storage_profile_read(uint8_t slot, uint16_t offset, uint8_t *out,
                          uint16_t max_len, uint16_t *out_len);
bool storage_macro_read(uint8_t id, uint16_t offset, uint8_t *out,
                        uint16_t max_len, uint16_t *out_len);

void storage_init(void);
bool storage_save_all(void);

/* Debounced flash persist of the RAM state (active slot, idle settings).
 * schedule: arm / re-arm the quiet window; task: call from the main loop;
 * cancel: clear pending (an explicit SAVE_ALL / COMMIT rewrite covers it). */
void storage_schedule_persist(void);
void storage_cancel_persist(void);
void storage_persist_task(void);

#ifdef __cplusplus
}
#endif
