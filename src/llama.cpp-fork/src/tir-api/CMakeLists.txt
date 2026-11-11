add_library(tir SHARED
    tir_core.cpp
    tir_chat.cpp
    tir_generate.cpp
    tir_mtp.cpp
)
target_include_directories(tir PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_definitions(tir PRIVATE TIR_BUILD)
target_compile_features(tir PRIVATE cxx_std_17)
target_link_libraries(tir PRIVATE llama)
if (LLAMA_BUILD_COMMON)
    target_link_libraries(tir PRIVATE llama-common)
endif()
set_target_properties(tir PROPERTIES OUTPUT_NAME tir)

add_executable(tir-test-abi ${PROJECT_SOURCE_DIR}/tests/tir-api/test_abi_basic.c)
target_link_libraries(tir-test-abi PRIVATE tir)
target_include_directories(tir-test-abi PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

add_executable(tir-test-abi-load ${PROJECT_SOURCE_DIR}/tests/tir-api/test_abi_load.c)
target_link_libraries(tir-test-abi-load PRIVATE tir)
target_include_directories(tir-test-abi-load PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

add_executable(tir-test-generate ${PROJECT_SOURCE_DIR}/tests/tir-api/test_generate.c)
target_link_libraries(tir-test-generate PRIVATE tir)
target_include_directories(tir-test-generate PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

add_executable(tir-test-profile ${PROJECT_SOURCE_DIR}/tests/tir-api/test_profile.c)
target_link_libraries(tir-test-profile PRIVATE tir)
target_include_directories(tir-test-profile PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

add_executable(tir-test-spec ${PROJECT_SOURCE_DIR}/tests/tir-api/test_spec.c)
target_link_libraries(tir-test-spec PRIVATE tir)
target_include_directories(tir-test-spec PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

add_executable(tir-test-draft-compat ${PROJECT_SOURCE_DIR}/tests/tir-api/test_draft_compat.cpp)
target_link_libraries(tir-test-draft-compat PRIVATE llama llama-common)
target_include_directories(tir-test-draft-compat PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR} ${PROJECT_SOURCE_DIR}/common ${PROJECT_SOURCE_DIR}/include)

add_executable(tir-test-mtp ${PROJECT_SOURCE_DIR}/tests/tir-api/test_mtp.c)
target_link_libraries(tir-test-mtp PRIVATE tir)
target_include_directories(tir-test-mtp PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

add_executable(tir-test-prefill ${PROJECT_SOURCE_DIR}/tests/tir-api/test_prefill.c)
target_link_libraries(tir-test-prefill PRIVATE tir)
target_include_directories(tir-test-prefill PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

add_executable(tir-test-chat ${PROJECT_SOURCE_DIR}/tests/tir-api/test_chat.c)
target_link_libraries(tir-test-chat PRIVATE tir)
target_include_directories(tir-test-chat PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

add_executable(tir-bench ${PROJECT_SOURCE_DIR}/tests/tir-api/bench.c)
target_link_libraries(tir-bench PRIVATE tir)
target_include_directories(tir-bench PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

add_executable(tir-bench-ceiling ${PROJECT_SOURCE_DIR}/tests/tir-api/bench_ceiling.c)
target_link_libraries(tir-bench-ceiling PRIVATE tir)
target_include_directories(tir-bench-ceiling PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
