#include "tir_internal.h"

#include <cstdlib>
#include <cstring>
#include <memory>

namespace {

thread_local std::string g_last_error;

// Output struct_size may be 0 (write header only); a smaller non-zero value is a caller bug.
bool out_size_ok(uint32_t size, size_t expected) {
    return size == 0 || size >= expected;
}

// Copy a versioned output struct, bounded by the caller's struct_size.
template <typename T>
bool write_versioned(T * out, const T & src) {
    if (!out_size_ok(out->struct_size, sizeof(T))) {
        return false;
    }
    const size_t n = out->struct_size < sizeof(T) ? out->struct_size : sizeof(T);
    std::memcpy(out, &src, n);
    out->struct_size = static_cast<uint32_t>(sizeof(T));
    out->version = 1;
    return true;
}

} // namespace

namespace tir_detail {
void set_error(const char * msg) {
    try {
        g_last_error = msg ? msg : "unknown error";
    } catch (...) {
        // error reporting must not throw
    }
}

bool spec_is_ngram() {
    const char * v = std::getenv("TIR_SPEC_TYPE");
    return v != nullptr && std::strcmp(v, "ngram") == 0;
}

bool spec_is_draft() {
    const char * v = std::getenv("TIR_DRAFT_MODEL");
    return v != nullptr && v[0] != '\0';
}

int32_t tir_mtp_n_max() {
    const char * v = std::getenv("TIR_MTP_N_MAX");
    if (v == nullptr || v[0] == '\0') return TIR_MTP_N_MAX;
    char * end = nullptr;
    const long n = std::strtol(v, &end, 10);
    if (end == v || *end != '\0' || n < 1 || n > 3) return TIR_MTP_N_MAX;
    return (int32_t) n;
}
void clear_error() { g_last_error.clear(); }
bool checked_size(uint32_t size, size_t expected) {
    return size >= expected;
}
}

