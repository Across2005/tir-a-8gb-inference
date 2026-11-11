set(TARGET tierspike)
add_executable(${TARGET} tierspike.cpp)
target_link_libraries(${TARGET} PRIVATE llama ${CMAKE_THREAD_LIBS_INIT})
target_compile_features(${TARGET} PRIVATE cxx_std_17)

# spike driver talks to the CUDA runtime directly (mapped host / H2D staging)
find_package(CUDAToolkit REQUIRED)
target_link_libraries(${TARGET} PRIVATE CUDA::cudart)
