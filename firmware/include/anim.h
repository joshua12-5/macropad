#pragma once

/*
 * OLED idle animation engine + flash store.
 *
 * Flash map (2 MiB, RP2040-Zero; offsets from flash start, XIP 0x10000000):
 *   0x000000 .. __flash_binary_end   firmware image (~60 KiB today)
 *   ...                               free
 *   0x1DF000 .. 0x1FEFFF (128 KiB)    ANIM region: MPAN blob (anim_format.h)
 *   0x1FF000 .. 0x1FFFFF (4 KiB)      MPFL device state (storage.h), incl.
 *                                     v3 idle settings block
 * anim_init() refuses the region (builtin animation only) if the firmware
 * image ever grows into it; CI checks the same with arm-none-eabi-nm.
 *
 * Idle state machine (anim_task, every main-loop tick):
 *   ACTIVE --(no input for idle_timeout_s, enabled)--> PLAYING (stored blob, or
 *   the builtin starfield if none) --(blank_timeout_s since last input)-->
 *   BLANK (display off). blank_timeout also applies from ACTIVE when the
 *   animation is disabled. Any key / encoder input wakes to the normal UI; the
 *   waking input is swallowed by the caller (anim_wake() returns true).
 */

#include "anim_format.h"

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define ANIM_REGION_SIZE        (128u * 1024u)
#define ANIM_REGION_OFFSET      (0x200000u - 4096u - ANIM_REGION_SIZE)  /* 0x1DF000 */
#define ANIM_SECTOR_SIZE        4096u

/* Worst case (all RAW frames): (128 KiB - 32) / (4 + 1024) = 127 frames. */
#define ANIM_MAX_FRAMES_RAW     ((ANIM_REGION_SIZE - ANIM_HEADER_SIZE) / (ANIM_REC_HDR_SIZE + ANIM_FRAME_BYTES))

#define ANIM_DEFAULT_IDLE_S     60u
#define ANIM_DEFAULT_BLANK_S    600u
#define ANIM_BUILTIN_FPS        20u

/* Persisted idle settings (MPFL v3 block, 8 bytes on the wire and in flash):
 *   enabled u8, flags u8 (reserved 0), idle_timeout_s u16, blank_timeout_s u16,
 *   reserved u16. 0 timeout = never. */
#define ANIM_SETTINGS_SIZE      8u

typedef struct {
    bool     enabled;
    uint16_t idle_timeout_s;
    uint16_t blank_timeout_s;
} anim_settings_t;

typedef enum {
    ANIM_STATE_ACTIVE = 0,   /* normal UI owns the display */
    ANIM_STATE_PLAYING,
    ANIM_STATE_BLANK,
} anim_state_t;

/* ANIM_PREVIEW modes */
#define ANIM_PREVIEW_STOP       0u
#define ANIM_PREVIEW_PLAY       1u   /* stored animation (builtin if none) */
#define ANIM_PREVIEW_BUILTIN    2u
#define ANIM_PREVIEW_BLANK      3u   /* blank now (burn-in test) */

void anim_init(void);            /* after storage_init() + oled_ui_init() */
void anim_task(void);

/* Input handling (main loop). note_input(): any key/encoder activity (also
 * held keys) restarts the idle timer. wake(): if the animation/blank owns the
 * screen, return to the normal UI and return true → caller swallows input. */
void anim_note_input(void);
bool anim_wake(void);
bool anim_screen_owned(void);

/* Settings (RAM; persisted by storage.c in the MPFL v3 image). */
void anim_settings_pack(uint8_t out[ANIM_SETTINGS_SIZE]);
bool anim_settings_unpack(const uint8_t in[ANIM_SETTINGS_SIZE]);
void anim_settings_defaults(void);

/* Upload (ANIM_BEGIN / DATA / COMMIT / ABORT). Sequential DATA only; each
 * full 4 KiB sector is erased + programmed as it fills. */
bool anim_upload_busy(void);
uint8_t anim_upload_begin(uint32_t total_len, uint32_t blob_crc);   /* CFG_ERR_* */
uint8_t anim_upload_data(uint32_t offset, const uint8_t *data, uint16_t len);
uint8_t anim_upload_commit(void);
void anim_upload_abort(void);

/* ANIM_INFO payload (ANIM_INFO_SIZE bytes, see docs/PROTOCOL.md). */
#define ANIM_INFO_SIZE          40u
void anim_info(uint8_t out[ANIM_INFO_SIZE]);

/* ANIM_READ: copy up to max_len bytes of the flash region at offset. */
bool anim_read(uint32_t offset, uint8_t *out, uint16_t max_len, uint16_t *out_len);

uint8_t anim_preview(uint8_t mode);   /* CFG_ERR_* */

#ifdef __cplusplus
}
#endif
