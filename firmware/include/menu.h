#pragma once

/*
 * Small table-driven menu engine for the 128x64 OLED.
 *
 * A menu is a tree of menu_page_t. A page lists items either from a static
 * table (items/count) or from callbacks (dyn_count/dyn_item, e.g. the profile
 * list). Items open a sub-page, run an action, or show a toggle / radio / "current"
 * marker and an optional right-aligned value. INFO pages are read-only
 * label/value lines: turning scrolls, a press goes back.
 *
 * Navigation (menu_input) is the same on every page:
 *   MENU_IN_NEXT / MENU_IN_PREV  move the highlight (wraps)
 *   MENU_IN_SELECT               open / confirm
 *   MENU_IN_BACK                 back one level; closes the menu at the top level
 *
 * The engine has no Pico SDK dependency (host-testable). It draws through the
 * oled_driver.h primitives; the caller owns when the frame is pushed.
 */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MENU_MAX_DEPTH     4
#define MENU_VISIBLE_ROWS  4
#define MENU_LABEL_MAX     22   /* 21 glyphs + NUL: the full 128 px width */
#define MENU_VALUE_MAX     12

typedef enum {
    MENU_STAY = 0,   /* stay on the page (re-render) */
    MENU_BACK,       /* go back one level */
    MENU_CLOSE,      /* close the whole menu */
} menu_result_t;

typedef enum {
    MENU_ITEM_ACTION = 0,   /* select runs .action */
    MENU_ITEM_SUBMENU,      /* select opens .submenu */
    MENU_ITEM_TOGGLE,       /* select runs .action; box shows .state */
    MENU_ITEM_RADIO,        /* select runs .action; ring + dot shows .state */
    MENU_ITEM_BACK,         /* select = back one level ("Back" / "Exit") */
    MENU_ITEM_INFO,         /* read-only label / value line (INFO pages) */
} menu_item_kind_t;

typedef struct menu_page menu_page_t;

typedef struct {
    menu_item_kind_t kind;
    const char *label;
    const menu_page_t *submenu;
    menu_result_t (*action)(uint8_t arg);
    bool (*state)(uint8_t arg);                         /* toggle / radio / current */
    void (*value)(uint8_t arg, char *buf, size_t n);    /* right-aligned text */
    uint8_t arg;
} menu_item_t;

typedef enum {
    MENU_PAGE_LIST = 0,
    MENU_PAGE_INFO,
} menu_page_kind_t;

struct menu_page {
    const char *title;
    menu_page_kind_t kind;
    const menu_item_t *items;   /* static table (NULL for dynamic pages) */
    uint8_t count;
    /* Dynamic pages: item count and item factory (label written to buf). */
    uint8_t (*dyn_count)(void);
    void (*dyn_item)(uint8_t index, menu_item_t *out, char *label, size_t n);
    /* Optional initial highlight when the page opens (e.g. active profile). */
    uint8_t (*initial)(void);
};

typedef enum {
    MENU_IN_NEXT = 0,
    MENU_IN_PREV,
    MENU_IN_SELECT,
    MENU_IN_BACK,
} menu_input_t;

typedef struct {
    const menu_page_t *page;
    uint8_t cursor;   /* highlighted item (LIST) / first visible line (INFO) */
    uint8_t top;      /* first visible row */
} menu_level_t;

typedef struct {
    menu_level_t stack[MENU_MAX_DEPTH];
    uint8_t depth;    /* 0 = closed */
} menu_t;

void menu_open(menu_t *m, const menu_page_t *root);
void menu_close(menu_t *m);
bool menu_is_open(const menu_t *m);
/* Returns true while the menu is still open after the input. */
bool menu_input(menu_t *m, menu_input_t in);

const menu_page_t *menu_page(const menu_t *m);
uint8_t menu_cursor(const menu_t *m);
uint8_t menu_item_count(const menu_page_t *page);
/* Fills *out for item index of page; label points at buf for dynamic items. */
bool menu_get_item(const menu_page_t *page, uint8_t index, menu_item_t *out, char *buf, size_t n);

/* Title bar text: "Parent > Page" when it fits, else the page title. */
void menu_breadcrumb(const menu_t *m, char *buf, size_t n);

/* Draw the current page into the OLED framebuffer (does not push it). */
void menu_render(const menu_t *m);

#ifdef __cplusplus
}
#endif
