/*
 * Table-driven OLED menu engine (see menu.h). No Pico SDK dependency.
 *
 * Layout (128x64, 5x7 font on a 6 px pitch):
 *   y 0..9    title bar: breadcrumb left, "n/N" position right (only when the
 *             list overflows), 1 px rule at y = 10
 *   y 12..63  four 13 px rows; the highlighted row is an inverse bar
 *   x 126..127 scroll bar when a page has more than four rows
 */
#include "menu.h"
#include "oled_driver.h"

#include <stdio.h>
#include <string.h>

#define TITLE_Y     1
#define RULE_Y      10
#define ROW_Y0      12
#define ROW_H       13
#define TEXT_DY     3
#define GLYPH_W     6
#define SCROLL_X    126

/* ---- model -------------------------------------------------------------- */

uint8_t menu_item_count(const menu_page_t *page) {
    if (page == NULL) {
        return 0;
    }
    if (page->dyn_count) {
        return page->dyn_count();
    }
    return page->count;
}

bool menu_get_item(const menu_page_t *page, uint8_t index, menu_item_t *out, char *buf, size_t n) {
    if (page == NULL || out == NULL || index >= menu_item_count(page)) {
        return false;
    }
    memset(out, 0, sizeof *out);
    if (page->dyn_item) {
        if (buf && n) {
            buf[0] = '\0';
        }
        page->dyn_item(index, out, buf, n);
        if (out->label == NULL) {
            out->label = buf;
        }
        return true;
    }
    *out = page->items[index];
    return true;
}

static menu_level_t *top_level(menu_t *m) {
    return (m && m->depth) ? &m->stack[m->depth - 1] : NULL;
}

static void ensure_visible(menu_level_t *lv) {
    uint8_t count = menu_item_count(lv->page);
    if (count == 0) {
        lv->cursor = lv->top = 0;
        return;
    }
    if (lv->page->kind == MENU_PAGE_INFO) {
        /* cursor is the first visible line */
        uint8_t max_top = count > MENU_VISIBLE_ROWS ? (uint8_t)(count - MENU_VISIBLE_ROWS) : 0;
        if (lv->cursor > max_top) {
            lv->cursor = max_top;
        }
        lv->top = lv->cursor;
        return;
    }
    if (lv->cursor >= count) {
        lv->cursor = (uint8_t)(count - 1);
    }
    if (lv->cursor < lv->top) {
        lv->top = lv->cursor;
    } else if (lv->cursor >= (uint8_t)(lv->top + MENU_VISIBLE_ROWS)) {
        lv->top = (uint8_t)(lv->cursor - MENU_VISIBLE_ROWS + 1);
    }
    if (count <= MENU_VISIBLE_ROWS) {
        lv->top = 0;
    } else if (lv->top > count - MENU_VISIBLE_ROWS) {
        lv->top = (uint8_t)(count - MENU_VISIBLE_ROWS);
    }
}

static void push(menu_t *m, const menu_page_t *page) {
    if (page == NULL || m->depth >= MENU_MAX_DEPTH) {
        return;
    }
    menu_level_t *lv = &m->stack[m->depth++];
    lv->page = page;
    lv->cursor = page->initial ? page->initial() : 0;
    lv->top = 0;
    ensure_visible(lv);
}

void menu_open(menu_t *m, const menu_page_t *root) {
    if (m == NULL) {
        return;
    }
    m->depth = 0;
    push(m, root);
}

void menu_close(menu_t *m) {
    if (m) {
        m->depth = 0;
    }
}

bool menu_is_open(const menu_t *m) {
    return m && m->depth > 0;
}

const menu_page_t *menu_page(const menu_t *m) {
    return (m && m->depth) ? m->stack[m->depth - 1].page : NULL;
}

uint8_t menu_cursor(const menu_t *m) {
    return (m && m->depth) ? m->stack[m->depth - 1].cursor : 0;
}

static void apply_result(menu_t *m, menu_result_t r) {
    if (r == MENU_CLOSE) {
        m->depth = 0;
    } else if (r == MENU_BACK && m->depth) {
        m->depth--;
    }
    menu_level_t *lv = top_level(m);
    if (lv) {
        ensure_visible(lv);   /* dynamic pages may have changed size */
    }
}

