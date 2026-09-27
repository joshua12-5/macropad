#include "storage.h"

#include "anim.h"
#include "config_protocol.h"
#include "macros.h"
#include "profiles.h"

#include "hardware/flash.h"
#include "pico/flash.h"
#include "pico/stdlib.h"

#include <stdio.h>
#include <string.h>

/*
 * Last 4 KiB sector. PICO_FLASH_SIZE_BYTES is 2 MiB on RP2040-Zero
 * (PICO_BOARD=waveshare_rp2040_zero), so offset = 0x1FF000.
 * Absolute XIP address = XIP_BASE + offset.
 * Do not call erase/program from an ISR. Step 22: the erase+program runs via
 * flash_safe_execute() (pico_flash): on this single-core build it masks IRQs
 * exactly like the old save_and_disable_interrupts() path, and it will lock
 * out core 1 safely (or refuse) if multicore is ever linked.
 */
#ifndef PICO_FLASH_SIZE_BYTES
#define PICO_FLASH_SIZE_BYTES (2u * 1024u * 1024u)
#endif

#define STORAGE_FLASH_OFFSET  (PICO_FLASH_SIZE_BYTES - FLASH_SECTOR_SIZE)

#define STORAGE_HDR_SIZE      8u
#define STORAGE_PROFILES_SIZE (PROFILE_SLOT_COUNT * PROFILE_BLOB_V1_SIZE)
#define STORAGE_MACROS_SIZE   (MACRO_BUILTIN_COUNT * MACRO_BLOB_V1_SIZE)
#define STORAGE_CRC_SIZE      4u

#define STORAGE_V1_BODY_SIZE  (STORAGE_HDR_SIZE + STORAGE_PROFILES_SIZE)
#define STORAGE_V1_IMAGE_SIZE (STORAGE_V1_BODY_SIZE + STORAGE_CRC_SIZE)

#define STORAGE_V2_BODY_SIZE  (STORAGE_HDR_SIZE + STORAGE_PROFILES_SIZE + STORAGE_MACROS_SIZE)

/* v3 = v2 body + idle-animation settings block, then CRC. */
#define STORAGE_ANIM_OFFSET   STORAGE_V2_BODY_SIZE
#define STORAGE_V3_BODY_SIZE  (STORAGE_V2_BODY_SIZE + ANIM_SETTINGS_SIZE)
#define STORAGE_IMAGE_SIZE    (STORAGE_V3_BODY_SIZE + STORAGE_CRC_SIZE)

_Static_assert(STORAGE_IMAGE_SIZE <= FLASH_SECTOR_SIZE, "storage image exceeds sector");
_Static_assert(PROFILE_BLOB_V1_SIZE == 148u, "PROFILE_BLOB_V1_SIZE mismatch");
_Static_assert(MACRO_BLOB_V1_SIZE == 162u, "MACRO_BLOB_V1_SIZE mismatch");
_Static_assert(MACRO_MAX_STEPS == 24u, "MACRO_MAX_STEPS mismatch");

enum {
    UPLOAD_NONE = 0,
    UPLOAD_PROFILE = 1,
    UPLOAD_MACRO = 2,
};

/* true while the flash v2 image matches RAM profiles+macros
 * (after a v2 load or a successful save); false after a failed save. */
static bool g_flash_in_sync;
static uint8_t g_upload_kind;
static uint8_t g_upload_slot;
static uint16_t g_upload_len;
static uint32_t g_upload_crc;
static uint16_t g_upload_got;

/* Staging fits the larger of profile (148) and macro (162) blobs. */
#define UPLOAD_BUF_MAX  MACRO_BLOB_V1_SIZE
_Static_assert(PROFILE_BLOB_V1_SIZE <= UPLOAD_BUF_MAX, "profile > upload buf");

static uint8_t g_upload_buf[UPLOAD_BUF_MAX];
static uint8_t g_upload_recv_mask[(UPLOAD_BUF_MAX + 7) / 8];

/* debounced active_slot persist (SET_ACTIVE → quiet → one rewrite). */
static bool g_active_persist_pending;
static absolute_time_t g_active_persist_deadline;

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

