// Unit tests for the TIR-B tier memory booking layer (no GPU required).
// Build (VS dev prompt):
//   cl /nologo /std:c++17 /EHsc /O2 /I src src/tier-memory.cpp test/tier-memory/tier-memory-test.cpp /Fe:build/tier-memory-test.exe
#include "tier-memory.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

namespace {

int g_failures = 0;

#define CHECK(cond) do { \
    if (!(cond)) { \
        std::printf("[FAIL] %s:%d: %s\n", __FILE__, __LINE__, #cond); \
        g_failures++; \
    } \
} while (0)

struct FakeBackend : tier::Backend {
    size_t vram_allocs = 0;
    size_t host_allocs = 0;
    void * alloc_vram(size_t bytes) override { vram_allocs++; return _aligned_malloc(bytes, 256); }
    void free_vram(void * ptr) override { _aligned_free(ptr); }
    void * alloc_host(size_t bytes) override { host_allocs++; return _aligned_malloc(bytes, 256); }
    void free_host(void * ptr) override { _aligned_free(ptr); }
    bool copy_h2d(void * dst, const void * src, size_t bytes, size_t * us) override {
        std::memcpy(dst, src, bytes);
        if (us != nullptr) { *us = 7; }
        return true;
    }
    bool copy_d2h(void * dst, const void * src, size_t bytes, size_t * us) override {
        std::memcpy(dst, src, bytes);
        if (us != nullptr) { *us = 7; }
        return true;
    }
};

tier::Config make_config(size_t t0, size_t t1 = 1024) {
    tier::Config cfg;
    cfg.t0_bytes = t0;
    cfg.t1_bytes = t1;
    cfg.align = 256;
    cfg.copy_streams = 2;
    return cfg;
}

void test_alignment_and_split() {
    FakeBackend backend;
    tier::TierMemory mem;
    CHECK(mem.init(make_config(1024), &backend));
    CHECK(mem.t0_free_bytes() == 1024);

    int a = 0;
    int b = 0;
    char host_a[400] = {0};
    char host_b[400] = {0};
    CHECK(mem.register_tensor(&a, 400, tier::Tier::T0_VRAM, host_a));
    CHECK(mem.register_tensor(&b, 400, tier::Tier::T0_VRAM, host_b));
    CHECK(mem.ensure(&a));
    CHECK(mem.t0_used_bytes() == 512); // 400 rounded to 256
    CHECK(mem.ensure(&b));
    CHECK(mem.t0_used_bytes() == 1024);
    CHECK(!mem.failed());
    mem.unpin(&a);
    mem.unpin(&b);
    mem.shutdown();
    CHECK(backend.vram_allocs == 1);
    CHECK(backend.host_allocs == 1);
}

void test_pin_prevents_eviction() {
    FakeBackend backend;
    tier::TierMemory mem;
    CHECK(mem.init(make_config(512), &backend));
    int a = 0;
    char host[100] = {0};
    CHECK(mem.register_tensor(&a, 400, tier::Tier::T0_VRAM, host));
    CHECK(mem.ensure(&a));      // pins=1
    CHECK(mem.ensure(&a));      // same slot, pins=2
    CHECK(mem.t0_slots() == 1);
    CHECK(mem.ensure(&a));      // pins=3
    CHECK(mem.t0_slots() == 1);
    mem.unpin(&a);
    mem.unpin(&a);
    mem.unpin(&a);
    CHECK(mem.stats().hits[0] >= 3);
    mem.shutdown();
}

void test_merge_on_free() {
    FakeBackend backend;
    tier::TierMemory mem;
    CHECK(mem.init(make_config(768), &backend));
    int a = 0, b = 0, c = 0;
    char host[300] = {0};
    CHECK(mem.register_tensor(&a, 100, tier::Tier::T0_VRAM, host));
    CHECK(mem.register_tensor(&b, 100, tier::Tier::T0_VRAM, host));
    CHECK(mem.register_tensor(&c, 100, tier::Tier::T0_VRAM, host));
    CHECK(mem.ensure(&a));
    CHECK(mem.ensure(&b));
    CHECK(mem.ensure(&c));
    CHECK(mem.t0_used_bytes() == 768);
    mem.unpin(&a);
    mem.unpin(&b);
    mem.unpin(&c);

    int d = 0;
    CHECK(mem.register_tensor(&d, 700, tier::Tier::T0_VRAM, host));
    mem.set_host_ptr(&d, host);
    CHECK(mem.ensure(&d)); // needs merge to fit 768 after eviction
    CHECK(mem.stats().evictions[0] >= 1);
    CHECK(!mem.failed());
    mem.shutdown();
}

void test_h2d_stats_and_copy() {
    FakeBackend backend;
    tier::TierMemory mem;
    CHECK(mem.init(make_config(1024), &backend));
    int a = 0;
    char host[300];
    std::memset(host, 7, sizeof(host));
    CHECK(mem.register_tensor(&a, 300, tier::Tier::T0_VRAM, host));
    CHECK(mem.ensure(&a));
    tier::Stats st = mem.stats();
    CHECK(st.h2d_bytes == 300);
    CHECK(st.h2d_us == 7);
    const unsigned char * dst = (const unsigned char *) mem.t0_ptr(&a);
    CHECK(dst != nullptr);
    CHECK(dst[0] == 7 && dst[299] == 7);
    mem.unpin(&a);
    mem.shutdown();
}

void test_failure_path() {
    FakeBackend backend;
    tier::TierMemory mem;
    CHECK(mem.init(make_config(1024), &backend));
    int big = 0;
    char host[4096] = {0};
    CHECK(mem.register_tensor(&big, 4096, tier::Tier::T0_VRAM, host));
    CHECK(!mem.ensure(&big));
    CHECK(mem.failed());
    CHECK(mem.stats().fail == 1);
    CHECK(std::string(mem.fail_reason()).find("out of T0") != std::string::npos);
    mem.shutdown();
}

void test_unregistered_tensor() {
    FakeBackend backend;
    tier::TierMemory mem;
    CHECK(mem.init(make_config(1024), &backend));
    int unknown = 0;
    CHECK(!mem.ensure(&unknown));
    CHECK(mem.failed());
    mem.shutdown();
}

void test_arena_lru_order() {
    FakeBackend backend;
    tier::TierMemory mem;
    CHECK(mem.init(make_config(1024), &backend));
    int a = 0, b = 0;
    char host[400] = {0};
    CHECK(mem.register_tensor(&a, 400, tier::Tier::T0_VRAM, host));
    CHECK(mem.register_tensor(&b, 400, tier::Tier::T0_VRAM, host));
    CHECK(mem.ensure(&a)); // a older
    CHECK(mem.ensure(&b));
    mem.unpin(&a);
    mem.unpin(&b);
    int c = 0;
    CHECK(mem.register_tensor(&c, 400, tier::Tier::T0_VRAM, host));
    CHECK(mem.ensure(&c)); // should evict a (oldest tick)
    CHECK(mem.stats().evictions[0] == 1);
    mem.unpin(&c);
    mem.shutdown();
}

void test_large_capacity_booking() {
    FakeBackend backend;
    tier::TierMemory mem;
    tier::Config cfg = make_config((size_t) 1024 * 1024 * 1024, (size_t) 2 * 1024 * 1024 * 1024);
    CHECK(mem.init(cfg, &backend));
    tier::Stats st = mem.stats();
    CHECK(st.t0_bytes == 1024ull * 1024 * 1024);
    CHECK(st.t1_bytes == 2ull * 1024 * 1024 * 1024);
    CHECK(mem.t0_free_bytes() == 1024ull * 1024 * 1024);
    mem.shutdown();
}

} // namespace

int main() {
    test_alignment_and_split();
    test_pin_prevents_eviction();
    test_merge_on_free();
    test_h2d_stats_and_copy();
    test_failure_path();
    test_unregistered_tensor();
    test_arena_lru_order();
    test_large_capacity_booking();
    if (g_failures == 0) {
        std::printf("tier-memory tests: 8/8 PASS\n");
        return 0;
    }
    std::printf("tier-memory tests: %d failure(s)\n", g_failures);
    return 1;
}
