cmake_minimum_required(VERSION 3.13)

# Step 22: verified with Pico SDK 2.1.1 + PICO_BOARD=waveshare_rp2040_zero
# (2 MiB flash, W25Q080 boot2 @ clkdiv 4). PICO_BOARD=pico also builds.
set(PICO_BOARD waveshare_rp2040_zero CACHE STRING "Board type")

include(pico_sdk_import.cmake)

project(macropad_step23 C CXX ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

pico_sdk_init()

set(MACROPAD_TESTED_SDK "2.1.1")
if (NOT PICO_SDK_VERSION_STRING VERSION_EQUAL MACROPAD_TESTED_SDK)
    message(WARNING "Pico SDK ${PICO_SDK_VERSION_STRING}; firmware verified with ${MACROPAD_TESTED_SDK}")
endif()

add_executable(macropad_step23
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

# Step 22: warnings on for our sources (SDK/TinyUSB sources keep their own flags).
target_compile_options(macropad_step23 PRIVATE -Wall -Wextra)

target_include_directories(macropad_step23 PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/include
)

target_link_libraries(macropad_step23
    pico_stdlib
    hardware_gpio
    hardware_flash
    hardware_sync
    hardware_i2c
    pico_flash
    tinyusb_device
)

pico_enable_stdio_uart(macropad_step23 1)
pico_enable_stdio_usb(macropad_step23 0)

pico_add_extra_outputs(macropad_step23)
