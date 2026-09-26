#include "actions.h"

#include "macros.h"
#include "oled_ui.h"
#include "profiles.h"
#include "text_table.h"
#include "usb_hid_app.h"

#include "class/hid/hid.h"

#include <stdio.h>
#include <string.h>

#ifndef KEYBOARD_MODIFIER_LEFTSHIFT
#define KEYBOARD_MODIFIER_LEFTSHIFT 0x02
#endif
#ifndef HID_KEY_ENTER
#define HID_KEY_ENTER 0x28
#endif
#ifndef HID_KEY_TAB
#define HID_KEY_TAB 0x2B
#endif
#ifndef HID_KEY_SPACE
#define HID_KEY_SPACE 0x2C
#endif
#ifndef HID_KEY_MINUS
#define HID_KEY_MINUS 0x2D
#endif
#ifndef HID_KEY_EQUAL
#define HID_KEY_EQUAL 0x2E
#endif
#ifndef HID_KEY_BRACKET_LEFT
#define HID_KEY_BRACKET_LEFT 0x2F
#endif
#ifndef HID_KEY_BRACKET_RIGHT
#define HID_KEY_BRACKET_RIGHT 0x30
#endif
#ifndef HID_KEY_BACKSLASH
#define HID_KEY_BACKSLASH 0x31
#endif
#ifndef HID_KEY_SEMICOLON
#define HID_KEY_SEMICOLON 0x33
#endif
#ifndef HID_KEY_APOSTROPHE
#define HID_KEY_APOSTROPHE 0x34
#endif
#ifndef HID_KEY_GRAVE
#define HID_KEY_GRAVE 0x35
#endif
#ifndef HID_KEY_COMMA
#define HID_KEY_COMMA 0x36
#endif
#ifndef HID_KEY_PERIOD
#define HID_KEY_PERIOD 0x37
#endif
#ifndef HID_KEY_SLASH
#define HID_KEY_SLASH 0x38
#endif
#ifndef HID_KEY_0
#define HID_KEY_0 0x27
#endif

#ifndef HID_USAGE_CONSUMER_PLAY_PAUSE
#define HID_USAGE_CONSUMER_PLAY_PAUSE 0x00CD
#endif
#ifndef HID_USAGE_CONSUMER_SCAN_NEXT
#define HID_USAGE_CONSUMER_SCAN_NEXT 0x00B5
#endif
#ifndef HID_USAGE_CONSUMER_SCAN_PREVIOUS
#define HID_USAGE_CONSUMER_SCAN_PREVIOUS 0x00B6
#endif
#ifndef HID_USAGE_CONSUMER_STOP
#define HID_USAGE_CONSUMER_STOP 0x00B7
#endif

#define ACTION_QUEUE_DEPTH 8
#define TYPE_GAP_TICKS     6   /* ~6 ms between characters after tap idle */

typedef struct {
    action_t action;
} queued_action_t;

static queued_action_t q[ACTION_QUEUE_DEPTH];
static uint8_t q_head, q_tail;

/* Non-blocking ASCII typer owned by the action engine. */
static const char *type_ptr;
static uint16_t type_index;
static bool type_enter;          /* append HID Enter after string */
static uint8_t type_gap;         /* countdown after each tap */
static bool typing_active;

static bool queue_empty(void) {
    return q_head == q_tail;
}

static bool queue_push(const action_t *a) {
    uint8_t next = (uint8_t)((q_head + 1) % ACTION_QUEUE_DEPTH);
    if (next == q_tail) {
        return false;
    }
    q[q_head].action = *a;
    q_head = next;
    return true;
}

static bool queue_pop(action_t *out) {
    if (queue_empty()) {
        return false;
    }
    *out = q[q_tail].action;
    q_tail = (uint8_t)((q_tail + 1) % ACTION_QUEUE_DEPTH);
    return true;
}