static uint16_t rd_u16_le(const uint8_t *p) {
    return (uint16_t)(p[0] | ((uint16_t)p[1] << 8));
}

static uint32_t rd_u32_le(const uint8_t *p) {
    return (uint32_t)p[0]
         | ((uint32_t)p[1] << 8)
         | ((uint32_t)p[2] << 16)
         | ((uint32_t)p[3] << 24);
}

static const uint8_t *flash_image(void) {
    return (const uint8_t *)(XIP_BASE + STORAGE_FLASH_OFFSET);
}

static bool image_crc_ok(const uint8_t *img, size_t body_size) {
    uint32_t expect = cfg_crc32(img, body_size);
    uint32_t got = rd_u32_le(&img[body_size]);
    return expect == got;
}

static bool image_valid_v1(const uint8_t *img) {
    if (rd_u32_le(&img[0]) != STORAGE_MAGIC) {
        return false;
    }
    if (rd_u16_le(&img[4]) != STORAGE_VERSION_1) {
        return false;
    }
    if (img[6] >= PROFILE_SLOT_COUNT) {
        return false;
    }
    return image_crc_ok(img, STORAGE_V1_BODY_SIZE);
}

static bool image_valid_v2(const uint8_t *img) {
    if (rd_u32_le(&img[0]) != STORAGE_MAGIC) {
        return false;
    }
    if (rd_u16_le(&img[4]) != STORAGE_VERSION_2) {
        return false;
    }
    if (img[6] >= PROFILE_SLOT_COUNT) {
        return false;
    }
    return image_crc_ok(img, STORAGE_V2_BODY_SIZE);
}

static bool image_valid_v3(const uint8_t *img) {
    if (rd_u32_le(&img[0]) != STORAGE_MAGIC) {
        return false;
    }
    if (rd_u16_le(&img[4]) != STORAGE_VERSION_3) {
        return false;
    }
    if (img[6] >= PROFILE_SLOT_COUNT) {
        return false;
    }
    return image_crc_ok(img, STORAGE_V3_BODY_SIZE);
}

static bool load_profiles_from_image(const uint8_t *img) {
    uint8_t active = img[6];
    for (uint8_t i = 0; i < PROFILE_SLOT_COUNT; i++) {
        profile_t tmp;
        const uint8_t *blob =
            &img[STORAGE_HDR_SIZE + i * PROFILE_BLOB_V1_SIZE];
        if (!profile_blob_unpack(blob, PROFILE_BLOB_V1_SIZE, &tmp)) {
            return false;
        }
        if (!profiles_write_slot(i, &tmp)) {
            return false;
        }
    }
    return profiles_set_active(active);
}

static bool load_macros_from_image(const uint8_t *img) {
    const uint8_t *base = &img[STORAGE_HDR_SIZE + STORAGE_PROFILES_SIZE];
    for (uint8_t i = 0; i < MACRO_BUILTIN_COUNT; i++) {
        const uint8_t *blob = &base[i * MACRO_BLOB_V1_SIZE];
        if (!macros_apply_blob(i, blob, MACRO_BLOB_V1_SIZE)) {
            return false;
        }
    }
    return true;
}

static bool build_image(uint8_t *out, uint8_t active_slot) {
    memset(out, 0, STORAGE_IMAGE_SIZE);
    wr_u32_le(&out[0], STORAGE_MAGIC);
    wr_u16_le(&out[4], STORAGE_VERSION_3);
    out[6] = active_slot;
    out[7] = 0;

    for (uint8_t i = 0; i < PROFILE_SLOT_COUNT; i++) {
        const profile_t *p = profiles_get(i);
        if (p == NULL) {
            return false;
        }
        if (!profile_blob_pack(p, &out[STORAGE_HDR_SIZE + i * PROFILE_BLOB_V1_SIZE],
                               PROFILE_BLOB_V1_SIZE)) {
            return false;
        }
    }

    uint8_t *macro_base = &out[STORAGE_HDR_SIZE + STORAGE_PROFILES_SIZE];
    for (uint8_t i = 0; i < MACRO_BUILTIN_COUNT; i++) {
        if (!macros_pack_slot(i, &macro_base[i * MACRO_BLOB_V1_SIZE],
                              MACRO_BLOB_V1_SIZE)) {
            return false;
        }
    }

    anim_settings_pack(&out[STORAGE_ANIM_OFFSET]);

    uint32_t crc = cfg_crc32(out, STORAGE_V3_BODY_SIZE);
    wr_u32_le(&out[STORAGE_V3_BODY_SIZE], crc);
    return true;
}

