#include "anim.h"

#include "config_protocol.h"
#include "oled_driver.h"
#include "oled_ui.h"

#include "hardware/flash.h"
#include "pico/flash.h"
#include "pico/stdlib.h"

#include <stdio.h>
#include <string.h>

#ifndef PICO_FLASH_SIZE_BYTES
#define PICO_FLASH_SIZE_BYTES (2u * 1024u * 1024u)
#endif

_Static_assert(ANIM_SECTOR_SIZE == FLASH_SECTOR_SIZE, "sector size");
_Static_assert(ANIM_REGION_OFFSET + ANIM_REGION_SIZE + FLASH_SECTOR_SIZE == PICO_FLASH_SIZE_BYTES,
               "ANIM region must sit directly below the MPFL sector");
_Static_assert(ANIM_REGION_SIZE % FLASH_SECTOR_SIZE == 0, "region not sector aligned");
_Static_assert(ANIM_FRAME_BYTES == OLED_WIDTH * OLED_HEIGHT / 8, "frame size");

extern char __flash_binary_end;

/* ---- state ------------------------------------------------------------- */

static anim_settings_t g_set;
static anim_state_t g_state;
static bool g_region_ok;          /* firmware image does not reach the region */
static uint64_t g_last_input_us;

/* Stored animation (validated copy of the header). */
static bool g_have_stored;
static anim_header_t g_hdr;
static uint32_t g_total_len;
static uint32_t g_total_crc;

/* Playback */
static bool g_playing_builtin;
static bool g_preview;
static uint8_t g_frame[ANIM_FRAME_BYTES];
static uint16_t g_frame_idx;
static uint32_t g_rec_off;
static bool g_hold;               /* non-looping animation finished */
static uint64_t g_next_frame_us;
static uint32_t g_period_us;

/* Upload */
static bool g_up_active;
static uint32_t g_up_total;
static uint32_t g_up_crc;
static uint32_t g_up_got;
static uint32_t g_up_sectors_written;
static uint8_t g_up_sector[ANIM_SECTOR_SIZE];

static const uint8_t *region(void) {
    return (const uint8_t *)(XIP_BASE + ANIM_REGION_OFFSET);
}

static uint32_t crc_fn(const uint8_t *data, size_t len) {
    return cfg_crc32(data, len);
}

static void wr16(uint8_t *p, uint16_t v) {
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
}

static void wr32(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16);
    p[3] = (uint8_t)(v >> 24);
}

/* ---- settings ---------------------------------------------------------- */

void anim_settings_defaults(void) {
    g_set.enabled = true;
    g_set.idle_timeout_s = ANIM_DEFAULT_IDLE_S;
    g_set.blank_timeout_s = ANIM_DEFAULT_BLANK_S;
}

void anim_settings_pack(uint8_t out[ANIM_SETTINGS_SIZE]) {
    memset(out, 0, ANIM_SETTINGS_SIZE);
    out[0] = g_set.enabled ? 1u : 0u;
    out[1] = 0;
    wr16(&out[2], g_set.idle_timeout_s);
    wr16(&out[4], g_set.blank_timeout_s);
}

bool anim_settings_unpack(const uint8_t in[ANIM_SETTINGS_SIZE]) {
    if (in[0] > 1u) {
        return false;
    }
    g_set.enabled = in[0] != 0;
    g_set.idle_timeout_s = (uint16_t)(in[2] | (in[3] << 8));
    g_set.blank_timeout_s = (uint16_t)(in[4] | (in[5] << 8));
    return true;
}

/* ---- stored animation -------------------------------------------------- */

static void load_stored(void) {
    g_have_stored = false;
    if (!g_region_ok) {
        return;
    }
    anim_header_t h;
    uint32_t total = 0;
    if (anim_validate(region(), ANIM_REGION_SIZE, crc_fn, &h, &total)) {
        g_hdr = h;
        g_total_len = total;
        g_total_crc = cfg_crc32(region(), total);
        g_have_stored = true;
        printf("anim stored: %u frames @ %u fps, %lu B '%s'\n", h.frame_count, h.fps,
               (unsigned long)total, h.name);
    } else {
        printf("anim: no stored animation (builtin)\n");
    }
}

/* ---- builtin starfield --------------------------------------------------- */

#define STARS 48
static int16_t star_x[STARS];
static int16_t star_y[STARS];
static uint8_t star_z[STARS];
static uint32_t rng_state = 0x2545F491u;

static uint32_t rnd(void) {
    uint32_t x = rng_state;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    rng_state = x;
    return x;
}

