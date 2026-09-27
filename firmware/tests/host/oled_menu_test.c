/*
 * Off-target test of the OLED menu: builds the real menu.c, device_menu.c,
 * oled_ui.c, oled_gfx.c and oled_font.c against stubs.c, drives the menu
 * through the same inputs main.c sends (turn, short press, hold), checks the
 * navigation / persistence behaviour and dumps the framebuffer as PBM files.
 *
 *   cc -std=c11 -Wall -Wextra -Werror -I../../include -Ishim \
 *      ../../src/{menu,device_menu,oled_ui,oled_gfx,oled_font}.c stubs.c oled_menu_test.c
 *   ./a.out [out_dir]      # exit 0 = all checks passed
 *
 * configurator/scripts/smoke_oled_menu.py compiles and runs this and turns the
 * PBMs into 4x PNGs.
 */
#include "anim.h"
#include "device_menu.h"
#include "menu.h"
#include "oled_driver.h"
#include "oled_ui.h"
#include "profiles.h"
#include "stubs.h"

#include <stdio.h>
#include <string.h>

static int g_fail;
static int g_checks;
static const char *g_out;

#define CHECK(cond, ...)                                  \
    do {                                                  \
        g_checks++;                                       \
        if (!(cond)) {                                    \
            g_fail++;                                     \
            printf("FAIL  %s:%d: ", __FILE__, __LINE__);  \
            printf(__VA_ARGS__);                          \
            printf("\n");                                 \
        }                                                 \
    } while (0)

static void advance_ms(uint32_t ms) {
    /* 1 ms main-loop ticks, like main.c */
    for (uint32_t i = 0; i < ms; i++) {
        host_now_us += 1000u;
        device_menu_task();
        oled_ui_task();
    }
}

static void settle(void) {
    advance_ms(2);
}

static bool px(int x, int y) {
    const uint8_t *fb = oled_driver_framebuffer();
    return (fb[x + (y / 8) * OLED_WIDTH] >> (y & 7)) & 1u;
}

static void dump(const char *name) {
    settle();
    if (g_out == NULL) {
        return;
    }
    char path[512];
    snprintf(path, sizeof path, "%s/%s.pbm", g_out, name);
    FILE *f = fopen(path, "w");
    if (f == NULL) {
        printf("FAIL  cannot write %s\n", path);
        g_fail++;
        return;
    }
    fprintf(f, "P1\n%d %d\n", OLED_WIDTH, OLED_HEIGHT);
    for (int y = 0; y < OLED_HEIGHT; y++) {
        for (int x = 0; x < OLED_WIDTH; x++) {
            fputc(px(x, y) ? '1' : '0', f);
        }
        fputc('\n', f);
    }
    fclose(f);
    printf("frame %s\n", name);
}

static const char *page_title(void) {
    const menu_page_t *p = menu_page(device_menu_state());
    return p ? p->title : "(closed)";
}

static int lit_in_row(int y) {
    int n = 0;
    for (int x = 0; x < OLED_WIDTH; x++) {
        n += px(x, y);
    }
    return n;
}

/* short press = MENU_IN_SELECT, hold = MENU_IN_BACK (see main.c) */
static void turn(int detents) {
    for (int i = 0; i < (detents < 0 ? -detents : detents); i++) {
        device_menu_input(detents > 0 ? MENU_IN_NEXT : MENU_IN_PREV);
    }
}