/*
 * one static sector buffer holds the image being written (image at
 * the front, 0xFF padding after). This used to be a 1.5 KiB stack array in
 * storage_save_all(), which pushed the USB-callback → COMMIT → save path past
 * the 2 KiB core-0 stack budget.
 */
static uint8_t g_sector_buf[FLASH_SECTOR_SIZE];

static void flash_write_sector_cb(void *param) {
    const uint8_t *sector = (const uint8_t *)param;
    flash_range_erase(STORAGE_FLASH_OFFSET, FLASH_SECTOR_SIZE);
    flash_range_program(STORAGE_FLASH_OFFSET, sector, FLASH_SECTOR_SIZE);
}

static bool program_image(uint8_t *sector) {
    memset(&sector[STORAGE_IMAGE_SIZE], 0xFF, FLASH_SECTOR_SIZE - STORAGE_IMAGE_SIZE);

    int rc = flash_safe_execute(flash_write_sector_cb, sector, 100u);
    if (rc != PICO_OK) {
        printf("stor flash_safe_execute rc=%d\n", rc);
        return false;
    }

    return image_valid_v3(flash_image());
}

void storage_init(void) {
    g_flash_in_sync = false;
    g_upload_kind = UPLOAD_NONE;
    g_active_persist_pending = false;

    const uint8_t *img = flash_image();
    anim_settings_defaults();   /* v1/v2 images carry no idle settings */

    if (image_valid_v3(img)) {
        if (!load_profiles_from_image(img) || !load_macros_from_image(img)) {
            printf("stor load default\n");
            macros_factory_reset_all();
            return;
        }
        if (!anim_settings_unpack(&img[STORAGE_ANIM_OFFSET])) {
            anim_settings_defaults();
        }
        g_flash_in_sync = true;
        printf("stor load v3\n");
        return;
    }

    if (image_valid_v2(img)) {
        if (!load_profiles_from_image(img) || !load_macros_from_image(img)) {
            printf("stor load default\n");
            macros_factory_reset_all();
            return;
        }
        /* Idle settings at defaults; the next save upgrades to v3. */
        g_flash_in_sync = false;
        printf("stor load v2\n");
        return;
    }

    if (image_valid_v1(img)) {
        if (!load_profiles_from_image(img)) {
            printf("stor load default\n");
            return;
        }
        /* Macros already seeded by macros_init(); next save upgrades to v2. */
        printf("stor load v1 (macros factory)\n");
        return;
    }

    printf("stor load default\n");
}

bool storage_save_all(void) {
    /* Any explicit rewrite supersedes a pending debounced active persist. */
    g_active_persist_pending = false;

    uint8_t *image = g_sector_buf;
    if (!build_image(image, profiles_active_index())) {
        printf("stor save fail\n");
        return false;
    }
    if (!program_image(image)) {
        g_flash_in_sync = false;
        printf("stor save fail\n");
        return false;
    }
    g_flash_in_sync = true;
    printf("stor save ok\n");
    return true;
}

void storage_schedule_active_persist(void) {
    g_active_persist_pending = true;
    g_active_persist_deadline = make_timeout_time_ms(STORAGE_ACTIVE_DEBOUNCE_MS);
}

void storage_cancel_active_persist(void) {
    g_active_persist_pending = false;
}

void storage_persist_task(void) {
    if (!g_active_persist_pending) {
        return;
    }
    if (absolute_time_diff_us(g_active_persist_deadline, get_absolute_time()) < 0) {
        return; /* quiet window not elapsed */
    }
    /* Due: one rewrite of profiles+macros+active already in RAM. */
    g_active_persist_pending = false;
    if (storage_upload_busy() || storage_macro_upload_busy()) {
        /* Defer until upload finishes — re-arm quiet window. */
        storage_schedule_active_persist();
        return;
    }
    /* nothing to do if flash already matches RAM incl. active_slot
     * (e.g. host cycled SET_ACTIVE and restored the original slot). */
    const uint8_t *img = flash_image();
    if (g_flash_in_sync && image_valid_v3(img) &&
        img[6] == profiles_active_index()) {
        printf("stor debounce skip (unchanged)\n");
        return;
    }
    printf("stor debounce save\n");
    if (!storage_save_all()) {
        printf("stor debounce save fail\n");
    }
}