bool menu_input(menu_t *m, menu_input_t in) {
    menu_level_t *lv = top_level(m);
    if (lv == NULL) {
        return false;
    }
    uint8_t count = menu_item_count(lv->page);
    const bool info = lv->page->kind == MENU_PAGE_INFO;

    switch (in) {
    case MENU_IN_NEXT:
    case MENU_IN_PREV: {
        if (count == 0) {
            break;
        }
        /* LIST: the highlight wraps; INFO: the view scrolls and wraps. */
        uint8_t span = info ? (count > MENU_VISIBLE_ROWS ? (uint8_t)(count - MENU_VISIBLE_ROWS + 1) : 1)
                            : count;
        if (in == MENU_IN_NEXT) {
            lv->cursor = (uint8_t)((lv->cursor + 1) % span);
        } else {
            lv->cursor = (uint8_t)((lv->cursor + span - 1) % span);
        }
        ensure_visible(lv);
        break;
    }
    case MENU_IN_SELECT: {
        if (info) {
            apply_result(m, MENU_BACK);
            break;
        }
        menu_item_t it;
        char buf[MENU_LABEL_MAX];
        if (!menu_get_item(lv->page, lv->cursor, &it, buf, sizeof buf)) {
            break;
        }
        switch (it.kind) {
        case MENU_ITEM_SUBMENU:
            push(m, it.submenu);
            break;
        case MENU_ITEM_BACK:
            apply_result(m, MENU_BACK);
            break;
        case MENU_ITEM_ACTION:
        case MENU_ITEM_TOGGLE:
        case MENU_ITEM_RADIO:
            apply_result(m, it.action ? it.action(it.arg) : MENU_STAY);
            break;
        case MENU_ITEM_INFO:
        default:
            break;
        }
        break;
    }
    case MENU_IN_BACK:
        apply_result(m, MENU_BACK);
        break;
    default:
        break;
    }
    return m->depth > 0;
}

void menu_breadcrumb(const menu_t *m, char *buf, size_t n) {
    if (buf == NULL || n == 0) {
        return;
    }
    buf[0] = '\0';
    const menu_page_t *page = menu_page(m);
    if (page == NULL) {
        return;
    }
    if (m->depth >= 2) {
        const menu_page_t *parent = m->stack[m->depth - 2].page;
        int w = snprintf(buf, n, "%s > %s", parent->title, page->title);
        if (w > 0 && (size_t)w < n) {
            return;
        }
    }
    snprintf(buf, n, "%s", page->title);
}

/* ---- rendering ------------------------------------------------------------ */

static void round_corners(int x, int y, int w, int h, bool bg) {
    oled_driver_set_pixel(x, y, bg);
    oled_driver_set_pixel(x + w - 1, y, bg);
    oled_driver_set_pixel(x, y + h - 1, bg);
    oled_driver_set_pixel(x + w - 1, y + h - 1, bg);
}

/* 7x7 check box at (x, y); filled centre when on. */
static void draw_toggle(int x, int y, bool checked, bool fg) {
    oled_driver_draw_rect(x, y, 7, 7, fg);
    if (checked) {
        oled_driver_fill_rect(x + 2, y + 2, 3, 3, fg);
    }
}

/* 7x7 ring with a 3x3 dot when selected. */
static void draw_radio(int x, int y, bool selected, bool fg) {
    oled_driver_fill_rect(x + 2, y, 3, 1, fg);
    oled_driver_fill_rect(x + 2, y + 6, 3, 1, fg);
    oled_driver_fill_rect(x, y + 2, 1, 3, fg);
    oled_driver_fill_rect(x + 6, y + 2, 1, 3, fg);
    oled_driver_set_pixel(x + 1, y + 1, fg);
    oled_driver_set_pixel(x + 5, y + 1, fg);
    oled_driver_set_pixel(x + 1, y + 5, fg);
    oled_driver_set_pixel(x + 5, y + 5, fg);
    if (selected) {
        oled_driver_fill_rect(x + 2, y + 2, 3, 3, fg);
    }
}

/* Filled 5x5 dot (the "current" marker). */
static void draw_dot(int x, int y, bool fg) {
    oled_driver_fill_rect(x + 1, y, 3, 5, fg);
    oled_driver_fill_rect(x, y + 1, 5, 3, fg);
}

/* ">" chevron, 3x5. */
static void draw_chevron(int x, int y, bool fg) {
    oled_driver_set_pixel(x, y, fg);
    oled_driver_set_pixel(x + 1, y + 1, fg);
    oled_driver_set_pixel(x + 2, y + 2, fg);
    oled_driver_set_pixel(x + 1, y + 3, fg);
    oled_driver_set_pixel(x, y + 4, fg);
}

static void draw_text_clipped(int x, int y, const char *s, int max_w, bool fg) {
    char tmp[MENU_LABEL_MAX];
    int max_chars = (max_w + 1) / GLYPH_W;
    if (max_chars <= 0 || s == NULL) {
        return;
    }
    size_t len = strlen(s);
    if ((int)len <= max_chars) {
        oled_driver_draw_string(x, y, s, fg);
        return;
    }
    if (max_chars >= (int)sizeof tmp) {
        max_chars = (int)sizeof tmp - 1;
    }
    memcpy(tmp, s, (size_t)max_chars);
    tmp[max_chars] = '\0';
    if (max_chars >= 2) {
        tmp[max_chars - 1] = '.';   /* mark the cut */
    }
    oled_driver_draw_string(x, y, tmp, fg);
}

