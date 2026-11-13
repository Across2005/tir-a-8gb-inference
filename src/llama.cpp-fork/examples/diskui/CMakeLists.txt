# SPDX-License-Identifier: Apache-2.0
# Derived from Horn-Studio/diskinfer-windows (Apache-2.0); modified for TIR-A.
set(TARGET llama-diskui)
add_executable(${TARGET} diskui.cpp)
install(TARGETS ${TARGET} RUNTIME)
target_include_directories(${TARGET} PRIVATE ${CMAKE_SOURCE_DIR}/src)
target_link_libraries(${TARGET} PRIVATE llama ${CMAKE_THREAD_LIBS_INIT})
target_compile_features(${TARGET} PRIVATE cxx_std_17)