bool storage_upload_busy(void) {
    return g_upload_kind == UPLOAD_PROFILE;
}

bool storage_macro_upload_busy(void) {
    return g_upload_kind == UPLOAD_MACRO;
}

static void upload_reset_mask(uint16_t len) {
    g_upload_got = 0;
    memset(g_upload_buf, 0, sizeof(g_upload_buf));
    memset(g_upload_recv_mask, 0, sizeof(g_upload_recv_mask));
    (void)len;
}

static bool upload_apply_data(uint16_t offset, const uint8_t *data, uint16_t len) {
    if (data == NULL) {
        return false;
    }
    if ((uint32_t)offset + len > g_upload_len) {
        return false;
    }
    memcpy(&g_upload_buf[offset], data, len);
    for (uint16_t i = 0; i < len; i++) {
        uint16_t bit = (uint16_t)(offset + i);
        g_upload_recv_mask[bit / 8u] |= (uint8_t)(1u << (bit % 8u));
    }
    g_upload_got = 0;
    for (uint16_t i = 0; i < g_upload_len; i++) {
        if (g_upload_recv_mask[i / 8u] & (uint8_t)(1u << (i % 8u))) {
            g_upload_got++;
        }
    }
    return true;
}

bool storage_upload_begin(uint8_t slot, uint16_t total_len, uint32_t blob_crc) {
    if (g_upload_kind != UPLOAD_NONE) {
        return false; /* EBUSY */
    }
    if (slot >= PROFILE_SLOT_COUNT || total_len != PROFILE_BLOB_V1_SIZE) {
        return false;
    }
    g_upload_kind = UPLOAD_PROFILE;
    g_upload_slot = slot;
    g_upload_len = total_len;
    g_upload_crc = blob_crc;
    upload_reset_mask(total_len);
    return true;
}

bool storage_upload_data(uint16_t offset, const uint8_t *data, uint16_t len) {
    if (g_upload_kind != UPLOAD_PROFILE) {
        return false;
    }
    return upload_apply_data(offset, data, len);
}

uint8_t storage_upload_commit(void) {
    if (g_upload_kind != UPLOAD_PROFILE) {
        return CFG_ERR_EINVAL;
    }

    if (g_upload_got != g_upload_len) {
        storage_upload_abort();
        return CFG_ERR_EINVAL;
    }

    uint32_t crc = cfg_crc32(g_upload_buf, g_upload_len);
    if (crc != g_upload_crc) {
        storage_upload_abort();
        return CFG_ERR_EBADMSG;
    }

    profile_t tmp;
    if (!profile_blob_unpack(g_upload_buf, g_upload_len, &tmp)) {
        storage_upload_abort();
        return CFG_ERR_EINVAL;
    }

    uint8_t slot = g_upload_slot;
    g_upload_kind = UPLOAD_NONE;

    if (!profiles_write_slot(slot, &tmp)) {
        return CFG_ERR_EINVAL;
    }
    if (!storage_save_all()) {
        return CFG_ERR_EBUSY;
    }
    printf("profile save ok slot=%u\n", slot);
    return CFG_ERR_OK;
}

void storage_upload_abort(void) {
    if (g_upload_kind == UPLOAD_PROFILE) {
        g_upload_kind = UPLOAD_NONE;
        g_upload_got = 0;
    }
}

bool storage_macro_upload_begin(uint8_t id, uint16_t total_len, uint32_t blob_crc) {
    if (g_upload_kind != UPLOAD_NONE) {
        return false;
    }
    if (id >= MACRO_BUILTIN_COUNT || total_len != MACRO_BLOB_V1_SIZE) {
        return false;
    }
    g_upload_kind = UPLOAD_MACRO;
    g_upload_slot = id;
    g_upload_len = total_len;
    g_upload_crc = blob_crc;
    upload_reset_mask(total_len);
    return true;
}

