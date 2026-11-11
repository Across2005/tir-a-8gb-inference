#include "tir_internal.h"

#include "common.h"
#include "sampling.h"
#include "speculative.h"

#include <algorithm>
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

// Token pieces can be longer than any fixed buffer, so size them from the probe call.
bool token_piece(const llama_vocab * vocab, llama_token id, std::vector<char> & buf, uint32_t & len) {
    int32_t n = llama_token_to_piece(vocab, id, nullptr, 0, 0, false);
    if (n > 0) {
        return false;
    }
    n = -n;
    // +1 keeps data() non-null when the piece is empty
    buf.assign((size_t) n + 1, '\0');
    if (n > 0 && llama_token_to_piece(vocab, id, buf.data(), n, 0, false) < 0) {
        return false;
    }
    len = (uint32_t) n;
    return true;
}

} // namespace

struct tir_mtp_state {
    common_params cp;
    common_speculative_init_result_ptr init;
    common_speculative * spec = nullptr;

    ~tir_mtp_state() {
        // free the driver first: it points into the draft context that init owns
        if (spec != nullptr) {
            common_speculative_free(spec);
            spec = nullptr;
        }
    }
};

tir_session::tir_session() = default;
tir_session::~tir_session() = default;

namespace {

// the MTP driver reuses the target model and only needs the draft context params
common_params mtp_params(tir_session * s) {
    tir_engine * e = s->engine;

    common_params cp;
    cp.model.path = e->model_path;
    cp.n_ctx = e->n_ctx;
    cp.n_batch = 2048;
    cp.n_ubatch = 512;
    cp.n_parallel = 1;
    cp.n_gpu_layers = e->n_gpu_layers;
    cp.cpuparams.n_threads = e->n_threads;
    cp.cpuparams_batch.n_threads = e->n_threads;
    cp.flash_attn_type = LLAMA_FLASH_ATTN_TYPE_ENABLED;
    cp.cache_type_k = e->kv_q4 ? GGML_TYPE_Q4_0 : GGML_TYPE_Q8_0;
    cp.cache_type_v = e->kv_q4 ? GGML_TYPE_Q4_0 : GGML_TYPE_Q8_0;

    cp.sampling.temp = 0.0f;
    cp.sampling.top_k = 1;
    cp.sampling.top_p = 1.0f;
    // an empty sampler list ends in dist(); name top-k 1 so the chain ends in greedy
    cp.sampling.samplers = { COMMON_SAMPLER_TYPE_TOP_K };

    const bool ngram = tir_detail::spec_is_ngram();
    const char * draft = std::getenv("TIR_DRAFT_MODEL");
    const int32_t n_max = tir_detail::tir_mtp_n_max();
    if (draft != nullptr && draft[0] != '\0') {
        cp.speculative.types = { COMMON_SPECULATIVE_TYPE_DRAFT_SIMPLE };
        cp.speculative.draft.mparams.path = draft;
        cp.speculative.draft.n_max = n_max;
    } else {
        cp.speculative.types = { ngram ? COMMON_SPECULATIVE_TYPE_NGRAM_SIMPLE
                                       : COMMON_SPECULATIVE_TYPE_DRAFT_MTP };
        cp.speculative.draft.n_max = n_max;
        if (ngram) {
            // ngram-simple requires draft length >= n-gram length; qwen35 allows one draft row
            cp.speculative.ngram_simple.size_n = 1;
            cp.speculative.ngram_simple.size_m = 1;
            cp.speculative.ngram_simple.min_hits = 1;
        }
    }
    cp.speculative.draft.cache_type_k = cp.cache_type_k;
    cp.speculative.draft.cache_type_v = cp.cache_type_v;
    cp.speculative.draft.ctx_tgt = s->ctx;

    // the draft context holds n_max + 1 logits rows per sequence
    const common_speculative_output_limits limits =
        common_speculative_get_output_limits(cp.n_batch, cp.n_parallel, n_max);
    cp.n_outputs_max = limits.total;
    cp.n_outputs_max_per_seq = limits.per_seq;

    return cp;
}

// Builds the MTP state on the first request of a session; later requests reuse it.
common_speculative * ensure_mtp_state(tir_session * s, tir_status & err) {
    if (s->mtp != nullptr) {
        return s->mtp->spec;
    }

    auto st = std::make_unique<tir_mtp_state>();
    st->cp = mtp_params(s);

    // creates the MTP draft context on the target model
    st->init = common_speculative_init_from_params(st->cp, s->engine->model, s->ctx);
    if (!st->init) {
        tir_detail::set_error("failed to create the speculative context");
        err = TIR_E_MODEL;
        return nullptr;
    }
    llama_context * ctx_dft = st->init->context();
    if (ctx_dft != nullptr) {
        st->cp.speculative.draft.ctx_dft = ctx_dft;
    } else if (!tir_detail::spec_is_ngram() && !tir_detail::spec_is_draft()) {
        tir_detail::set_error("failed to create the MTP draft context");
        err = TIR_E_MODEL;
        return nullptr;
    }

    st->spec = common_speculative_init(st->cp.speculative, 1);
    if (st->spec == nullptr) {
        tir_detail::set_error("common_speculative_init failed");
        err = TIR_E_INTERNAL;
        return nullptr;
    }

    s->mtp = std::move(st);
    return s->mtp->spec;
}

} // namespace

