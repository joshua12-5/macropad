#include "storage.h"

#include "config_protocol.h"
#include "profiles.h"

#include "hardware/flash.h"
#include "hardware/sync.h"
#include "pico/stdlib.h"

#include <stdio.h>
#include <string.h>

/*
 * Last 4 KiB sector. PICO_FLASH_SIZE_BYTES is typically 2 MiB on RP2040-Zero
 * (Waveshare), so offset = 0x1FF000. Absolute XIP address = XIP_BASE + offset.
 * Do not call erase/program from an ISR; interrupts are masked for the write.
 */
#ifndef PICO_FLASH_SIZE_BYTES
#define PICO_FLASH_SIZE_BYTES (2u * 1024u * 1024u)
#endif

#define STORAGE_FLASH_OFFSET  (PICO_FLASH_SIZE_BYTES - FLASH_SECTOR_SIZE)

#define STORAGE_HDR_SIZE      8u
#define STORAGE_BLOBS_SIZE    (PROFILE_SLOT_COUNT * PROFILE_BLOB_V1_SIZE)
#define STORAGE_CRC_SIZE      4u
#define STORAGE_IMAGE_SIZE    (STORAGE_HDR_SIZE + STORAGE_BLOBS_SIZE + STORAGE_CRC_SIZE)

_Static_assert(STORAGE_IMAGE_SIZE <= FLASH_SECTOR_SIZE, "storage image exceeds sector");
_Static_assert(PROFILE_BLOB_V1_SIZE == 148u, "PROFILE_BLOB_V1_SIZE mismatch");

static bool g_loaded_from_flash;
static bool g_upload_active;
static uint8_t g_upload_slot;
static uint16_t g_upload_len;
static uint32_t g_upload_crc;
static uint16_t g_upload_got;
static uint8_t g_upload_buf[PROFILE_BLOB_V1_SIZE];
static uint8_t g_upload_recv_mask[(PROFILE_BLOB_V1_SIZE + 7) / 8];

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

static bool image_valid(const uint8_t *img) {
    if (rd_u32_le(&img[0]) != STORAGE_MAGIC) {
        return false;
    }
    if (rd_u16_le(&img[4]) != STORAGE_VERSION) {
        return false;
    }
    uint8_t active = img[6];
    if (active >= PROFILE_SLOT_COUNT) {
        return false;
    }
    uint32_t expect = cfg_crc32(img, STORAGE_HDR_SIZE + STORAGE_BLOBS_SIZE);
    uint32_t got = rd_u32_le(&img[STORAGE_HDR_SIZE + STORAGE_BLOBS_SIZE]);
    return expect == got;
}

static bool build_image(uint8_t *out, uint8_t active_slot) {
    memset(out, 0, STORAGE_IMAGE_SIZE);
    wr_u32_le(&out[0], STORAGE_MAGIC);
    wr_u16_le(&out[4], STORAGE_VERSION);
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

    uint32_t crc = cfg_crc32(out, STORAGE_HDR_SIZE + STORAGE_BLOBS_SIZE);
    wr_u32_le(&out[STORAGE_HDR_SIZE + STORAGE_BLOBS_SIZE], crc);
    return true;
}

static bool program_image(const uint8_t *image) {
    /* Pad sector buffer so flash_range_program length is a multiple of
     * FLASH_PAGE_SIZE (256). */
    static uint8_t sector[FLASH_SECTOR_SIZE];
    memset(sector, 0xFF, sizeof(sector));
    memcpy(sector, image, STORAGE_IMAGE_SIZE);

    uint32_t ints = save_and_disable_interrupts();
    flash_range_erase(STORAGE_FLASH_OFFSET, FLASH_SECTOR_SIZE);
    flash_range_program(STORAGE_FLASH_OFFSET, sector, FLASH_SECTOR_SIZE);
    restore_interrupts(ints);

    return image_valid(flash_image());
}

void storage_init(void) {
    g_loaded_from_flash = false;
    g_upload_active = false;

    const uint8_t *img = flash_image();
    if (!image_valid(img)) {
        printf("stor load default\n");
        return;
    }

    uint8_t active = img[6];
    for (uint8_t i = 0; i < PROFILE_SLOT_COUNT; i++) {
        profile_t tmp;
        const uint8_t *blob =
            &img[STORAGE_HDR_SIZE + i * PROFILE_BLOB_V1_SIZE];
        if (!profile_blob_unpack(blob, PROFILE_BLOB_V1_SIZE, &tmp)) {
            printf("stor load default\n");
            return;
        }
        if (!profiles_write_slot(i, &tmp)) {
            printf("stor load default\n");
            return;
        }
    }
    (void)profiles_set_active(active);
    g_loaded_from_flash = true;
    printf("stor load ok\n");
}

bool storage_loaded_from_flash(void) {
    return g_loaded_from_flash;
}

bool storage_save_all(void) {
    uint8_t image[STORAGE_IMAGE_SIZE];
    if (!build_image(image, profiles_active_index())) {
        printf("stor save fail\n");
        return false;
    }
    if (!program_image(image)) {
        printf("stor save fail\n");
        return false;
    }
    g_loaded_from_flash = true;
    printf("stor save ok\n");
    return true;
}

bool storage_save_slot(uint8_t index) {
    if (index >= PROFILE_SLOT_COUNT) {
        return false;
    }
    /* Single sector holds all slots — rewrite the full image. */
    return storage_save_all();
}

bool storage_upload_busy(void) {
    return g_upload_active;
}

bool storage_upload_begin(uint8_t slot, uint16_t total_len, uint32_t blob_crc) {
    if (g_upload_active) {
        return false; /* caller maps to EBUSY */
    }
    if (slot >= PROFILE_SLOT_COUNT || total_len != PROFILE_BLOB_V1_SIZE) {
        return false; /* EINVAL */
    }
    g_upload_active = true;
    g_upload_slot = slot;
    g_upload_len = total_len;
    g_upload_crc = blob_crc;
    g_upload_got = 0;
    memset(g_upload_buf, 0, sizeof(g_upload_buf));
    memset(g_upload_recv_mask, 0, sizeof(g_upload_recv_mask));
    return true;
}

bool storage_upload_data(uint16_t offset, const uint8_t *data, uint16_t len) {
    if (!g_upload_active || data == NULL) {
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

uint8_t storage_upload_commit(void) {
    if (!g_upload_active) {
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
    g_upload_active = false;

    if (!profiles_write_slot(slot, &tmp)) {
        return CFG_ERR_EINVAL;
    }
    if (!storage_save_all()) {
        return CFG_ERR_EBUSY;
    }
    return CFG_ERR_OK;
}

void storage_upload_abort(void) {
    g_upload_active = false;
    g_upload_got = 0;
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
