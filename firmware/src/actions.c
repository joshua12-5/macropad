#include "actions.h"

#include "oled_ui.h"
#include "profiles.h"
#include "usb_hid_app.h"

#include <stdio.h>

void actions_init(void) {
}

void actions_fire(const action_t *action) {
    if (!action) {
        return;
    }

    switch (action->type) {
    case ACTION_DISABLED:
        break;

    case ACTION_KEY:
    case ACTION_SHORTCUT:
        /* One-shot tap via helper (encoder shouldn't normally bind these in v1,
         * but support it for testing). */
        usb_hid_tap(action->mods, action->keycode);
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

    case ACTION_MEDIA:
        usb_hid_consumer_usage(action->usage);
        oled_ui_show_toast("MEDIA", "", 600);
        break;

    case ACTION_PROFILE:
        if (profiles_set_active(action->aux)) {
            const profile_t *p = profiles_active();
            oled_ui_set_profile_name(p->oled.title);
            oled_ui_show_toast("PROFILE", p->oled.title, 800);
        }
        break;

    case ACTION_MACRO:
    case ACTION_TEXT:
    case ACTION_APP:
    case ACTION_URL:
        /* Implemented in Steps 8–9 / host helper. */
        oled_ui_show_toast("TODO", "Action type", 700);
        break;

    default:
        break;
    }
}
