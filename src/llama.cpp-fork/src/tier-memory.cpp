#include "tier-memory.h"

#include <algorithm>
#include <cstring>

namespace tier {

namespace {
size_t align_up(size_t value, size_t align) {
    if (align == 0) {
        return value;
    }
    return (value + align - 1) / align * align;
}
} // namespace

Arena::Arena(Tier tier, void * base, size_t bytes, size_t align)
    : tier_(tier), base_(base), capacity_(bytes), align_(align == 0 ? 256 : align) {
    if (base_ != nullptr && capacity_ > 0) {
        insert_free(0, capacity_);
    }
}

size_t Arena::align_up(size_t bytes) const {
    return ::tier::align_up(bytes, align_);
}

void Arena::insert_free(size_t off, size_t size) {
    if (size == 0) {
        return;
    }
    free_[off] = size;
}

void Arena::merge_free() {
    auto it = free_.begin();
    while (it != free_.end()) {
        auto next = std::next(it);
        if (next == free_.end()) {
            break;
        }
        if (it->first + it->second == next->first) {
            it->second += next->second;
            free_.erase(next);
        } else {
            ++it;
        }
    }
}

bool Arena::can_fit(size_t bytes) const {
    const size_t need = align_up(bytes);
    for (const auto & [off, size] : free_) {
        (void) off;
        if (size >= need) {
            return true;
        }
    }
    return false;
}

long Arena::alloc(size_t bytes, void * owner) {
    const size_t need = align_up(bytes);
    if (need == 0) {
        return -1;
    }
    for (auto it = free_.begin(); it != free_.end(); ++it) {
        if (it->second < need) {
            continue;
        }
        const size_t off = it->first;
        const size_t size = it->second;
        free_.erase(it);
        if (size > need) {
            insert_free(off + need, size - need);
        }
        Slot slot;
        slot.off = off;
        slot.size = need;
        slot.owner = owner;
        slot.pins = 0;
        slot.tick = 0;
        slot.used = true;
        used_ += need;
        slots_.push_back(slot);
        return (long) slots_.size() - 1;
    }
    return -1;
}

bool Arena::free(long idx) {
    if (idx < 0 || (size_t) idx >= slots_.size()) {
        return false;
    }
    Slot & slot = slots_[(size_t) idx];
    if (!slot.used) {
        return false;
    }
    if (slot.pins > 0) {
        return false;
    }
    used_ -= slot.size;
    insert_free(slot.off, slot.size);
    slot.used = false;
    slot.owner = nullptr;
    slot.pins = 0;
    merge_free();
    return true;
}

long Arena::lru_victim() const {
    long best = -1;
    uint64_t best_tick = UINT64_MAX;
    for (size_t i = 0; i < slots_.size(); ++i) {
        const Slot & slot = slots_[i];
        if (!slot.used || slot.pins > 0) {
            continue;
        }
        if (slot.tick < best_tick) {
            best_tick = slot.tick;
            best = (long) i;
        }
    }
    return best;
}

TierMemory::~TierMemory() {
    shutdown();
}

bool TierMemory::init(const Config & cfg, Backend * backend) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (backend == nullptr) {
        fail_reason_ = "tier: null backend";
        return false;
    }
    cfg_ = cfg;
    backend_ = backend;
    stats_ = Stats{};

    void * t0 = cfg.t0_bytes > 0 ? backend_->alloc_vram(cfg.t0_bytes) : nullptr;
    if (cfg.t0_bytes > 0 && t0 == nullptr) {
        set_fail("tier: cannot allocate T0 VRAM");
        return false;
    }
    void * t1 = cfg.t1_bytes > 0 ? backend_->alloc_host(cfg.t1_bytes) : nullptr;
    if (cfg.t1_bytes > 0 && t1 == nullptr) {
        if (t0 != nullptr) {
            backend_->free_vram(t0);
        }
        set_fail("tier: cannot allocate T1 pinned host");
        return false;
    }
    t0_ = Arena(Tier::T0_VRAM, t0, cfg.t0_bytes, cfg.align);
    t1_ = Arena(Tier::T1_HOST, t1, cfg.t1_bytes, cfg.align);
    stats_.t0_bytes = cfg.t0_bytes;
    stats_.t1_bytes = cfg.t1_bytes;
    stats_.t2_bytes = cfg.t2_bytes;
    return true;
}

void TierMemory::shutdown() {
    std::lock_guard<std::mutex> lock(mtx_);
    if (backend_ != nullptr) {
        if (t0_.valid()) {
            backend_->free_vram(t0_.base());
        }
        if (t1_.valid()) {
            backend_->free_host(t1_.base());
        }
    }
    backend_ = nullptr;
    t0_ = Arena();
    t1_ = Arena();
    entries_.clear();
    failed_ = false;
    fail_reason_.clear();
}