int main(int argc, char **argv) {
    g_out = argc > 1 ? argv[1] : NULL;
    host_profiles_reset(0);
    host_now_us = 0;
    oled_ui_init();
    advance_ms(1600);   /* boot splash → home */
    CHECK(oled_ui_page() == OLED_PAGE_IDLE, "home after boot (page %d)", oled_ui_page());
    dump("home");

    /* ---- main menu ---- */
    device_menu_open();
    CHECK(device_menu_active(), "hold opens the menu");
    CHECK(strcmp(page_title(), "Menu") == 0, "main menu title %s", page_title());
    CHECK(menu_cursor(device_menu_state()) == 0, "cursor starts on Profiles");
    dump("main_menu");
    CHECK(lit_in_row(10) == OLED_WIDTH, "title rule drawn");
    CHECK(px(1, 13) && px(60, 20), "highlight bar on the first row");
    turn(5);
    CHECK(menu_cursor(device_menu_state()) == 0, "turning wraps (5 items → back to 0)");
    turn(-1);
    CHECK(menu_cursor(device_menu_state()) == 4, "turning back wraps to Exit");
    device_menu_input(MENU_IN_SELECT);
    CHECK(!device_menu_active() && oled_ui_page() == OLED_PAGE_IDLE, "Exit closes the menu");

    /* hold at the top level = exit */
    device_menu_open();
    device_menu_input(MENU_IN_BACK);
    CHECK(!device_menu_active(), "hold at the top level closes the menu");

    /* ---- profiles ---- */
    device_menu_open();
    device_menu_input(MENU_IN_SELECT);
    CHECK(strcmp(page_title(), "Profiles") == 0, "Profiles page (%s)", page_title());
    CHECK(menu_cursor(device_menu_state()) == 0, "cursor on the active profile (0)");
    turn(2);
    dump("profiles");
    CHECK(menu_cursor(device_menu_state()) == 2, "moved to CODING");
    turn(3);
    CHECK(menu_cursor(device_menu_state()) == 5, "Back row is last");
    dump("profiles_scrolled");
    turn(1);
    CHECK(menu_cursor(device_menu_state()) == 0, "profile list wraps");
    device_menu_input(MENU_IN_BACK);
    CHECK(strcmp(page_title(), "Menu") == 0, "hold goes back one level");
    CHECK(menu_cursor(device_menu_state()) == 0, "parent keeps its highlight");
    device_menu_input(MENU_IN_SELECT);
    turn(2);
    unsigned persists = host_calls.persist_scheduled;
    device_menu_input(MENU_IN_SELECT);
    CHECK(profiles_active_index() == 2, "CODING active (%u)", profiles_active_index());
    CHECK(host_calls.persist_scheduled == persists + 1, "profile pick schedules the debounced persist");
    CHECK(!device_menu_active(), "picking a profile returns home");
    CHECK(oled_ui_page() == OLED_PAGE_TOAST, "toast after switching");
    dump("toast_switched");
    advance_ms(1300);
    CHECK(oled_ui_page() == OLED_PAGE_IDLE, "toast returns to the home screen");
    dump("home_coding");

    /* ---- idle animation ---- */
    device_menu_open();
    turn(1);
    device_menu_input(MENU_IN_SELECT);
    CHECK(strcmp(page_title(), "Idle") == 0, "Idle page (%s)", page_title());
    turn(1);
    dump("idle");
    persists = host_calls.persist_scheduled;
    device_menu_input(MENU_IN_SELECT);   /* Play when idle → off */
    uint8_t st[8];
    anim_settings_pack(st);
    CHECK(st[0] == 0, "Play when idle toggled off");
    CHECK(host_calls.persist_scheduled == persists + 1, "toggle schedules the debounced persist");
    CHECK(device_menu_active() && strcmp(page_title(), "Idle") == 0, "toggle stays on the page");
    device_menu_input(MENU_IN_SELECT);   /* back on */
    turn(1);
    device_menu_input(MENU_IN_SELECT);   /* Start after > */
    CHECK(strcmp(page_title(), "Start after") == 0, "Start after page (%s)", page_title());
    CHECK(menu_cursor(device_menu_state()) == 2, "radio cursor on the current value (1 min)");
    turn(1);
    dump("start_after");
    device_menu_input(MENU_IN_SELECT);
    anim_settings_pack(st);
    CHECK((st[2] | (st[3] << 8)) == 120, "Start after = 2 min (%d)", st[2] | (st[3] << 8));
    CHECK(strcmp(page_title(), "Idle") == 0, "picking a preset goes back");
    turn(2);
    device_menu_input(MENU_IN_SELECT);   /* Back row */
    CHECK(strcmp(page_title(), "Menu") == 0, "Back row returns to Menu");
    turn(-1);
    persists = host_calls.persist_scheduled;
    device_menu_input(MENU_IN_BACK);
    device_menu_open();
    turn(1);
    device_menu_input(MENU_IN_SELECT);
    device_menu_input(MENU_IN_SELECT);   /* Preview now */
    CHECK(host_calls.anim_preview == 1 && host_calls.last_preview_mode == 1, "Preview now plays the stored animation");
    CHECK(!device_menu_active(), "preview closes the menu");

    /* ---- device info ---- */
    host_now_us = (uint64_t)(3600u + 2 * 60u + 7u) * 1000000u;
    device_menu_open();
    turn(2);
    device_menu_input(MENU_IN_SELECT);
    CHECK(strcmp(page_title(), "Device info") == 0, "Device info page (%s)", page_title());
    dump("device_info");
    turn(1);
    dump("device_info_scrolled");
    turn(2);
    CHECK(menu_cursor(device_menu_state()) == 0, "info view wraps back to the top");
    device_menu_input(MENU_IN_SELECT);
    CHECK(strcmp(page_title(), "Menu") == 0, "press on an info page goes back");

    /* ---- save + toast over the menu ---- */
    turn(1);
    unsigned saves = host_calls.save_all;
    device_menu_input(MENU_IN_SELECT);
    CHECK(host_calls.save_all == saves + 1, "Save device state writes flash now");
    CHECK(device_menu_active() && oled_ui_page() == OLED_PAGE_TOAST, "Saved toast over the menu");
    dump("toast_saved");
    advance_ms(1300);
    CHECK(oled_ui_page() == OLED_PAGE_MENU, "toast returns to the menu");

    /* ---- timeout ---- */
    advance_ms(DEVICE_MENU_TIMEOUT_MS - 1400);
    CHECK(device_menu_active(), "still open just before the timeout");
    advance_ms(200);
    CHECK(!device_menu_active() && oled_ui_page() == OLED_PAGE_IDLE, "9 s idle closes the menu");

    /* input restarts the timeout */
    device_menu_open();
    advance_ms(8000);
    turn(1);
    advance_ms(8000);
    CHECK(device_menu_active(), "turning restarts the 9 s timeout");
    device_menu_close();

    /* ---- PROFILE key / SET_ACTIVE path ---- */
    persists = host_calls.persist_scheduled;
    device_menu_open();
    CHECK(device_select_profile(4), "select slot 4");
    CHECK(!device_menu_active(), "an external switch closes the menu");
    CHECK(host_calls.persist_scheduled == persists + 1, "PROFILE key / SET_ACTIVE schedule the persist");
    CHECK(!device_select_profile(9), "out-of-range slot rejected");

    /* ---- engine edge cases ---- */
    menu_t m = {0};
    CHECK(!menu_input(&m, MENU_IN_NEXT), "input on a closed menu is ignored");

    printf("%s: %d checks, %d failed\n", g_fail ? "FAIL" : "OK", g_checks, g_fail);
    return g_fail ? 1 : 0;
}
