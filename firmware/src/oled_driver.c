#include "oled_driver.h"
#include "board_pins.h"

#include "hardware/i2c.h"
#include "pico/stdlib.h"

#include <string.h>

#define OLED_I2C          i2c0
#define OLED_I2C_BAUD     (400 * 1000)
#define OLED_ADDR_PRIMARY 0x3C
#define OLED_ADDR_ALT     0x3D

/*
 * non-blocking flush. oled_driver_update() only marks the frame
 * dirty; oled_driver_task() (every main-loop tick) snapshots fb into tx and
 * streams it in 16-byte data transactions, at most OLED_FLUSH_CHUNKS_PER_TASK
 * per call. At 400 kHz one transaction (addr + 0x40 + 16 data = 18 bytes x
 * 9 clocks) is ~0.41 ms, so a tick blocks <= ~0.83 ms instead of the old
 * ~26 ms full-frame stall; a whole 1 KiB frame takes ~33 ticks (~26.5 ms of
 * bus time), i.e. up to ~30 fps. Measured per-frame bus/wall time is exposed
 * via oled_driver_last_frame_us() (ANIM_INFO).
 */
#define OLED_CHUNK                  16u
#ifndef OLED_FLUSH_CHUNKS_PER_TASK
#define OLED_FLUSH_CHUNKS_PER_TASK  2u
#endif

static uint8_t tx[OLED_FB_BYTES];      /* snapshot being streamed */
static uint16_t tx_off;
static bool tx_active;
static bool tx_pending;
static uint64_t tx_start_us;
static uint32_t tx_bus_us;
static uint32_t last_bus_us;
static uint32_t last_wall_us;
static uint8_t i2c_addr;
static bool ready;

static bool i2c_write_raw(const uint8_t *data, size_t len) {
    int written = i2c_write_blocking(OLED_I2C, i2c_addr, data, len, false);
    return written == (int)len;
}

static bool cmd1(uint8_t c) {
    uint8_t buf[2] = {0x00, c};
    return i2c_write_raw(buf, 2);
}

static bool cmd_list(const uint8_t *cmds, size_t n) {
    for (size_t i = 0; i < n; i++) {
        if (!cmd1(cmds[i])) {
            return false;
        }
    }
    return true;
}

static bool probe_addr(uint8_t addr) {
    uint8_t probe = 0x00;
    int r = i2c_write_blocking(OLED_I2C, addr, &probe, 1, false);
    return r >= 0;
}

bool oled_driver_init(void) {
    ready = false;
    oled_driver_clear();
    i2c_addr = OLED_ADDR_PRIMARY;

    i2c_init(OLED_I2C, OLED_I2C_BAUD);
    gpio_set_function(PIN_OLED_SDA, GPIO_FUNC_I2C);
    gpio_set_function(PIN_OLED_SCL, GPIO_FUNC_I2C);
    gpio_pull_up(PIN_OLED_SDA);
    gpio_pull_up(PIN_OLED_SCL);
    sleep_ms(50);

    if (probe_addr(OLED_ADDR_PRIMARY)) {
        i2c_addr = OLED_ADDR_PRIMARY;
    } else if (probe_addr(OLED_ADDR_ALT)) {
        i2c_addr = OLED_ADDR_ALT;
    } else {
        return false;
    }

    /* SSD1306 128x64 init sequence (charge pump, horizontal addressing) */
    static const uint8_t init_cmds[] = {
        0xAE,       /* display off */
        0xD5, 0x80, /* clock */
        0xA8, 0x3F, /* multiplex 1/64 */
        0xD3, 0x00, /* display offset */
        0x40,       /* start line */
        0x8D, 0x14, /* charge pump on */
        0x20, 0x00, /* horizontal addressing */
        0xA1,       /* segment remap */
        0xC8,       /* COM scan dec */
        0xDA, 0x12, /* COM pins */
        0x81, 0xCF, /* contrast */
        0xD9, 0xF1, /* precharge */
        0xDB, 0x40, /* VCOM detect */
        0xA4,       /* resume RAM */
        0xA6,       /* normal display */
        0xAF,       /* display on */
    };

    if (!cmd_list(init_cmds, sizeof init_cmds)) {
        return false;
    }

    ready = true;
    tx_active = false;
    tx_pending = false;
    oled_driver_clear();
    oled_driver_update_blocking();
    return true;
}

bool oled_driver_ok(void) {
    return ready;
}

uint8_t oled_driver_address(void) {
    return i2c_addr;
}

void oled_driver_update(void) {
    if (!ready) {
        return;
    }
    tx_pending = true; /* picked up by oled_driver_task() */
}

bool oled_driver_busy(void) {
    return ready && (tx_active || tx_pending);
}

static bool flush_begin(void) {
    memcpy(tx, oled_driver_framebuffer(), sizeof tx);
    tx_pending = false;
    tx_off = 0;
    tx_start_us = time_us_64();
    /* Column 0..127, page 0..7 window in one command transaction. */
    static const uint8_t window[] = {0x00, 0x21, 0, 127, 0x22, 0, 7};
    uint32_t t0 = time_us_32();
    bool ok = i2c_write_raw(window, sizeof window);
    tx_bus_us = time_us_32() - t0;
    tx_active = ok;
    return ok;
}

void oled_driver_task(void) {
    if (!ready) {
        return;
    }
    if (!tx_active) {
        if (!tx_pending || !flush_begin()) {
            return;
        }
    }
    uint8_t chunk[1 + OLED_CHUNK];
    chunk[0] = 0x40;
    for (unsigned n = 0; n < OLED_FLUSH_CHUNKS_PER_TASK && tx_off < sizeof tx; n++) {
        memcpy(&chunk[1], &tx[tx_off], OLED_CHUNK);
        uint32_t t0 = time_us_32();
        bool ok = i2c_write_raw(chunk, sizeof chunk);
        tx_bus_us += time_us_32() - t0;
        if (!ok) {
            tx_active = false; /* drop this frame; next update retries */
            return;
        }
        tx_off = (uint16_t)(tx_off + OLED_CHUNK);
    }
    if (tx_off >= sizeof tx) {
        tx_active = false;
        last_bus_us = tx_bus_us;
        last_wall_us = (uint32_t)(time_us_64() - tx_start_us);
    }
}

void oled_driver_update_blocking(void) {
    oled_driver_update();
    while (oled_driver_busy()) {
        oled_driver_task();
    }
}

void oled_driver_display_on(bool on) {
    if (ready) {
        cmd1(on ? 0xAF : 0xAE);
    }
}

void oled_driver_last_frame_us(uint32_t *bus_us, uint32_t *wall_us) {
    if (bus_us) {
        *bus_us = last_bus_us;
    }
    if (wall_us) {
        *wall_us = last_wall_us;
    }
}

