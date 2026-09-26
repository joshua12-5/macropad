#pragma once

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Step 9/17 non-blocking macro engine.
 * Factory defaults in flash/const; RAM working set of 5 editable slots.
 * One playback at a time.
 */

typedef enum {
    MACRO_END = 0,
    MACRO_KEY_DOWN,   /* mods + keycode held via macro report */
    MACRO_KEY_UP,     /* release keycode (keycode 0 = release all) */
    MACRO_TAP,        /* mods + keycode down then up */
    MACRO_DELAY_MS,   /* arg = delay in ms */
    MACRO_TEXT,       /* arg = text_table id; uses action typer */
    MACRO_CONSUMER,   /* arg = consumer usage pulse */
} macro_op_t;

typedef struct {
    uint8_t op;
    uint8_t mods;
    uint8_t keycode;
    uint8_t pad;
    uint16_t arg; /* delay_ms, text_id, or consumer usage */
} macro_step_t;

/* Built-in macro ids (macros.c). */
#define MACRO_ID_HELLO          0
#define MACRO_ID_SELECT_COPY    1
#define MACRO_ID_UNDO_REDO      2
#define MACRO_ID_GIT_STATUS     3
#define MACRO_ID_ALT_TAB        4
#define MACRO_BUILTIN_COUNT     5

void macros_init(void);
void macros_task(void);                 /* every ~1 ms from main */
bool macros_fire(uint8_t macro_id);     /* start playback; false if busy/invalid */
bool macros_busy(void);
void macros_abort(void);

const char *macros_name(uint8_t macro_id);

/* Replace RAM slot from host/firmware (aborts playback if id is active). */
bool macros_replace(uint8_t id, const char *name,
                    const macro_step_t *steps, uint8_t count);

/* Unpack wire blob into RAM slot (see macro_blob.h). */
bool macros_apply_blob(uint8_t id, const uint8_t *blob, size_t len);

/* Pack RAM slot to wire blob. */
bool macros_pack_slot(uint8_t id, uint8_t *dst, size_t dst_len);

/* Restore all five slots from factory defaults (used on blank flash). */
void macros_factory_reset_all(void);

#ifdef __cplusplus
}
#endif
