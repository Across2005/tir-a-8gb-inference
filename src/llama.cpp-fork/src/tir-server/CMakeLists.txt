add_library(tir-stream STATIC stream.cpp)
target_include_directories(tir-stream PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_features(tir-stream PRIVATE cxx_std_17)

add_executable(tir-test-stream ${PROJECT_SOURCE_DIR}/tests/tir-server/test_stream.cpp)
target_link_libraries(tir-test-stream PRIVATE tir-stream)
target_compile_features(tir-test-stream PRIVATE cxx_std_17)
