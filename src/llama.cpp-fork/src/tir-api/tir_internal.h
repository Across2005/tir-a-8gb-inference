#pragma once

#include "tir.h"

#include "llama.h"

#include <atomic>
#include <memory>
#include <string>
#include <vector>

// draft tokens per MTP step. the target context needs that many rollback slots
// (cparams.n_rs_seq) so a rejected draft can be trimmed from the hybrid memory.
//
// default 1: on this hybrid (gated delta net) model a target verify batch of 3 or more
// rows takes a chunked kernel that shifts the logits by ~0.13 against sequential decode,
// which flips near-ties and breaks plain/MTP token parity. batches of 1-2 rows are
// bit-identical to sequential decode (measured on qwen3.8-9b, 2026-11-09).
// TIR_MTP_N_MAX env can override to 2/3 for experiments; default stays 1.
constexpr int32_t TIR_MTP_N_MAX = 1;

struct tir_engine {
    std::string model_path;
    int32_t n_ctx = 16384;
    int32_t n_gpu_layers = 99;
    int32_t n_threads = 8;
    int32_t kv_q4 = 1;
    int32_t mtp = 0;

    llama_model * model = nullptr;
    bool loaded = false;

    bool last_gen_ok = false;
    tir_stats last_stats{};
};

// cached MTP driver and draft context, defined in tir_mtp.cpp so that this header
// does not pull in the common/ types
struct tir_mtp_state;

struct tir_session {
    tir_engine * engine = nullptr;
    llama_context * ctx = nullptr;
    llama_sampler * smpl = nullptr;
    int32_t n_past = 0;
    std::atomic<bool> cancel{false};
    // created by the first MTP request and reused by every later request
    std::unique_ptr<tir_mtp_state> mtp;

    // both are defined in tir_mtp.cpp, where tir_mtp_state is complete
    tir_session();
    ~tir_session();
};

namespace tir_detail {
void set_error(const char * msg);
void clear_error();
bool checked_size(uint32_t size, size_t expected);
bool spec_is_ngram();
bool spec_is_draft();
int32_t tir_mtp_n_max();
}

#ifdef __cplusplus
extern "C" {
#endif

tir_status tir_generate_plain(tir_session * session, const tir_request * req,
                              const tir_callbacks * cb, void * user);
tir_status tir_generate_mtp(tir_session * session, const tir_request * req,
                            const tir_callbacks * cb, void * user);

#ifdef __cplusplus
}
#endif
