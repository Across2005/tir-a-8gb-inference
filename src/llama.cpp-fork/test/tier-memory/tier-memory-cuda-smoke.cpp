// Real-CUDA smoke for the tier memory booking layer: allocate 1 GiB T0 VRAM
// and 2 GiB T1 pinned host, register a tensor, copy it, check stats.
// Build (VS dev prompt):
//   cl /nologo /std:c++17 /EHsc /O2 /I <fork>\src /I <cuda>\include ^
//      <fork>\src\tier-memory.cpp tier-memory-cuda-smoke.cpp ^
//      /Fe:tier-memory-cuda-smoke.exe <cuda>\lib\x64\cudart.lib
#include "tier-memory.h"

#include <cuda_runtime.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace {

int g_failures = 0;

#define CHECK(cond) do { \
    if (!(cond)) { \
        std::printf("[FAIL] %s:%d: %s\n", __FILE__, __LINE__, #cond); \
        g_failures++; \
    } \
} while (0)

struct CudaBackend : tier::Backend {
    void * alloc_vram(size_t bytes) override {
        void * ptr = nullptr;
        return cudaMalloc(&ptr, bytes) == cudaSuccess ? ptr : nullptr;
    }
    void free_vram(void * ptr) override { cudaFree(ptr); }
    void * alloc_host(size_t bytes) override {
        void * ptr = nullptr;
        return cudaHostAlloc(&ptr, bytes, cudaHostAllocDefault) == cudaSuccess ? ptr : nullptr;
    }
    void free_host(void * ptr) override { cudaFreeHost(ptr); }
    bool copy_h2d(void * dst, const void * src, size_t bytes, size_t * us) override {
        const cudaError_t err = cudaMemcpy(dst, src, bytes, cudaMemcpyHostToDevice);
        if (us != nullptr) { *us = 1; }
        return err == cudaSuccess;
    }
    bool copy_d2h(void * dst, const void * src, size_t bytes, size_t * us) override {
        const cudaError_t err = cudaMemcpy(dst, src, bytes, cudaMemcpyDeviceToHost);
        if (us != nullptr) { *us = 1; }
        return err == cudaSuccess;
    }
};

} // namespace

int main() {
    cudaFree(nullptr); // initialize runtime
    int device = 0;
    if (cudaGetDevice(&device) != cudaSuccess) {
        std::printf("[FAIL] no CUDA device\n");
        return 1;
    }
    size_t free_before = 0, total = 0;
    cudaMemGetInfo(&free_before, &total);
    std::printf("cuda free before = %.0f MiB / total %.0f MiB\n",
                free_before / 1048576.0, total / 1048576.0);

    CudaBackend backend;
    tier::TierMemory mem;
    tier::Config cfg;
    cfg.t0_bytes = 1ull << 30;
    cfg.t1_bytes = 2ull << 30;
    cfg.align = 2ull << 20; // 2 MiB
    cfg.copy_streams = 2;
    CHECK(mem.init(cfg, &backend));
    tier::Stats st = mem.stats();
    CHECK(st.t0_bytes == (1ull << 30));
    CHECK(st.t1_bytes == (2ull << 30));
    CHECK(mem.t0_free_bytes() == (1ull << 30));

    const size_t tensor_bytes = 64ull << 20; // 64 MiB
    void * host = _aligned_malloc(tensor_bytes, 2ull << 20);
    CHECK(host != nullptr);
    std::memset(host, 0x3c, tensor_bytes);

    int tensor_key = 0;
    CHECK(mem.register_tensor(&tensor_key, tensor_bytes, tier::Tier::T0_VRAM, host));
    CHECK(mem.ensure(&tensor_key));
    st = mem.stats();
    CHECK(st.h2d_bytes == tensor_bytes);
    CHECK(st.fail == 0);
    CHECK(mem.t0_used_bytes() == tensor_bytes);
    mem.unpin(&tensor_key);
    mem.shutdown();
    _aligned_free(host);

    size_t free_after = 0;
    cudaMemGetInfo(&free_after, &total);
    std::printf("cuda free after  = %.0f MiB (delta %.0f MiB)\n",
                free_after / 1048576.0, (free_before - free_after) / 1048576.0);
    if (g_failures == 0) {
        std::printf("tier-memory cuda smoke: PASS\n");
        return 0;
    }
    std::printf("tier-memory cuda smoke: %d failure(s)\n", g_failures);
    return 1;
}