bool TierMemory::register_tensor(void * key, size_t bytes, Tier home, void * host_ptr) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (failed_) {
        return false;
    }
    Entry entry;
    entry.bytes = bytes;
    entry.home = home;
    entry.host_ptr = host_ptr;
    entries_[key] = entry;
    return true;
}

void TierMemory::set_host_ptr(void * key, void * host_ptr) {
    std::lock_guard<std::mutex> lock(mtx_);
    auto it = entries_.find(key);
    if (it != entries_.end()) {
        it->second.host_ptr = host_ptr;
    }
}

TierMemory::Entry * TierMemory::find(void * key) {
    auto it = entries_.find(key);
    return it == entries_.end() ? nullptr : &it->second;
}

long TierMemory::evict_one() {
    const long victim = t0_.lru_victim();
    if (victim < 0) {
        return -1;
    }
    Slot & slot = t0_.slot_mut(victim);
    Entry * entry = find(slot.owner);
    if (entry != nullptr) {
        entry->state = State::ABSENT;
        entry->slot = -1;
    }
    t0_.free(victim);
    stats_.evictions[(int) Tier::T0_VRAM]++;
    return victim;
}

bool TierMemory::ensure(void * key) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (failed_) {
        return false;
    }
    Entry * entry = find(key);
    if (entry == nullptr) {
        set_fail("tier: ensure on unregistered tensor");
        return false;
    }
    if (entry->state == State::RESIDENT && entry->slot >= 0 && t0_.slot(entry->slot).used) {
        entry->pins++;
        t0_.slot_mut(entry->slot).pins++;
        t0_.slot_mut(entry->slot).tick = next_tick();
        stats_.hits[(int) Tier::T0_VRAM]++;
        return true;
    }
    if (!t0_.can_fit(entry->bytes)) {
        while (!t0_.can_fit(entry->bytes)) {
            if (evict_one() < 0) {
                set_fail("tier: out of T0");
                return false;
            }
        }
    }
    const long slot = t0_.alloc(entry->bytes, key);
    if (slot < 0) {
        set_fail("tier: out of T0");
        return false;
    }
    if (entry->host_ptr != nullptr) {
        size_t us = 0;
        if (!backend_->copy_h2d(t0_.ptr(slot), entry->host_ptr, entry->bytes, &us)) {
            t0_.free(slot);
            set_fail("tier: H2D copy failed");
            return false;
        }
        stats_.h2d_bytes += entry->bytes;
        stats_.h2d_us += us;
    }
    Slot & slot_ref = t0_.slot_mut(slot);
    slot_ref.pins = 1;
    slot_ref.tick = next_tick();
    entry->state = State::RESIDENT;
    entry->slot = slot;
    entry->pins = 1;
    stats_.hits[(int) Tier::T0_VRAM]++;
    return true;
}

void TierMemory::unpin(void * key) {
    std::lock_guard<std::mutex> lock(mtx_);
    Entry * entry = find(key);
    if (entry == nullptr || entry->slot < 0) {
        return;
    }
    Slot & slot = t0_.slot_mut(entry->slot);
    if (entry->pins > 0) {
        entry->pins--;
    }
    if (slot.pins > 0) {
        slot.pins--;
    }
}

void TierMemory::set_fail(const std::string & why) {
    failed_ = true;
    fail_reason_ = why;
    stats_.fail = 1;
    std::memset(stats_.fail_reason, 0, sizeof(stats_.fail_reason));
    std::strncpy(stats_.fail_reason, why.c_str(), sizeof(stats_.fail_reason) - 1);
}

bool TierMemory::failed() const {
    std::lock_guard<std::mutex> lock(mtx_);
    return failed_;
}

const std::string & TierMemory::fail_reason() const {
    return fail_reason_;
}

Stats TierMemory::stats() const {
    std::lock_guard<std::mutex> lock(mtx_);
    Stats out = stats_;
    out.fail = failed_ ? 1 : stats_.fail;
    return out;
}

size_t TierMemory::t0_free_bytes() const {
    std::lock_guard<std::mutex> lock(mtx_);
    return t0_.free_bytes();
}

size_t TierMemory::t0_used_bytes() const {
    std::lock_guard<std::mutex> lock(mtx_);
    return t0_.used_bytes();
}

long TierMemory::t0_slots() const {
    std::lock_guard<std::mutex> lock(mtx_);
    return t0_.n_slots();
}

void * TierMemory::t0_ptr(void * key) {
    std::lock_guard<std::mutex> lock(mtx_);
    Entry * entry = find(key);
    if (entry == nullptr || entry->slot < 0) {
        return nullptr;
    }
    return t0_.ptr(entry->slot);
}

bool TierMemory::prefetch(int) {
    return false;
}

} // namespace tier