bool storage_macro_upload_data(uint16_t offset, const uint8_t *data, uint16_t len) {
    if (g_upload_kind != UPLOAD_MACRO) {
        return false;
    }
    return upload_apply_data(offset, data, len);
}

uint8_t storage_macro_upload_commit(void) {
    if (g_upload_kind != UPLOAD_MACRO) {
        return CFG_ERR_EINVAL;
    }

    if (g_upload_got != g_upload_len) {
        storage_macro_upload_abort();
        return CFG_ERR_EINVAL;
    }

    uint32_t crc = cfg_crc32(g_upload_buf, g_upload_len);
    if (crc != g_upload_crc) {
        storage_macro_upload_abort();
        return CFG_ERR_EBADMSG;
    }

    uint8_t id = g_upload_slot;
    if (!macros_apply_blob(id, g_upload_buf, g_upload_len)) {
        storage_macro_upload_abort();
        return CFG_ERR_EINVAL;
    }

    g_upload_kind = UPLOAD_NONE;

    if (!storage_save_all()) {
        return CFG_ERR_EBUSY;
    }
    printf("macro save ok id=%u\n", id);
    return CFG_ERR_OK;
}

void storage_macro_upload_abort(void) {
    if (g_upload_kind == UPLOAD_MACRO) {
        g_upload_kind = UPLOAD_NONE;
        g_upload_got = 0;
    }
}

bool storage_profile_meta(uint8_t slot, uint16_t *out_len, uint32_t *out_crc) {
    if (slot >= PROFILE_SLOT_COUNT || out_len == NULL || out_crc == NULL) {
        return false;
    }
    uint8_t blob[PROFILE_BLOB_V1_SIZE];
    const profile_t *p = profiles_get(slot);
    if (p == NULL || !profile_blob_pack(p, blob, sizeof(blob))) {
        return false;
    }
    *out_len = PROFILE_BLOB_V1_SIZE;
    *out_crc = cfg_crc32(blob, PROFILE_BLOB_V1_SIZE);
    return true;
}

bool storage_macro_meta(uint8_t id, uint16_t *out_len, uint32_t *out_crc) {
    if (id >= MACRO_BUILTIN_COUNT || out_len == NULL || out_crc == NULL) {
        return false;
    }
    uint8_t blob[MACRO_BLOB_V1_SIZE];
    if (!macros_pack_slot(id, blob, sizeof(blob))) {
        return false;
    }
    *out_len = MACRO_BLOB_V1_SIZE;
    *out_crc = cfg_crc32(blob, MACRO_BLOB_V1_SIZE);
    return true;
}

static bool read_window(const uint8_t *blob, uint16_t blob_len, uint16_t offset,
                        uint8_t *out, uint16_t max_len, uint16_t *out_len) {
    if (out == NULL || out_len == NULL || offset >= blob_len) {
        return false;
    }
    uint16_t n = (uint16_t)(blob_len - offset);
    if (n > max_len) {
        n = max_len;
    }
    memcpy(out, &blob[offset], n);
    *out_len = n;
    return true;
}

bool storage_profile_read(uint8_t slot, uint16_t offset, uint8_t *out,
                          uint16_t max_len, uint16_t *out_len) {
    if (slot >= PROFILE_SLOT_COUNT) {
        return false;
    }
    uint8_t blob[PROFILE_BLOB_V1_SIZE];
    const profile_t *p = profiles_get(slot);
    if (p == NULL || !profile_blob_pack(p, blob, sizeof(blob))) {
        return false;
    }
    return read_window(blob, PROFILE_BLOB_V1_SIZE, offset, out, max_len, out_len);
}

bool storage_macro_read(uint8_t id, uint16_t offset, uint8_t *out,
                        uint16_t max_len, uint16_t *out_len) {
    if (id >= MACRO_BUILTIN_COUNT) {
        return false;
    }
    uint8_t blob[MACRO_BLOB_V1_SIZE];
    if (!macros_pack_slot(id, blob, sizeof(blob))) {
        return false;
    }
    return read_window(blob, MACRO_BLOB_V1_SIZE, offset, out, max_len, out_len);
}