extern "C" {

uint32_t tir_api_version(void) { return 0x00010000u; }

const char * tir_last_error(void) {
    return g_last_error.empty() ? "" : g_last_error.c_str();
}

tir_engine * tir_engine_create(const tir_engine_options * opt) {
    tir_detail::clear_error();
    try {
        if (opt == nullptr) {
            tir_detail::set_error("engine options is null");
            return nullptr;
        }
        if (!tir_detail::checked_size(opt->struct_size, sizeof(tir_engine_options))) {
            tir_detail::set_error("engine options struct_size is too small");
            return nullptr;
        }
        if (opt->version != 1) {
            tir_detail::set_error("unsupported engine_options version");
            return nullptr;
        }
        if (opt->model_path == nullptr || opt->model_path[0] == '\0') {
            tir_detail::set_error("model_path is empty");
            return nullptr;
        }
        if (opt->n_ctx < 512) {
            tir_detail::set_error("n_ctx must be >= 512");
            return nullptr;
        }
        if (opt->n_gpu_layers < -1) {
            tir_detail::set_error("n_gpu_layers must be >= -1");
            return nullptr;
        }
        if (opt->n_threads <= 0) {
            tir_detail::set_error("n_threads must be > 0");
            return nullptr;
        }
        if (opt->kv_q4 != 0 && opt->kv_q4 != 1) {
            tir_detail::set_error("kv_q4 must be 0 or 1");
            return nullptr;
        }
        if (opt->mtp != 0 && opt->mtp != 1) {
            tir_detail::set_error("mtp must be 0 or 1");
            return nullptr;
        }

        auto e = std::make_unique<tir_engine>();
        e->model_path = opt->model_path;
        e->n_ctx = opt->n_ctx;
        e->n_gpu_layers = opt->n_gpu_layers;
        e->n_threads = opt->n_threads;
        e->kv_q4 = opt->kv_q4;
        e->mtp = (opt->mtp != 0 || tir_detail::spec_is_ngram() || tir_detail::spec_is_draft()) ? 1 : 0;
        return e.release();
    } catch (...) {
        tir_detail::set_error("out of memory");
        return nullptr;
    }
}

tir_status tir_engine_load(tir_engine * engine) {
    tir_detail::clear_error();
    try {
        if (engine == nullptr) {
            tir_detail::set_error("engine is null");
            return TIR_E_INVALID;
        }
        if (engine->loaded) {
            return TIR_OK;
        }

        llama_backend_init();

        llama_model_params mp = llama_model_default_params();
        mp.n_gpu_layers = engine->n_gpu_layers;
        // the nextn/MTP head is skipped unless asked for; ngram needs no head
        const bool ngram = tir_detail::spec_is_ngram();
        const bool draft = tir_detail::spec_is_draft();
        mp.load_mtp = engine->mtp != 0 && !ngram && !draft;

        engine->model = llama_model_load_from_file(engine->model_path.c_str(), mp);
        if (engine->model == nullptr) {
            // include the path for diagnosis; fall back to the bare message if the copy allocates
            static const char * fail_msg = "llama_model_load_from_file failed";
            try {
                tir_detail::set_error((std::string(fail_msg) + ": " + engine->model_path).c_str());
            } catch (...) {
                tir_detail::set_error(fail_msg);
            }
            return TIR_E_MODEL;
        }
        if (engine->mtp == 1 && !ngram && !draft && llama_model_n_layer_nextn(engine->model) == 0) {
            engine->mtp = 0; // model has no nextn head, fall back to plain decode
        }
        // no rope scaling is exposed, so a context past the training length is unsupported.
        // a malformed GGUF can report 0; do not reject every request on that
        const int32_t n_ctx_train = llama_model_n_ctx_train(engine->model);
        if (n_ctx_train > 0 && engine->n_ctx > n_ctx_train) {
            tir_detail::set_error((std::string("n_ctx exceeds the model training length: ") +
                                   std::to_string(engine->n_ctx) + " > " + std::to_string(n_ctx_train)).c_str());
            llama_model_free(engine->model);
            engine->model = nullptr;
            return TIR_E_INVALID;
        }
        engine->loaded = true;
        return TIR_OK;
    } catch (...) {
        tir_detail::set_error("out of memory");
        return TIR_E_OOM;
    }
}

tir_status tir_engine_info(tir_engine * engine, tir_model_info * out) {
    tir_detail::clear_error();
    try {
        if (engine == nullptr || out == nullptr) {
            tir_detail::set_error("engine or out is null");
            return TIR_E_INVALID;
        }
        if (!out_size_ok(out->struct_size, sizeof(tir_model_info))) {
            tir_detail::set_error("model_info struct_size is too small");
            return TIR_E_INVALID;
        }
        if (!engine->loaded || engine->model == nullptr) {
            tir_detail::set_error("engine not loaded");
            return TIR_E_INVALID;
        }

        tir_model_info info{};
        info.n_layer = llama_model_n_layer(engine->model);
        info.n_embd = llama_model_n_embd(engine->model);
        info.n_ctx_train = llama_model_n_ctx_train(engine->model);
        info.n_vocab = llama_vocab_n_tokens(llama_model_get_vocab(engine->model));
        info.mtp = llama_model_n_layer_nextn(engine->model) > 0 ? 1 : 0;

        if (!write_versioned(out, info)) {
            tir_detail::set_error("model_info struct_size is too small");
            return TIR_E_INVALID;
        }
        return TIR_OK;
    } catch (...) {
        tir_detail::set_error("out of memory");
        return TIR_E_OOM;
    }
}

void tir_engine_destroy(tir_engine * engine) {
    tir_detail::clear_error();
    if (engine == nullptr) return;
    try {
        if (engine->model != nullptr) {
            llama_model_free(engine->model);
            engine->model = nullptr;
        }
        delete engine;
    } catch (...) {
        tir_detail::set_error("engine_destroy failed");
    }
}

tir_session * tir_session_create(tir_engine * engine) {
    tir_detail::clear_error();
    try {
        if (engine == nullptr) {
            tir_detail::set_error("engine is null");
            return nullptr;
        }
        if (!engine->loaded) {
            tir_detail::set_error("engine is not loaded");
            return nullptr;
        }
        if (engine->model == nullptr) {
            tir_detail::set_error("model is null");
            return nullptr;
        }

        auto s = std::make_unique<tir_session>();
        s->engine = engine;

        llama_context_params cp = llama_context_default_params();
        cp.no_perf = false;
        cp.n_ctx = engine->n_ctx;
        cp.n_batch = 2048;
        cp.n_ubatch = 512;
        cp.n_threads = engine->n_threads;
        cp.n_threads_batch = engine->n_threads;
        cp.type_k = engine->kv_q4 ? GGML_TYPE_Q4_0 : GGML_TYPE_Q8_0;
        cp.type_v = engine->kv_q4 ? GGML_TYPE_Q4_0 : GGML_TYPE_Q8_0;
        cp.flash_attn_type = LLAMA_FLASH_ATTN_TYPE_ENABLED;
        // MTP rejects a draft tail by trimming the hybrid memory: it needs one rollback
        // slot per draft token, otherwise only full checkpoints can undo a partial accept
        cp.n_rs_seq = engine->mtp != 0 ? (uint32_t) tir_detail::tir_mtp_n_max() : 0u;

        s->ctx = llama_init_from_model(engine->model, cp);
        if (s->ctx == nullptr) {
            tir_detail::set_error((std::string("llama_init_from_model failed: n_ctx=") +
                                   std::to_string(cp.n_ctx) + " kv_q4=" + std::to_string(engine->kv_q4) +
                                   " n_rs_seq=" + std::to_string(cp.n_rs_seq)).c_str());
            return nullptr;
        }

        llama_sampler_chain_params sp = llama_sampler_chain_default_params();
        sp.no_perf = false;
        s->smpl = llama_sampler_chain_init(sp);
        if (s->smpl == nullptr) {
            llama_free(s->ctx);
            s->ctx = nullptr;
            tir_detail::set_error("llama_sampler_chain_init failed");
            return nullptr;
        }
        llama_sampler_chain_add(s->smpl, llama_sampler_init_greedy());

        return s.release();
    } catch (...) {
        tir_detail::set_error("out of memory");
        return nullptr;
    }
}

tir_status tir_session_generate(tir_session * session,
                                const tir_request * req,
                                const tir_callbacks * cb,
                                void * user) {
    tir_detail::clear_error();
    try {
        if (session == nullptr || req == nullptr) {
            tir_detail::set_error("session or request is null");
            return TIR_E_INVALID;
        }
        if (!tir_detail::checked_size(req->struct_size, sizeof(tir_request))) {
            tir_detail::set_error("request struct_size is too small");
            return TIR_E_INVALID;
        }
        if (req->version != 1) {
            tir_detail::set_error("unsupported request version");
            return TIR_E_INVALID;
        }
        tir_engine * e = session->engine;
        if (e == nullptr) {
            tir_detail::set_error("session has no engine");
            return TIR_E_INVALID;
        }
        if (!e->loaded || e->model == nullptr) {
            tir_detail::set_error("engine is not loaded");
            return TIR_E_INVALID;
        }
        if (session->ctx == nullptr) {
            tir_detail::set_error("session has no context");
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

        session->cancel.store(false); // a cancelled session must not stay cancelled

        if (e->mtp != 0 && req->n_predict > 1) {
            return tir_generate_mtp(session, req, cb, user);
        }
        return tir_generate_plain(session, req, cb, user);
    } catch (...) {
        tir_detail::set_error("out of memory");
        return TIR_E_OOM;
    }
}

void tir_session_cancel(tir_session * session) {
    tir_detail::clear_error();
    if (session) session->cancel.store(true);
}

void tir_session_destroy(tir_session * session) {
    tir_detail::clear_error();
    if (session == nullptr) return;
    try {
        // the cached MTP state frees its draft context, which points into the target
        // context, so both the context and the sampler outlive the session object
        llama_sampler * smpl = session->smpl;
        llama_context * ctx = session->ctx;
        session->smpl = nullptr;
        session->ctx = nullptr;
        delete session;
        if (smpl != nullptr) {
            llama_sampler_free(smpl);
        }
        if (ctx != nullptr) {
            llama_free(ctx);
        }
    } catch (...) {
        tir_detail::set_error("session_destroy failed");
    }
}

tir_status tir_stats_snapshot(tir_engine * engine, tir_stats * out) {
    tir_detail::clear_error();
    try {
        if (engine == nullptr || out == nullptr) {
            tir_detail::set_error("engine or out is null");
            return TIR_E_INVALID;
        }
        if (!write_versioned(out, engine->last_stats)) {
            tir_detail::set_error("stats struct_size is too small");
            return TIR_E_INVALID;
        }
        return TIR_OK;
    } catch (...) {
        tir_detail::set_error("out of memory");
        return TIR_E_OOM;
    }
}

} // extern "C"
