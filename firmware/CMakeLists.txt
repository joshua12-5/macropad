cmake_minimum_required(VERSION 3.13)

set(PICO_BOARD pico CACHE STRING "Board type")

include(pico_sdk_import.cmake)

project(macropad_step18 C CXX ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

pico_sdk_init()

add_executable(macropad_step18
    src/main.c
    src/matrix.c
    src/encoder.c
    src/usb_descriptors.c
    src/usb_hid_app.c
    src/config_protocol.c
    src/profile_blob.c
    src/macro_blob.c
    src/storage.c
    src/oled_driver.c
    src/oled_font.c
    src/oled_ui.c
    src/profiles.c
    src/actions.c
    src/text_table.c
    src/macros.c
)

target_include_directories(macropad_step18 PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/include
)

target_link_libraries(macropad_step18
    pico_stdlib
    hardware_gpio
    hardware_flash
    hardware_sync
    hardware_i2c
    tinyusb_device
    tinyusb_board
)

pico_enable_stdio_uart(macropad_step18 1)
pico_enable_stdio_usb(macropad_step18 0)

pico_add_extra_outputs(macropad_step18)