extern "C" tir_status tir_generate_mtp(tir_session * s,
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
    const bool ngram = tir_detail::spec_is_ngram();
    const bool draft = tir_detail::spec_is_draft();
    if (!ngram && !draft && llama_model_n_layer_nextn(e->model) <= 0) {
        tir_detail::set_error("model has no MTP (nextn) head");
        return TIR_E_MODEL;
    }

    try {
        e->last_stats = {};
        llama_perf_context_reset(s->ctx);

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

        const int32_t n_ctx = (int32_t) llama_n_ctx(s->ctx);
        if ((int64_t) n_prompt + (int64_t) req->n_predict > (int64_t) n_ctx) {
            tir_detail::set_error("prompt + n_predict exceeds context");
            return TIR_E_INVALID;
        }
        if (n_prompt < 2) {
            // a single-token prompt leaves nothing for the prompt batch
            return tir_generate_plain(s, req, cb, user);
        }

        // the MTP driver reuses the target model and only needs the draft context params
        tir_status state_err = TIR_E_INTERNAL;
        common_speculative * spec = ensure_mtp_state(s, state_err);
        if (spec == nullptr) {
            return state_err;
        }
        llama_context * ctx_dft = s->mtp->init->context();

        // can_seq_rm may evaluate probe tokens, so it runs before the prompt
        const common_context_seq_rm_type tgt_rm = common_context_can_seq_rm(s->ctx);
        if (tgt_rm == COMMON_CONTEXT_SEQ_RM_TYPE_NO) {
            tir_detail::set_error("context cannot remove sequences");
            return TIR_E_INTERNAL;
        }
        const int32_t n_max = tir_detail::tir_mtp_n_max();
        // a hybrid memory trims the rejected tail through n_rs_seq slots; if the context
        // has fewer slots than a full draft, fall back to checkpoints like the example does
        const bool use_ckpt_tgt =
            tgt_rm == COMMON_CONTEXT_SEQ_RM_TYPE_FULL ||
            (tgt_rm == COMMON_CONTEXT_SEQ_RM_TYPE_RS && llama_n_rs_seq(s->ctx) < (uint32_t) n_max);
        const bool use_ckpt_dft = ctx_dft != nullptr &&
            common_context_can_seq_rm(ctx_dft) == COMMON_CONTEXT_SEQ_RM_TYPE_FULL;

        // every generate starts a new sequence: drop what a previous call left behind
        llama_memory_clear(llama_get_memory(s->ctx), true);
        if (ctx_dft != nullptr) {
            llama_memory_clear(llama_get_memory(ctx_dft), true);
            llama_perf_context_reset(ctx_dft);
        }
        s->n_past = 0;

        common_sampler_ptr smpl(common_sampler_init(e->model, s->mtp->cp.sampling));
        if (!smpl) {
            tir_detail::set_error("common_sampler_init failed");
            return TIR_E_INTERNAL;
        }
        llama_perf_sampler_reset(common_sampler_get(smpl.get()));

        const int64_t t_start = now_us();
        int64_t t_first = 0;
        uint64_t step_us = 0, detok_us = 0, callback_us = 0;
        struct StepTimer {
            uint64_t * acc;
            int64_t t0;
            explicit StepTimer(uint64_t * a) : acc(a), t0(now_us()) {}
            ~StepTimer() { *acc += (uint64_t) (now_us() - t0); }
        };

        // prefill everything but the last token, keep it as the first batch entry.
        // one token per decode keeps the target numerics identical to the plain path:
        // a multi-token ubatch takes a chunked delta-net kernel that shifts the logits
        {
            for (size_t i = 0; i + 1 < tokens.size(); ++i) {
                common_batch batch_prompt(s->ctx);
                batch_prompt.add(tokens[i], (llama_pos) i, 0, false);
                if (s->cancel.load()) {
                    tir_detail::set_error("cancelled");
                    return TIR_E_CANCELLED;
                }
                if (llama_process(s->ctx, LLAMA_PROCESS_TYPE_DECODE, batch_prompt.get()) != 0) {
                    tir_detail::set_error("prompt decode failed");
                    return TIR_E_INTERNAL;
                }
                if (!common_speculative_process(spec, batch_prompt)) {
                    tir_detail::set_error("speculative prompt process failed");
                    return TIR_E_INTERNAL;
                }
            }
        }
        if (s->cancel.load()) {
            tir_detail::set_error("cancelled");
            return TIR_E_CANCELLED;
        }

        // prompt prefill is wall-clocked by ttft; sync first because an unsynchronized
        // eval books its time on the next call, then reset so the perf counters and
        // step_us cover the speculative loop only
        llama_synchronize(s->ctx);
        llama_perf_context_reset(s->ctx);

        llama_token id_last = tokens.back();

        // all tokens currently in the target context
        llama_tokens prompt_tgt(tokens.begin(), tokens.end() - 1);
        prompt_tgt.reserve((size_t) n_ctx);

        int n_past = (int) tokens.size() - 1;

        common_speculative_begin(spec, 0, prompt_tgt);

        common_batch batch_tgt(s->ctx);
        llama_tokens draft;
        common_prompt_checkpoint ckpt;

        std::vector<char> piece;
        uint32_t piece_len = 0;

        uint64_t gen = 0;
        uint64_t drafted = 0;
        uint64_t accepted = 0;
        uint64_t steps = 0;

        while ((int) gen < req->n_predict) {
            StepTimer step_timer(&step_us);
            if (s->cancel.load()) {
                tir_detail::set_error("cancelled");
                return TIR_E_CANCELLED;
            }

            if (draft.empty()) {
                ckpt.update_pos(
                        (int64_t) prompt_tgt.size(),
                        llama_memory_seq_pos_min(llama_get_memory(s->ctx), 0),
                        llama_memory_seq_pos_max(llama_get_memory(s->ctx), 0));

                if (use_ckpt_dft) {
                    ckpt.update_dft(ctx_dft, 0, LLAMA_STATE_SEQ_FLAGS_PARTIAL_ONLY);
                }

                // the draft must fit the remaining context and the remaining budget
                int n_draft_max = n_ctx - n_past - 2;
                n_draft_max = std::min(n_draft_max, req->n_predict - (int) gen - 1);
                n_draft_max = std::min(n_draft_max, (int) n_max);
                n_draft_max = std::max(n_draft_max, 0);

                auto & dp = common_speculative_get_draft_params(spec, 0);
                dp.drafting = true;
                dp.n_max = n_draft_max;
                dp.pos0 = n_past;
                dp.id_last = id_last;
                dp.prompt = &prompt_tgt;
                dp.result = &draft;
                dp.result_q = nullptr;
                dp.temp = 0.0f;
                dp.seed = req->seed;
                common_speculative_draft(spec);

                // snapshot the target before the verify batch so a rejected tail can be undone
                if (!draft.empty() && use_ckpt_tgt) {
                    ckpt.update_tgt(s->ctx, 0, LLAMA_STATE_SEQ_FLAGS_PARTIAL_ONLY);
                }

                // the draft context must not hold rows past the verified prefix
                if (use_ckpt_dft && !ckpt.load_dft(ctx_dft, 0, LLAMA_STATE_SEQ_FLAGS_PARTIAL_ONLY)) {
                    tir_detail::set_error("failed to restore the draft checkpoint");
                    return TIR_E_INTERNAL;
                }
                if (ctx_dft != nullptr && !llama_memory_seq_rm(llama_get_memory(ctx_dft), 0, ckpt.pos_max + 1, -1)) {
                    tir_detail::set_error("failed to trim the draft memory");
                    return TIR_E_INTERNAL;
                }
            } else {
                // reuse the partial draft restored by the checkpoint path
                if (use_ckpt_tgt && ckpt.empty()) {
                    tir_detail::set_error("partial draft without a checkpoint");
                    return TIR_E_INTERNAL;
                }
            }

            // always have a token to evaluate from before: id_last
            batch_tgt.clear();
            batch_tgt.add(id_last, n_past++, 0, true);
            for (size_t i = 0; i < draft.size(); ++i) {
                batch_tgt.add(draft[i], n_past + (llama_pos) i, 0, true);
            }

            // verify id_last and the drafts in one target pass
            if (llama_process(s->ctx, LLAMA_PROCESS_TYPE_DECODE, batch_tgt.get()) != 0) {
                tir_detail::set_error("verify decode failed");
                return TIR_E_INTERNAL;
            }
            if (!common_speculative_process(spec, batch_tgt)) {
                tir_detail::set_error("speculative verify process failed");
                return TIR_E_INTERNAL;
            }

            common_sampler_ptr smpl_save;
            if (use_ckpt_tgt) {
                smpl_save.reset(common_sampler_clone(smpl.get()));
            }

            const size_t n_draft = draft.size();
            std::vector<llama_token> ids = common_sampler_sample_and_accept_n(smpl.get(), s->ctx, draft);
            if (ids.empty()) {
                tir_detail::set_error("no sampled token");
                return TIR_E_INTERNAL;
            }

            // partial acceptance without bounded rollback: restore and replay the accepted prefix
            if (use_ckpt_tgt && ids.size() - 1 < n_draft) {
                draft = ids;
                // the rejected draft still counts as an attempt, or acceptance looks better than it is
                drafted += n_draft;
                accepted += ids.size() - 1;

                if (!ckpt.load_tgt(s->ctx, 0, LLAMA_STATE_SEQ_FLAGS_PARTIAL_ONLY)) {
                    tir_detail::set_error("failed to restore the target checkpoint");
                    return TIR_E_INTERNAL;
                }
                if (!llama_memory_seq_rm(llama_get_memory(s->ctx), 0, ckpt.pos_max + 1, -1)) {
                    tir_detail::set_error("failed to trim the target memory");
                    return TIR_E_INTERNAL;
                }
                if (ctx_dft) {
                    if (!ckpt.load_dft(ctx_dft, 0, LLAMA_STATE_SEQ_FLAGS_PARTIAL_ONLY)) {
                        tir_detail::set_error("failed to restore the draft checkpoint");
                        return TIR_E_INTERNAL;
                    }
                    if (!llama_memory_seq_rm(llama_get_memory(ctx_dft), 0, ckpt.pos_max + 1, -1)) {
                        tir_detail::set_error("failed to trim the draft memory");
                        return TIR_E_INTERNAL;
                    }
                }

                prompt_tgt.resize((size_t) ckpt.n_tokens);
                smpl = std::move(smpl_save);
                n_past = (int) prompt_tgt.size();
                continue;
            }

            common_speculative_accept(spec, 0, (uint16_t) (ids.size() - 1));
            n_past += (int) ids.size() - 1;
            drafted += n_draft;
            accepted += ids.size() - 1;

            bool has_eos = false;
            int emitted = 0;
            for (size_t i = 0; i < ids.size() && (int) gen < req->n_predict; ++i) {
                prompt_tgt.push_back(id_last);
                id_last = ids[i];

                if (llama_vocab_is_eog(vocab, id_last)) {
                    has_eos = true;
                    break;
                }

                const int64_t t_detok = now_us();
                if (!token_piece(vocab, id_last, piece, piece_len)) {
                    tir_detail::set_error("token_to_piece failed");
                    return TIR_E_INTERNAL;
                }
                detok_us += (uint64_t) (now_us() - t_detok);

                tir_token tok{};
                tok.id = id_last;
                tok.piece = piece.data();
                tok.piece_len = piece_len;
                tok.index = (uint32_t) gen;
                if (t_first == 0) {
                    t_first = now_us();
                }
                const int64_t t_cb = now_us();
                if (cb != nullptr && cb->on_token != nullptr && cb->on_token(user, &tok) != 0) {
                    tir_detail::set_error("cancelled by callback");
                    return TIR_E_CANCELLED;
                }
                callback_us += (uint64_t) (now_us() - t_cb);
                gen++;
                emitted++;
            }
            if (emitted > 0) {
                steps++;
            }

            draft.clear();

            // drop every row the target wrote past the accepted tokens (RS rollback path)
            if (!llama_memory_seq_rm(llama_get_memory(s->ctx), 0, n_past, -1)) {
                tir_detail::set_error("failed to trim the target memory");
                return TIR_E_INTERNAL;
            }
            if (ctx_dft != nullptr && !llama_memory_seq_rm(llama_get_memory(ctx_dft), 0, n_past, -1)) {
                tir_detail::set_error("failed to trim the draft memory");
                return TIR_E_INTERNAL;
            }

            if (has_eos) {
                break;
            }
        }

        const int64_t t_end = now_us();
        const double decode_s = t_first > 0 ? (double) (t_end - t_first) / 1e6 : 0.0;

        e->last_stats.prompt_tokens = (uint64_t) n_prompt;
        e->last_stats.gen_tokens = gen;
        e->last_stats.ttft_ms = t_first > 0 ? (double) (t_first - t_start) / 1000.0 : 0.0;
        e->last_stats.decode_ms = t_first > 0 ? (double) (t_end - t_first) / 1000.0 : 0.0;
        e->last_stats.tok_s = (gen > 0 && decode_s > 0.0) ? (double) gen / decode_s : 0.0;
        e->last_stats.acceptance = drafted > 0 ? (double) accepted / (double) drafted : 0.0;
        // steps counts the rounds that produced at least one token
        e->last_stats.mean_len = steps > 0 ? (double) gen / (double) steps : 1.0;

        const llama_perf_context_data perf = llama_perf_context(s->ctx);
        const llama_perf_sampler_data perf_smpl = llama_perf_sampler(common_sampler_get(smpl.get()));
        e->last_stats.eval_ms = perf.t_eval_ms;
        e->last_stats.prompt_eval_ms = perf.t_p_eval_ms;
        e->last_stats.sampler_ms = perf_smpl.t_sample_ms;
        e->last_stats.step_us = step_us;
        e->last_stats.detok_us = detok_us;
        e->last_stats.callback_us = callback_us;
        e->last_stats.graph_reused = perf.n_reused;
        e->last_stats.graph_reallocs_same = perf.n_reallocs_same;
        e->last_stats.graph_reallocs_diff = perf.n_reallocs_diff;

        if (std::getenv("TIR_SPEC_DEBUG") != nullptr) {
            std::fprintf(stderr, "tir-spec: drafted=%llu accepted=%llu steps=%llu gen=%llu n_max=%d\n",
                         (unsigned long long) drafted, (unsigned long long) accepted,
                         (unsigned long long) steps, (unsigned long long) gen,
                         common_speculative_n_max(spec));
            if (ctx_dft != nullptr) {
                const llama_perf_context_data pd = llama_perf_context(ctx_dft);
                std::fprintf(stderr, "tir-spec: draft eval_ms=%.3f p_eval_ms=%.3f n_eval=%d\n",
                             pd.t_eval_ms, pd.t_p_eval_ms, pd.n_eval);
            }
        }

        s->n_past = n_past;
        return TIR_OK;
    } catch (...) {
        tir_detail::set_error("out of memory");
        return TIR_E_OOM;
    }
}