/*
 * US QWERTY ASCII → HID keycode + modifiers.
 * Supports printable 0x20–0x7E plus \n / \r / \t. Unknowns skipped.
 */
static bool ascii_to_hid(char c, uint8_t *mods, uint8_t *keycode) {
    *mods = 0;
    *keycode = 0;

    if (c == '\n' || c == '\r') {
        *keycode = HID_KEY_ENTER;
        return true;
    }
    if (c == '\t') {
        *keycode = HID_KEY_TAB;
        return true;
    }
    if (c == ' ') {
        *keycode = HID_KEY_SPACE;
        return true;
    }
    if (c >= 'a' && c <= 'z') {
        *keycode = (uint8_t)(HID_KEY_A + (c - 'a'));
        return true;
    }
    if (c >= 'A' && c <= 'Z') {
        *mods = KEYBOARD_MODIFIER_LEFTSHIFT;
        *keycode = (uint8_t)(HID_KEY_A + (c - 'A'));
        return true;
    }
    if (c >= '1' && c <= '9') {
        *keycode = (uint8_t)(HID_KEY_1 + (c - '1'));
        return true;
    }
    if (c == '0') {
        *keycode = HID_KEY_0;
        return true;
    }

    switch (c) {
    case '!': *mods = KEYBOARD_MODIFIER_LEFTSHIFT; *keycode = HID_KEY_1; return true;
    case '@': *mods = KEYBOARD_MODIFIER_LEFTSHIFT; *keycode = HID_KEY_2; return true;
    case '#': *mods = KEYBOARD_MODIFIER_LEFTSHIFT; *keycode = HID_KEY_3; return true;
    case '$': *mods = KEYBOARD_MODIFIER_LEFTSHIFT; *keycode = HID_KEY_4; return true;
    case '%': *mods = KEYBOARD_MODIFIER_LEFTSHIFT; *keycode = HID_KEY_5; return true;
    case '^': *mods = KEYBOARD_MODIFIER_LEFTSHIFT; *keycode = HID_KEY_6; return true;
    case '&': *mods = KEYBOARD_MODIFIER_LEFTSHIFT; *keycode = HID_KEY_7; return true;
    case '*': *mods = KEYBOARD_MODIFIER_LEFTSHIFT; *keycode = HID_KEY_8; return true;
    case '(': *mods = KEYBOARD_MODIFIER_LEFTSHIFT; *keycode = HID_KEY_9; return true;
    case ')': *mods = KEYBOARD_MODIFIER_LEFTSHIFT; *keycode = HID_KEY_0; return true;
    case '-': *keycode = HID_KEY_MINUS; return true;
    case '_': *mods = KEYBOARD_MODIFIER_LEFTSHIFT; *keycode = HID_KEY_MINUS; return true;
    case '=': *keycode = HID_KEY_EQUAL; return true;
    case '+': *mods = KEYBOARD_MODIFIER_LEFTSHIFT; *keycode = HID_KEY_EQUAL; return true;
    case '[': *keycode = HID_KEY_BRACKET_LEFT; return true;
    case '{': *mods = KEYBOARD_MODIFIER_LEFTSHIFT; *keycode = HID_KEY_BRACKET_LEFT; return true;
    case ']': *keycode = HID_KEY_BRACKET_RIGHT; return true;
    case '}': *mods = KEYBOARD_MODIFIER_LEFTSHIFT; *keycode = HID_KEY_BRACKET_RIGHT; return true;
    case '\\': *keycode = HID_KEY_BACKSLASH; return true;
    case '|': *mods = KEYBOARD_MODIFIER_LEFTSHIFT; *keycode = HID_KEY_BACKSLASH; return true;
    case ';': *keycode = HID_KEY_SEMICOLON; return true;
    case ':': *mods = KEYBOARD_MODIFIER_LEFTSHIFT; *keycode = HID_KEY_SEMICOLON; return true;
    case '\'': *keycode = HID_KEY_APOSTROPHE; return true;
    case '"': *mods = KEYBOARD_MODIFIER_LEFTSHIFT; *keycode = HID_KEY_APOSTROPHE; return true;
    case '`': *keycode = HID_KEY_GRAVE; return true;
    case '~': *mods = KEYBOARD_MODIFIER_LEFTSHIFT; *keycode = HID_KEY_GRAVE; return true;
    case ',': *keycode = HID_KEY_COMMA; return true;
    case '<': *mods = KEYBOARD_MODIFIER_LEFTSHIFT; *keycode = HID_KEY_COMMA; return true;
    case '.': *keycode = HID_KEY_PERIOD; return true;
    case '>': *mods = KEYBOARD_MODIFIER_LEFTSHIFT; *keycode = HID_KEY_PERIOD; return true;
    case '/': *keycode = HID_KEY_SLASH; return true;
    case '?': *mods = KEYBOARD_MODIFIER_LEFTSHIFT; *keycode = HID_KEY_SLASH; return true;
    default:
        return false;
    }
}

