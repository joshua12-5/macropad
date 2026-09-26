#pragma once

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Firmware string table for TEXT / URL / APP actions (schema aux = text_id).
 * Keep total storage small (<512 bytes of string data).
 */
#define TEXT_TABLE_COUNT 8

/* Well-known ids (must match text_table.c). */
#define TEXT_ID_HELLO       0
#define TEXT_ID_GITHUB_URL  1
#define TEXT_ID_GIT_STATUS  2
#define TEXT_ID_CONSOLE_LOG 3
#define TEXT_ID_NOTEPAD     4
#define TEXT_ID_CALC        5
#define TEXT_ID_HELLO_WORLD 6
#define TEXT_ID_LS_LA       7

const char *text_table_get(uint8_t text_id);
uint8_t text_table_count(void);

#ifdef __cplusplus
}
#endif
