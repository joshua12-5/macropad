cmake_minimum_required(VERSION 3.13)

set(PICO_BOARD pico CACHE STRING "Board type")

include(pico_sdk_import.cmake)

project(macropad_step5 C CXX ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

pico_sdk_init()

add_executable(macropad_step5
    src/main.c
    src/matrix.c
    src/encoder.c
    src/usb_descriptors.c
    src/usb_hid_app.c
)

target_include_directories(macropad_step5 PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/include
)

target_link_libraries(macropad_step5
    pico_stdlib
    hardware_gpio
    tinyusb_device
    tinyusb_board
)

pico_enable_stdio_uart(macropad_step5 1)
pico_enable_stdio_usb(macropad_step5 0)

pico_add_extra_outputs(macropad_step5)