static void star_spawn(int i, bool any_depth) {
    star_x[i] = (int16_t)((int)(rnd() % 512u) - 256);
    star_y[i] = (int16_t)((int)(rnd() % 256u) - 128);
    star_z[i] = (uint8_t)(any_depth ? (4u + rnd() % 60u) : (48u + rnd() % 16u));
}

static void frame_set(int x, int y) {
    if ((unsigned)x < ANIM_WIDTH && (unsigned)y < ANIM_HEIGHT) {
        g_frame[x + (y >> 3) * ANIM_WIDTH] |= (uint8_t)(1u << (y & 7));
    }
}

static void builtin_reset(void) {
    for (int i = 0; i < STARS; i++) {
        star_spawn(i, true);
    }
}

static void builtin_render(void) {
    memset(g_frame, 0, sizeof g_frame);
    for (int i = 0; i < STARS; i++) {
        if (star_z[i] <= 2) {
            star_spawn(i, false);
        }
        star_z[i] = (uint8_t)(star_z[i] - 2);
        int z = star_z[i] ? star_z[i] : 1;
        int px = 64 + (star_x[i] * 8) / z;
        int py = 32 + (star_y[i] * 8) / z;
        if ((unsigned)px >= ANIM_WIDTH || (unsigned)py >= ANIM_HEIGHT) {
            star_spawn(i, false);
            continue;
        }
        frame_set(px, py);
        if (z < 20) {
            frame_set(px + 1, py);
        }
        if (z < 10) {
            frame_set(px, py + 1);
            frame_set(px + 1, py + 1);
        }
    }
}

/* ---- playback ------------------------------------------------------------ */

static void release_screen(void) {
    if (g_state == ANIM_STATE_BLANK) {
        oled_driver_display_on(true);
    }
    g_state = ANIM_STATE_ACTIVE;
    g_preview = false;
    oled_ui_invalidate();
}

static void start_play(bool builtin, bool preview) {
    if (g_state == ANIM_STATE_BLANK) {
        oled_driver_display_on(true);
    }
    g_playing_builtin = builtin || !g_have_stored;
    g_preview = preview;
    g_state = ANIM_STATE_PLAYING;
    g_frame_idx = 0;
    g_rec_off = 0;
    g_hold = false;
    memset(g_frame, 0, sizeof g_frame);
    uint8_t fps = g_playing_builtin ? ANIM_BUILTIN_FPS : g_hdr.fps;
    g_period_us = 1000000u / fps;
    g_next_frame_us = time_us_64();
    if (g_playing_builtin) {
        builtin_reset();
    }
    printf("anim play %s%s\n", g_playing_builtin ? "builtin" : "stored",
           preview ? " (preview)" : "");
}

static void go_blank(void) {
    g_state = ANIM_STATE_BLANK;
    g_preview = false;
    oled_driver_display_on(false);
    printf("anim blank\n");
}

static bool next_frame(void) {
    if (g_playing_builtin) {
        builtin_render();
        return true;
    }
    if (g_hold) {
        return false;
    }
    const uint8_t *data = region() + ANIM_HEADER_SIZE;
    size_t used = anim_decode_record(&data[g_rec_off], g_hdr.data_len - g_rec_off, g_frame);
    if (used == 0) {
        printf("anim decode error at frame %u — builtin\n", g_frame_idx);
        g_have_stored = false;
        start_play(true, g_preview);
        return false;
    }
    g_rec_off += (uint32_t)used;
    g_frame_idx++;
    if (g_frame_idx >= g_hdr.frame_count) {
        if (g_hdr.flags & ANIM_FLAG_LOOP) {
            g_frame_idx = 0;
            g_rec_off = 0;
        } else {
            g_hold = true;
        }
    }
    return true;
}

void anim_init(void) {
    g_state = ANIM_STATE_ACTIVE;
    g_last_input_us = time_us_64();
    uintptr_t end = (uintptr_t)&__flash_binary_end;
    g_region_ok = end <= (uintptr_t)(XIP_BASE + ANIM_REGION_OFFSET);
    if (!g_region_ok) {
        printf("anim: firmware image (end 0x%08lX) overlaps ANIM region — stored animations disabled\n",
               (unsigned long)end);
    }
    load_stored();
    printf("anim idle: %s, idle %u s, blank %u s\n", g_set.enabled ? "on" : "off",
           g_set.idle_timeout_s, g_set.blank_timeout_s);
}

