#include "tir_internal.h"

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

namespace {

int64_t now_us() {
    return std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

// how many prompt tokens one decode step may take. any prefill row count above 2 makes the CUDA
// backend pick other matmul / flash-attention kernels, so the last-token logits move by a few ulp
// and a near-tied greedy id can flip; that happened on short ambiguous prompts for llama and
// qwen3, and at ~130 tokens for qwen35, but not on the >=500-token prompt of test_prefill on any
// allowlisted arch. TIR_PREFILL_BATCH=2 is the exact-parity setting. an unmeasured arch stays at
// one token per decode.
//
// an allowlisted model with an MTP head stays at 2 by default: tir_generate_mtp prefills one
// token per decode so plain and speculative decode start from identical target numerics, and
// raising the plain path to 512 breaks that equality from the second generated token on
// (tir-test-mtp catches it). an unlisted arch still returns 1 above, nextn head or not.
static int32_t prefill_batch_for_arch(const tir_session * s) {
    char arch[64] = {0};
    if (llama_model_meta_val_str(s->engine->model, "general.architecture", arch, sizeof(arch)) < 0) {
        return 1;
    }
    const std::string a(arch);
    if (a != "llama" && a != "qwen3" && a != "qwen35" && a != "nemotron_h") return 1;
    if (llama_model_n_layer_nextn(s->engine->model) > 0) return 2;
    return 512;
}

// prompt prefill chunk size. the arch allowlist above is the default; TIR_PREFILL_BATCH is an
// env escape hatch, 1 restores the per-token prefill of the P0 baseline and 2 keeps exact parity.
// empty, unparsable or out-of-range [1, 512] values fall back to the allowlist, not to a guess.
// 512 matches cparams.n_ubatch, the widest chunk the context will run in one decode anyway.
static int32_t prefill_batch_size(const tir_session * s) {
    const int32_t arch_batch = prefill_batch_for_arch(s);

    const char * v = getenv("TIR_PREFILL_BATCH");
    if (v == nullptr || v[0] == '\0') return arch_batch;

    char * end = nullptr;
    const long parsed = strtol(v, &end, 10);
    if (end == v || *end != '\0') return arch_batch;
    if (parsed < 1 || parsed > 512) return arch_batch;
    return (int32_t) parsed;
}

// Frees the batch on every exit path, including exceptions.
struct batch_guard {
    llama_batch b;
    batch_guard(int32_t n_tokens, int32_t n_seq_max) : b(llama_batch_init(n_tokens, 0, n_seq_max)) {}
    ~batch_guard() { llama_batch_free(b); }
    batch_guard(const batch_guard &) = delete;
    batch_guard & operator=(const batch_guard &) = delete;
};

// prefill feeds prefill_batch_size() prompt tokens per decode step; the sampling loop below
// still decodes one token per step, as KV q4 keeps the batch small.
bool decode_one(llama_context * ctx, llama_token id, llama_pos pos, bool logits, llama_batch & batch) {
    batch.n_tokens = 1;
    batch.token[0] = id;
    batch.pos[0] = pos;
    batch.n_seq_id[0] = 1;
    batch.seq_id[0][0] = 0;
    batch.logits[0] = logits ? 1 : 0;
    return llama_decode(ctx, batch) == 0;
}

} // namespace

extern "C" tir_status tir_generate_plain(tir_session * s,
                                         const tir_request * req,
                                         const tir_callbacks * cb,
                                         void * user) {
    if (s == nullptr || s->ctx == nullptr || req == nullptr) {
        tir_detail::set_error("invalid session or request");
        return TIR_E_INVALID;
    }
    if (req->prompt == nullptr) {
        tir_detail::set_error("prompt is null");
        return TIR_E_INVALID;
    }
    if (req->n_predict <= 0) {
        tir_detail::set_error("n_predict must be > 0");
        return TIR_E_INVALID;
    }

    tir_engine * e = s->engine;
    if (e == nullptr || !e->loaded || e->model == nullptr) {
        tir_detail::set_error("engine is not loaded");
        return TIR_E_INVALID;
    }

    try {
        e->last_stats = {};
        llama_perf_context_reset(s->ctx);
        if (s->smpl != nullptr) {
            llama_perf_sampler_reset(s->smpl);
        }

        const llama_vocab * vocab = llama_model_get_vocab(e->model);
        const std::string prompt(req->prompt);

        // first pass only measures, it returns the negative token count
        const int32_t n_prompt = -llama_tokenize(vocab, prompt.c_str(), (int32_t) prompt.size(),
                                                 nullptr, 0, true, true);
        if (n_prompt <= 0) {
            tir_detail::set_error("tokenize failed");
            return TIR_E_MODEL;
        }
        std::vector<llama_token> tokens((size_t) n_prompt);
        if (llama_tokenize(vocab, prompt.c_str(), (int32_t) prompt.size(), tokens.data(),
                           n_prompt, true, true) < 0) {
            tir_detail::set_error("tokenize failed");
            return TIR_E_MODEL;
        }

        // check before prefill: an oversized request must not touch the memory
        const int32_t n_ctx = (int32_t) llama_n_ctx(s->ctx);
        if ((int64_t) n_prompt + (int64_t) req->n_predict > (int64_t) n_ctx) {
            tir_detail::set_error("prompt + n_predict exceeds context");
            return TIR_E_INVALID;
        }

        const int32_t pb = prefill_batch_size(s);
        batch_guard guard(pb, 1);
        llama_batch & batch = guard.b;

        // every generate starts a new sequence: drop what a previous call left behind
        llama_memory_clear(llama_get_memory(s->ctx), true);

        const int64_t t_start = now_us();
        s->n_past = 0;
        for (int32_t i = 0; i < n_prompt; i += pb) {
            if (s->cancel.load()) return TIR_E_CANCELLED;
            const int32_t n = (n_prompt - i < pb) ? n_prompt - i : pb;
            batch.n_tokens = n;
            for (int32_t j = 0; j < n; ++j) {
                const int32_t pos = i + j;
                batch.token[j] = tokens[(size_t) pos];
                batch.pos[j] = pos;
                batch.n_seq_id[j] = 1;
                batch.seq_id[j][0] = 0;
                // only the last prompt token needs logits for the first sample
                batch.logits[j] = (pos == n_prompt - 1) ? 1 : 0;
            }
            if (llama_decode(s->ctx, batch) != 0) {
                tir_detail::set_error("prefill decode failed");
                return TIR_E_INTERNAL;
            }
            s->n_past = i + n;
        }

        // prefill is wall-clocked by ttft; sync first because an unsynchronized eval
        // books its time on the next call (llama-context.cpp FIXME), then reset so the
        // perf counters and step_us cover the decode loop only
        llama_synchronize(s->ctx);
        llama_perf_context_reset(s->ctx);

        uint64_t gen = 0;
        uint64_t step_us = 0;
        uint64_t detok_us = 0;
        uint64_t callback_us = 0;
        int64_t t_first = t_start;
        bool sampled = false;
        const bool margin_debug = std::getenv("TIR_MARGIN_DEBUG") != nullptr;
        double margin_min = 1e30;
        for (int32_t i = 0; i < req->n_predict; ++i) {
            if (s->cancel.load()) return TIR_E_CANCELLED;

            const int64_t t_step = now_us();
            if (margin_debug) {
                const float * logits = llama_get_logits_ith(s->ctx, -1);
                const int32_t n_vocab = llama_vocab_n_tokens(vocab);
                int32_t i1 = -1, i2 = -1;
                float v1 = -1e30f, v2 = -1e30f;
                for (int32_t v = 0; v < n_vocab; ++v) {
                    const float x = logits[v];
                    if (x > v1) { v2 = v1; i2 = i1; v1 = x; i1 = v; }
                    else if (x > v2) { v2 = x; i2 = v; }
                }
                const double m = (double) v1 - (double) v2;
                if (m < margin_min) margin_min = m;
                std::fprintf(stderr, "tir-margin: idx=%d id=%d m=%.4f flip=%d\n", i, i1, m, m < 0.13 ? 1 : 0);
            }
            const llama_token cur = llama_sampler_sample(s->smpl, s->ctx, -1);
            if (!sampled) {
                t_first = now_us();
                sampled = true;
            }
            if (llama_vocab_is_eog(vocab, cur)) {
                step_us += (uint64_t) (now_us() - t_step);
                break;
            }

            const int64_t t_detok = now_us();
            // probe the size first, the negative return is the required length
            int32_t n_piece = llama_token_to_piece(vocab, cur, nullptr, 0, 0, false);
            if (n_piece > 0) {
                tir_detail::set_error("token_to_piece probe failed");
                return TIR_E_INTERNAL;
            }
            n_piece = -n_piece;
            // +1 keeps data() non-null when the piece is empty
            std::vector<char> piece((size_t) n_piece + 1);
            if (n_piece > 0 && llama_token_to_piece(vocab, cur, piece.data(), n_piece, 0, false) < 0) {
                tir_detail::set_error("token_to_piece failed");
                return TIR_E_INTERNAL;
            }
            detok_us += (uint64_t) (now_us() - t_detok);

            // piece is alive until the callback returns
            tir_token tok{};
            tok.id = cur;
            tok.piece = piece.data();
            tok.piece_len = (uint32_t) n_piece;
            tok.index = (uint32_t) gen;
            const int64_t t_cb = now_us();
            if (cb != nullptr && cb->on_token != nullptr && cb->on_token(user, &tok) != 0) {
                tir_detail::set_error("cancelled by callback");
                return TIR_E_CANCELLED;
            }
            callback_us += (uint64_t) (now_us() - t_cb);
            gen++;

            // the last requested token needs no logits
            if (!decode_one(s->ctx, cur, s->n_past++, i + 1 < req->n_predict, batch)) {
                tir_detail::set_error("decode failed");
                return TIR_E_INTERNAL;
            }
            step_us += (uint64_t) (now_us() - t_step);
        }

        const int64_t t_end = now_us();
        if (margin_debug && margin_min < 1e29) {
            std::fprintf(stderr, "tir-margin: min=%.4f (0.13 ref: %.2fx)\n",
                         margin_min, margin_min / 0.13);
        }
        const llama_perf_context_data perf = llama_perf_context(s->ctx);
        const llama_perf_sampler_data perf_smpl = llama_perf_sampler(s->smpl);
        const double decode_s = (double) (t_end - t_first) / 1e6;
        e->last_stats.prompt_tokens = (uint64_t) n_prompt;
        e->last_stats.gen_tokens = gen;
        e->last_stats.ttft_ms = (double) (t_first - t_start) / 1000.0;
        e->last_stats.decode_ms = (double) (t_end - t_first) / 1000.0;
        e->last_stats.tok_s = (gen > 0 && decode_s > 0.0) ? (double) gen / decode_s : 0.0;
        e->last_stats.eval_ms = perf.t_eval_ms;
        e->last_stats.prompt_eval_ms = perf.t_p_eval_ms;
        e->last_stats.sampler_ms = perf_smpl.t_sample_ms;
        e->last_stats.step_us = step_us;
        e->last_stats.detok_us = detok_us;
        e->last_stats.callback_us = callback_us;
        e->last_stats.graph_reused = perf.n_reused;
        e->last_stats.graph_reallocs_same = perf.n_reallocs_same;
        e->last_stats.graph_reallocs_diff = perf.n_reallocs_diff;
        return TIR_OK;
    } catch (...) {
        tir_detail::set_error("out of memory");
        return TIR_E_OOM;
    }
}