static bool page_has_marks(const menu_page_t *page, uint8_t count) {
    for (uint8_t i = 0; i < count; i++) {
        menu_item_t it;
        char buf[MENU_LABEL_MAX];
        if (menu_get_item(page, i, &it, buf, sizeof buf) &&
            (it.kind == MENU_ITEM_TOGGLE || it.kind == MENU_ITEM_RADIO || it.state != NULL)) {
            return true;
        }
    }
    return false;
}

static void draw_scrollbar(uint8_t top, uint8_t count) {
    const int track_y = ROW_Y0;
    const int track_h = OLED_HEIGHT - ROW_Y0;
    for (int y = track_y; y < track_y + track_h; y += 2) {
        oled_driver_set_pixel(SCROLL_X + 1, y, true);
    }
    int thumb_h = track_h * MENU_VISIBLE_ROWS / count;
    if (thumb_h < 6) {
        thumb_h = 6;
    }
    int span = count - MENU_VISIBLE_ROWS;
    int thumb_y = track_y + (span > 0 ? (track_h - thumb_h) * top / span : 0);
    oled_driver_fill_rect(SCROLL_X, thumb_y, 2, thumb_h, true);
}

static void draw_title(const menu_t *m, uint8_t count, const menu_level_t *lv) {
    char crumb[40];
    char pos[8] = "";
    menu_breadcrumb(m, crumb, sizeof crumb);
    if (lv->page->kind == MENU_PAGE_LIST && count > MENU_VISIBLE_ROWS) {
        snprintf(pos, sizeof pos, "%u/%u", (unsigned)(lv->cursor + 1), (unsigned)count);
        oled_driver_draw_string_right(OLED_WIDTH - 2, TITLE_Y, pos, true);
    }
    int avail = OLED_WIDTH - 4 - (pos[0] ? oled_driver_text_width(pos) + GLYPH_W : 0);
    if (oled_driver_text_width(crumb) > avail) {
        snprintf(crumb, sizeof crumb, "%s", lv->page->title);
    }
    draw_text_clipped(2, TITLE_Y, crumb, avail, true);
    oled_driver_hline(0, RULE_Y, OLED_WIDTH, true);
}

void menu_render(const menu_t *m) {
    oled_driver_clear();
    const menu_level_t *lv = (m && m->depth) ? &m->stack[m->depth - 1] : NULL;
    if (lv == NULL || lv->page == NULL) {
        return;
    }
    const menu_page_t *page = lv->page;
    const uint8_t count = menu_item_count(page);
    const bool info = page->kind == MENU_PAGE_INFO;
    const bool overflow = count > MENU_VISIBLE_ROWS;
    const int right = overflow ? SCROLL_X - 3 : OLED_WIDTH - 1;   /* last content column */
    const bool marks = !info && page_has_marks(page, count);

    draw_title(m, count, lv);
    if (overflow) {
        draw_scrollbar(lv->top, count);
    }
    if (count == 0) {
        oled_driver_draw_string_centered(ROW_Y0 + 20, "(empty)", true);
        return;
    }

    for (uint8_t row = 0; row < MENU_VISIBLE_ROWS; row++) {
        uint8_t idx = (uint8_t)(lv->top + row);
        if (idx >= count) {
            break;
        }
        menu_item_t it;
        char label[MENU_LABEL_MAX];
        if (!menu_get_item(page, idx, &it, label, sizeof label)) {
            break;
        }
        const int y = ROW_Y0 + row * ROW_H;
        const bool sel = !info && idx == lv->cursor;
        const bool fg = !sel;
        if (sel) {
            oled_driver_fill_rect(0, y, right + 1, ROW_H - 1, true);
            round_corners(0, y, right + 1, ROW_H - 1, false);
        }

        int label_x = info ? 2 : (marks ? 14 : 4);
        if (marks) {
            bool on = it.state ? it.state(it.arg) : false;
            if (it.kind == MENU_ITEM_TOGGLE) {
                draw_toggle(3, y + 2, on, fg);
            } else if (it.kind == MENU_ITEM_RADIO) {
                draw_radio(3, y + 2, on, fg);
            } else if (on) {
                draw_dot(4, y + 3, fg);
            }
        }

        int text_right = right - 3;
        if (it.kind == MENU_ITEM_SUBMENU) {
            draw_chevron(right - 5, y + 3, fg);
            text_right = right - 10;
        }
        char value[MENU_VALUE_MAX] = "";
        if (it.value) {
            it.value(it.arg, value, sizeof value);
        }
        if (value[0]) {
            oled_driver_draw_string_right(text_right, y + TEXT_DY, value, fg);
            text_right -= oled_driver_text_width(value) + 4;
        }
        draw_text_clipped(label_x, y + TEXT_DY, it.label, text_right - label_x, fg);
    }
}