void anim_note_input(void) {
    g_last_input_us = time_us_64();
}

bool anim_screen_owned(void) {
    return g_state != ANIM_STATE_ACTIVE;
}

bool anim_wake(void) {
    anim_note_input();
    if (g_state == ANIM_STATE_ACTIVE) {
        return false;
    }
    release_screen();
    printf("anim wake\n");
    return true;
}

void anim_task(void) {
    if (g_up_active || !oled_driver_ok()) {
        return;
    }
    uint64_t now = time_us_64();
    uint64_t idle_us = now - g_last_input_us;
    bool blank_due = g_set.blank_timeout_s &&
                     idle_us >= (uint64_t)g_set.blank_timeout_s * 1000000u;

    switch (g_state) {
    case ANIM_STATE_ACTIVE:
        if (g_set.enabled && g_set.idle_timeout_s &&
            idle_us >= (uint64_t)g_set.idle_timeout_s * 1000000u && !blank_due) {
            start_play(false, false);
        } else if (blank_due) {
            go_blank();
        }
        break;
    case ANIM_STATE_PLAYING:
        if (blank_due && !g_preview) {
            go_blank();
            break;
        }
        if (now >= g_next_frame_us && !oled_driver_busy()) {
            if (next_frame()) {
                oled_driver_load_frame(g_frame);
                oled_driver_update();
            }
            g_next_frame_us += g_period_us;
            if (now > g_next_frame_us + g_period_us) {
                g_next_frame_us = now + g_period_us; /* fell behind: resync */
            }
        }
        break;
    case ANIM_STATE_BLANK:
    default:
        break;
    }
}

uint8_t anim_preview(uint8_t mode) {
    if (g_up_active) {
        return CFG_ERR_EBUSY;
    }
    switch (mode) {
    case ANIM_PREVIEW_STOP:
        anim_wake();
        return CFG_ERR_OK;
    case ANIM_PREVIEW_PLAY:
        start_play(false, true);
        return CFG_ERR_OK;
    case ANIM_PREVIEW_BUILTIN:
        start_play(true, true);
        return CFG_ERR_OK;
    case ANIM_PREVIEW_BLANK:
        go_blank();
        return CFG_ERR_OK;
    default:
        return CFG_ERR_EINVAL;
    }
}

/* ---- flash writes ------------------------------------------------------- */

typedef struct {
    uint32_t offset;
    const uint8_t *data;   /* NULL → erase only */
} anim_flash_op_t;

static void flash_op_cb(void *param) {
    const anim_flash_op_t *op = (const anim_flash_op_t *)param;
    flash_range_erase(op->offset, FLASH_SECTOR_SIZE);
    if (op->data) {
        flash_range_program(op->offset, op->data, FLASH_SECTOR_SIZE);
    }
}

static bool flash_sector(uint32_t index, const uint8_t *data) {
    anim_flash_op_t op = {ANIM_REGION_OFFSET + index * FLASH_SECTOR_SIZE, data};
    int rc = flash_safe_execute(flash_op_cb, &op, 200u);
    if (rc != PICO_OK) {
        printf("anim flash rc=%d sector=%lu\n", rc, (unsigned long)index);
        return false;
    }
    return true;
}

static void invalidate_stored(void) {
    g_have_stored = false;
    (void)flash_sector(0, NULL);
}

/* ---- upload ------------------------------------------------------------- */

bool anim_upload_busy(void) {
    return g_up_active;
}

uint8_t anim_upload_begin(uint32_t total_len, uint32_t blob_crc) {
    if (g_up_active) {
        return CFG_ERR_EBUSY;
    }
    if (!g_region_ok || total_len < ANIM_HEADER_SIZE + ANIM_REC_HDR_SIZE ||
        total_len > ANIM_REGION_SIZE) {
        return CFG_ERR_EINVAL;
    }
    if (g_state != ANIM_STATE_ACTIVE) {
        release_screen();
    }
    g_up_active = true;
    g_up_total = total_len;
    g_up_crc = blob_crc;
    g_up_got = 0;
    g_up_sectors_written = 0;
    memset(g_up_sector, 0xFF, sizeof g_up_sector);
    printf("anim upload begin len=%lu\n", (unsigned long)total_len);
    return CFG_ERR_OK;
}

static bool flush_upload_sector(void) {
    if (!flash_sector(g_up_sectors_written, g_up_sector)) {
        return false;
    }
    if (g_up_sectors_written == 0) {
        g_have_stored = false; /* old header overwritten */
    }
    g_up_sectors_written++;
    memset(g_up_sector, 0xFF, sizeof g_up_sector);
    return true;
}