static void preview_copy(char *dst, size_t dst_sz, const char *src) {
    if (!dst || dst_sz == 0) {
        return;
    }
    dst[0] = '\0';
    if (!src) {
        return;
    }
    size_t n = 0;
    while (src[n] && n + 1 < dst_sz && n < 12) {
        char c = src[n];
        if (c == '\n' || c == '\r' || c == '\t') {
            c = ' ';
        }
        dst[n++] = c;
    }
    dst[n] = '\0';
}

static const char *media_label(uint16_t usage) {
    switch (usage) {
    case HID_USAGE_CONSUMER_PLAY_PAUSE: return "Play/Pause";
    case HID_USAGE_CONSUMER_SCAN_NEXT: return "Next";
    case HID_USAGE_CONSUMER_SCAN_PREVIOUS: return "Prev";
    case HID_USAGE_CONSUMER_STOP: return "Stop";
    default: return "Media";
    }
}

static void start_typing(const char *str, bool append_enter,
                         const char *toast1) {
    if (!str) {
        return;
    }
    char preview[13];
    preview_copy(preview, sizeof preview, str);
    oled_ui_show_toast(toast1, preview, 800);
    printf("%s: \"%s\"%s\n", toast1, str, append_enter ? " +Enter" : "");

    type_ptr = str;
    type_index = 0;
    type_enter = append_enter;
    type_gap = 0;
    typing_active = true;
}

static void typing_tick(void) {
    if (!typing_active) {
        return;
    }
    if (!usb_hid_tap_idle()) {
        return;
    }
    if (type_gap > 0) {
        type_gap--;
        return;
    }

    /* Finished string — optional trailing Enter. */
    if (!type_ptr || type_ptr[type_index] == '\0') {
        if (type_enter) {
            type_enter = false;
            usb_hid_tap(0, HID_KEY_ENTER);
            type_gap = TYPE_GAP_TICKS;
            return;
        }
        typing_active = false;
        type_ptr = NULL;
        return;
    }

    char c = type_ptr[type_index++];
    uint8_t mods = 0, key = 0;
    if (!ascii_to_hid(c, &mods, &key)) {
        /* Skip unknown; try next char next tick. */
        return;
    }
    usb_hid_tap(mods, key);
    type_gap = TYPE_GAP_TICKS;
}

