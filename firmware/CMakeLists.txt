cmake_minimum_required(VERSION 3.13)

set(PICO_BOARD pico CACHE STRING "Board type")

include(pico_sdk_import.cmake)

project(macropad_step4 C CXX ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

pico_sdk_init()

add_executable(macropad_step4
    src/main.c
    src/matrix.c
    src/usb_descriptors.c
    src/usb_hid_app.c
)

target_include_directories(macropad_step4 PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/include
)

target_link_libraries(macropad_step4
    pico_stdlib
    hardware_gpio
    tinyusb_device
    tinyusb_board
)

# Keep UART for debug logs; USB is owned by TinyUSB HID (not CDC stdio).
pico_enable_stdio_uart(macropad_step4 1)
pico_enable_stdio_usb(macropad_step4 0)

pico_add_extra_outputs(macropad_step4)