uint8_t anim_upload_data(uint32_t offset, const uint8_t *data, uint16_t len) {
    if (!g_up_active || data == NULL) {
        return CFG_ERR_EINVAL;
    }
    if (offset != g_up_got || g_up_got + len > g_up_total) {
        return CFG_ERR_EINVAL;
    }
    while (len > 0) {
        uint32_t in_sector = g_up_got % ANIM_SECTOR_SIZE;
        uint32_t n = ANIM_SECTOR_SIZE - in_sector;
        if (n > len) {
            n = len;
        }
        memcpy(&g_up_sector[in_sector], data, n);
        g_up_got += n;
        data += n;
        len = (uint16_t)(len - n);
        if (g_up_got % ANIM_SECTOR_SIZE == 0) {
            if (!flush_upload_sector()) {
                anim_upload_abort();
                return CFG_ERR_EBUSY;
            }
        }
    }
    return CFG_ERR_OK;
}

uint8_t anim_upload_commit(void) {
    if (!g_up_active) {
        return CFG_ERR_EINVAL;
    }
    if (g_up_got != g_up_total) {
        anim_upload_abort();
        return CFG_ERR_EINVAL;
    }
    if (g_up_got % ANIM_SECTOR_SIZE != 0 && !flush_upload_sector()) {
        anim_upload_abort();
        return CFG_ERR_EBUSY;
    }
    g_up_active = false;
    uint8_t err = CFG_ERR_OK;
    if (cfg_crc32(region(), g_up_total) != g_up_crc) {
        err = CFG_ERR_EBADMSG;
    } else {
        anim_header_t h;
        uint32_t total = 0;
        if (!anim_validate(region(), ANIM_REGION_SIZE, crc_fn, &h, &total) ||
            total != g_up_total) {
            err = CFG_ERR_EBADMSG;
        }
    }
    if (err != CFG_ERR_OK) {
        invalidate_stored();
        printf("anim commit rejected err=%u\n", err);
    } else {
        load_stored();
        printf("anim commit ok (%lu sectors)\n", (unsigned long)g_up_sectors_written);
    }
    anim_note_input();
    return err;
}

void anim_upload_abort(void) {
    if (!g_up_active) {
        return;
    }
    g_up_active = false;
    if (g_up_sectors_written > 0) {
        invalidate_stored(); /* partial new data in flash — fall back to builtin */
    }
    g_up_got = 0;
    anim_note_input();
    printf("anim upload abort\n");
}

/* ---- info / read ----------------------------------------------------------- */

void anim_info(uint8_t out[ANIM_INFO_SIZE]) {
    memset(out, 0, ANIM_INFO_SIZE);
    uint8_t st = 0;
    if (g_have_stored) st |= 0x01u;
    if (g_up_active) st |= 0x02u;
    if (g_state == ANIM_STATE_PLAYING) st |= 0x04u;
    if (g_state == ANIM_STATE_BLANK) st |= 0x08u;
    if (g_state == ANIM_STATE_PLAYING && g_playing_builtin) st |= 0x10u;
    if (g_preview) st |= 0x20u;
    if (g_region_ok) st |= 0x40u;
    out[0] = st;
    out[1] = ANIM_VERSION;
    if (g_have_stored) {
        wr16(&out[2], g_hdr.frame_count);
        out[4] = g_hdr.fps;
        out[5] = g_hdr.flags;
        wr32(&out[6], g_total_len);
        wr32(&out[10], g_total_crc);
        memcpy(&out[32], g_hdr.name, 8);
    }
    wr32(&out[14], ANIM_REGION_SIZE);
    wr16(&out[18], (uint16_t)ANIM_MAX_FRAMES_RAW);
    uint32_t bus = 0, wall = 0;
    oled_driver_last_frame_us(&bus, &wall);
    wr32(&out[20], bus);
    wr32(&out[24], wall);
    wr32(&out[28], g_up_active ? g_up_got : 0u);
}

bool anim_read(uint32_t offset, uint8_t *out, uint16_t max_len, uint16_t *out_len) {
    if (out == NULL || out_len == NULL || offset >= ANIM_REGION_SIZE || g_up_active) {
        return false;
    }
    uint32_t n = ANIM_REGION_SIZE - offset;
    if (n > max_len) {
        n = max_len;
    }
    memcpy(out, region() + offset, n);
    *out_len = (uint16_t)n;
    return true;
}