static void fire_immediate(const action_t *action) {
    switch (action->type) {
    case ACTION_DISABLED:
        break;

    case ACTION_KEY:
    case ACTION_SHORTCUT:
        if (action->keycode != 0) {
            usb_hid_tap(action->mods, action->keycode);
        }
        break;

    case ACTION_VOLUME:
        switch (action->aux) {
        case VOLUME_UP:
            usb_hid_consumer_volume_up();
            oled_ui_notify_volume(+1);
            break;
        case VOLUME_DOWN:
            usb_hid_consumer_volume_down();
            oled_ui_notify_volume(-1);
            break;
        case VOLUME_MUTE:
            usb_hid_consumer_mute();
            oled_ui_notify_mute();
            break;
        default:
            break;
        }
        break;

    case ACTION_MEDIA: {
        usb_hid_consumer_usage(action->usage);
        const char *label = media_label(action->usage);
        oled_ui_show_toast("MEDIA", label, 600);
        break;
    }

    case ACTION_PROFILE:
        if (profiles_set_active(action->aux)) {
            const profile_t *p = profiles_active();
            oled_ui_set_profile_name(p->oled.title);
            oled_ui_show_toast("PROFILE", p->oled.title, 800);
        }
        break;

    case ACTION_MACRO:
        /* macros_fire() owns OLED toast + UART start/end logs. */
        if (!macros_fire(action->aux)) {
            printf("MACRO: fire failed id=%u\n", (unsigned)action->aux);
        }
        break;

    case ACTION_TEXT: {
        const char *s = text_table_get(action->aux);
        if (!s) {
            oled_ui_show_toast("TEXT", "bad id", 600);
            printf("TEXT: invalid text_id %u\n", (unsigned)action->aux);
            break;
        }
        start_typing(s, false, "TEXT");
        break;
    }

    case ACTION_URL: {
        const char *s = text_table_get(action->aux);
        if (!s) {
            oled_ui_show_toast("URL", "bad id", 600);
            printf("URL: invalid text_id %u\n", (unsigned)action->aux);
            break;
        }
        start_typing(s, true, "URL");
        break;
    }

    case ACTION_APP: {
        /*
         * Best-effort without host daemon: type the launch string from the
         * text table then Enter. Works when a terminal / launcher / Run dialog
         * already has focus. True OS app launch needs a host helper later.
         */
        const char *s = text_table_get(action->aux);
        if (!s) {
            oled_ui_show_toast("APP", "bad id", 600);
            printf("APP: invalid text_id %u\n", (unsigned)action->aux);
            break;
        }
        start_typing(s, true, "APP");
        break;
    }

    default:
        break;
    }
}

static bool needs_queue(uint8_t type) {
    return type == ACTION_TEXT || type == ACTION_URL || type == ACTION_APP;
}


bool actions_type_string(const char *s, bool append_enter) {
    if (!s || typing_active) {
        return false;
    }
    start_typing(s, append_enter, "TEXT");
    return true;
}

bool actions_type_text_id(uint8_t text_id, bool append_enter) {
    const char *s = text_table_get(text_id);
    if (!s) {
        printf("TEXT: invalid text_id %u\n", (unsigned)text_id);
        return false;
    }
    return actions_type_string(s, append_enter);
}

void actions_init(void) {
    q_head = q_tail = 0;
    type_ptr = NULL;
    type_index = 0;
    type_enter = false;
    type_gap = 0;
    typing_active = false;
}

bool actions_busy(void) {
    return typing_active || !queue_empty();
}

void actions_fire(const action_t *action) {
    if (!action) {
        return;
    }

    /* Typing jobs serialize through the queue so encoder/matrix never block. */
    if (needs_queue(action->type)) {
        if (typing_active || !queue_empty()) {
            if (!queue_push(action)) {
                printf("actions: queue full, drop type=%u\n", action->type);
            }
            return;
        }
        fire_immediate(action);
        return;
    }

    /* KEY/SHORTCUT one-shots: wait if typer owns the keyboard. */
    if ((action->type == ACTION_KEY || action->type == ACTION_SHORTCUT) &&
        actions_busy()) {
        if (!queue_push(action)) {
            printf("actions: queue full, drop KEY/SHORTCUT\n");
        }
        return;
    }

    fire_immediate(action);
}

void actions_task(void) {
    typing_tick();

    /* Start next queued job when typer is idle. */
    if (!typing_active && usb_hid_tap_idle()) {
        action_t next;
        if (queue_pop(&next)) {
            fire_immediate(&next);
        }
    }
}
