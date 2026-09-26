#pragma once

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Step 9 non-blocking macro engine.
 * Built-in RAM tables; one playback at a time.
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

#ifdef __cplusplus
}
#endif
