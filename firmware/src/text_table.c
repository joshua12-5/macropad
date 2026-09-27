#include "text_table.h"

/*
 * Fixed ASCII snippets for TEXT / URL / APP actions and MACRO_TEXT steps.
 * Total string bytes (excluding pointers) stays well under 512.
 */
static const char *const k_strings[TEXT_TABLE_COUNT] = {
    [TEXT_ID_HELLO]       = "Hello",
    [TEXT_ID_GITHUB_URL]  = "https://github.com/joshua12-5/macropad",
    [TEXT_ID_GIT_STATUS]  = "git status\n",
    [TEXT_ID_CONSOLE_LOG] = "console.log(",
    [TEXT_ID_NOTEPAD]     = "notepad",
    [TEXT_ID_CALC]        = "calc",
    [TEXT_ID_HELLO_WORLD] = "Hello, World!",
    [TEXT_ID_LS_LA]       = "ls -la\n",
};

const char *text_table_get(uint8_t text_id) {
    if (text_id >= TEXT_TABLE_COUNT) {
        return NULL;
    }
    return k_strings[text_id];
}

