#pragma once

// TIR-B tier memory: T0 VRAM arena + T1 pinned host arena booking layer.
// This slice owns slot allocation/merging, pinning, LRU eviction and the
// explicit failure state. CUDA copies are delegated to a Backend so the
// booking logic is testable without a GPU.

#include <cstddef>
#include <cstdint>
#include <map>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

namespace tier {

enum class Tier : int { T0_VRAM = 0, T1_HOST = 1, T2_DISK = 2 };
enum class State { ABSENT, LOADING, RESIDENT, FAILED };

struct Config {
    size_t t0_bytes = 0;
    size_t t1_bytes = 0;
    size_t t2_bytes = 0;   // B1: 0
    size_t align = 256;
    int    copy_streams = 2;
};

struct Stats {
    unsigned long long t0_bytes = 0;
    unsigned long long t1_bytes = 0;
    unsigned long long t2_bytes = 0;
    unsigned long long h2d_bytes = 0;
    unsigned long long h2d_us = 0;
    unsigned long long disk_bytes = 0;
    unsigned long long disk_us = 0;
    unsigned long long evictions[3] = {0, 0, 0};
    unsigned long long hits[3] = {0, 0, 0};
    int layer = -1;
    int n_layer = 0;
    int fail = 0;
    char fail_reason[256] = {0};
};

// Minimal device abstraction. The CUDA implementation lives in the runtime
// integration slice; tests provide a fake.
struct Backend {
    virtual ~Backend() = default;
    virtual void * alloc_vram(size_t bytes) = 0;
    virtual void   free_vram(void * ptr) = 0;
    virtual void * alloc_host(size_t bytes) = 0;
    virtual void   free_host(void * ptr) = 0;
    virtual bool   copy_h2d(void * dst, const void * src, size_t bytes, size_t * us) = 0;
    virtual bool   copy_d2h(void * dst, const void * src, size_t bytes, size_t * us) = 0;
};

struct Slot {
    size_t off = 0;
    size_t size = 0;      // aligned envelope
    void * owner = nullptr;
    int    pins = 0;
    uint64_t tick = 0;
    bool   used = false;
};

class Arena {
public:
    Arena() = default;
    Arena(Tier tier, void * base, size_t bytes, size_t align);

    bool   valid() const { return base_ != nullptr; }
    void * base() const { return base_; }
    Tier   tier() const { return tier_; }
    size_t capacity() const { return capacity_; }
    size_t used_bytes() const { return used_; }
    size_t free_bytes() const { return capacity_ - used_; }
    size_t align_up(size_t bytes) const;

    // First-fit allocation. Returns a negative value when the request cannot fit.
    long alloc(size_t bytes, void * owner);
    bool free(long slot);
    bool can_fit(size_t bytes) const;

    // Oldest unpinned used slot, or -1.
    long lru_victim() const;

    long n_slots() const { return (long) slots_.size(); }
    const Slot & slot(long idx) const { return slots_[idx]; }
    Slot & slot_mut(long idx) { return slots_[idx]; }
    void * ptr(long idx) const { return (char *) base_ + slots_[idx].off; }

private:
    void insert_free(size_t off, size_t size);
    void merge_free();

    Tier tier_ = Tier::T0_VRAM;
    void * base_ = nullptr;
    size_t capacity_ = 0;
    size_t align_ = 256;
    size_t used_ = 0;
    std::vector<Slot> slots_;
    std::map<size_t, size_t> free_; // offset -> size
};

class TierMemory {
public:
    TierMemory() = default;
    ~TierMemory();

    bool init(const Config & cfg, Backend * backend);
    void shutdown();

    // Load-time registration. host_ptr may be null until B1d fills it.
    bool register_tensor(void * key, size_t bytes, Tier home, void * host_ptr = nullptr);
    void set_host_ptr(void * key, void * host_ptr);

    // Bring the tensor to T0 and pin it. Returns false and latches failure.
    bool ensure(void * key);
    void unpin(void * key);

    bool prefetch(int layer); // B1b: no-op

    Stats stats() const;
    bool failed() const;
    const std::string & fail_reason() const;

    // test hooks
    size_t t0_free_bytes() const;
    size_t t0_used_bytes() const;
    long t0_slots() const;
    void * t0_ptr(void * key);

private:
    struct Entry {
        size_t bytes = 0;
        Tier home = Tier::T1_HOST;
        State state = State::ABSENT;
        long slot = -1;
        int pins = 0;
        uint64_t tick = 0;
        void * host_ptr = nullptr;
    };

    void set_fail(const std::string & why);
    long evict_one();
    uint64_t next_tick() { return ++tick_; }
    Entry * find(void * key);

    mutable std::mutex mtx_;
    Config cfg_;
    Backend * backend_ = nullptr;
    Arena t0_;
    Arena t1_;
    std::unordered_map<void *, Entry> entries_;
    Stats stats_;
    bool failed_ = false;
    std::string fail_reason_;
    uint64_t tick_ = 0;
};

} // namespace tier
