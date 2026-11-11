// TIR-B B0 spike driver: callback count, zero-copy, H2D staging, bandwidth bench.
// Usage (env): TIR_SPIKE=callback-count|zero-copy|h2d, TIR_SPIKE_TENSOR=<name>, TIR_SPIKE_MB=<cap>
// Output: one JSON line on stderr (plus a text token stream on stdout).

#if defined(_WIN32)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#endif

#include "llama.h"
#include "ggml-cuda.h"

#include <cuda_runtime.h>

#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <utility>
#include <vector>

// spike-only accessor, declared in src/llama-model.h; declared here to keep the example standalone
const std::vector<std::pair<std::string, ggml_tensor *>> & llama_internal_get_tensor_map(const struct llama_model * model);

namespace {

enum spike_mode {
    SPIKE_OFF = 0,
    SPIKE_CALLBACK_COUNT,
    SPIKE_ZERO_COPY,
    SPIKE_H2D,
};

spike_mode g_mode = SPIKE_OFF;

ggml_tensor * g_target = nullptr;
void *        g_host   = nullptr;
void *        g_slot   = nullptr;
size_t        g_bytes  = 0;
int           g_pointer_type = -1;
std::string   g_target_name;

std::atomic<unsigned long long> g_cb_false{0};
std::atomic<unsigned long long> g_cb_true{0};
std::atomic<unsigned long long> g_hits{0};
std::atomic<unsigned long long> g_copy_us{0};
std::atomic<unsigned long long> g_copy_count{0};

static int64_t now_us() {
    return std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

static void spike_cb(ggml_tensor * t, bool done) {
    if (done) {
        g_cb_true.fetch_add(1, std::memory_order_relaxed);
        return;
    }
    g_cb_false.fetch_add(1, std::memory_order_relaxed);

    if (g_mode != SPIKE_ZERO_COPY && g_mode != SPIKE_H2D) {
        return;
    }
    if (g_target == nullptr) {
        return;
    }

    bool uses = false;
    for (int j = 0; j < GGML_MAX_SRC; ++j) {
        if (t->src[j] == g_target) {
            uses = true;
            break;
        }
    }
    if (!uses) {
        return;
    }
    g_hits.fetch_add(1, std::memory_order_relaxed);

    if (g_mode == SPIKE_H2D) {
        const int64_t t0 = now_us();
        const cudaError_t err = cudaMemcpy(g_slot, g_host, g_bytes, cudaMemcpyHostToDevice);
        const int64_t t1 = now_us();
        if (err != cudaSuccess) {
            fprintf(stderr, "tierspike: cudaMemcpy failed: %s\n", cudaGetErrorString(err));
            return;
        }
        g_copy_us.fetch_add((unsigned long long) (t1 - t0), std::memory_order_relaxed);
        g_copy_count.fetch_add(1, std::memory_order_relaxed);
        g_target->data = g_slot;
    }
}

static bool setup_spike(llama_model * model, size_t cap_mib, std::string & err) {
    const auto & map = llama_internal_get_tensor_map(model);
    for (const auto & kv : map) {
        if (kv.first == g_target_name) {
            g_target = kv.second;
            break;
        }
    }
    if (g_target == nullptr) {
        err = "tensor not found: " + g_target_name;
        return false;
    }
    g_bytes = ggml_nbytes(g_target);

    fprintf(stderr, "tierspike: target=%s nbytes=%zu (%.2f MiB), cap=%zu MiB\n",
            g_target_name.c_str(), g_bytes, g_bytes / 1048576.0, cap_mib);

    if (g_mode == SPIKE_ZERO_COPY) {
        cudaError_t e = cudaHostAlloc(&g_host, g_bytes, cudaHostAllocMapped | cudaHostAllocPortable);
        if (e != cudaSuccess) {
            err = std::string("cudaHostAlloc(mapped) failed: ") + cudaGetErrorString(e);
            return false;
        }
        e = cudaMemcpy(g_host, g_target->data, g_bytes, cudaMemcpyDeviceToHost);
        if (e != cudaSuccess) {
            err = std::string("D2H copy failed: ") + cudaGetErrorString(e);
            return false;
        }
        void * dev = nullptr;
        e = cudaHostGetDevicePointer(&dev, g_host, 0);
        if (e != cudaSuccess) {
            err = std::string("cudaHostGetDevicePointer failed: ") + cudaGetErrorString(e);
            return false;
        }
        cudaPointerAttributes attr;
        memset(&attr, 0, sizeof(attr));
        e = cudaPointerGetAttributes(&attr, dev);
        if (e != cudaSuccess) {
            err = std::string("cudaPointerGetAttributes failed: ") + cudaGetErrorString(e);
            return false;
        }
        g_pointer_type = (int) attr.type;
        g_target->data = dev;
    } else if (g_mode == SPIKE_H2D) {
        cudaError_t e = cudaHostAlloc(&g_host, g_bytes, cudaHostAllocDefault);
        if (e != cudaSuccess) {
            err = std::string("cudaHostAlloc failed: ") + cudaGetErrorString(e);
            return false;
        }
        e = cudaMemcpy(g_host, g_target->data, g_bytes, cudaMemcpyDeviceToHost);
        if (e != cudaSuccess) {
            err = std::string("D2H staging copy failed: ") + cudaGetErrorString(e);
            return false;
        }
        e = cudaMalloc(&g_slot, g_bytes);
        if (e != cudaSuccess) {
            err = std::string("cudaMalloc(slot) failed: ") + cudaGetErrorString(e);
            return false;
        }
    }
    return true;
}

static int bench_h2d(const char * list) {
    // list is a comma separated set of sizes in MiB
    std::string s = list;
    size_t pos = 0;
    while (pos <= s.size()) {
        const size_t comma = s.find(',', pos);
        const std::string tok = s.substr(pos, comma == std::string::npos ? std::string::npos : comma - pos);
        if (!tok.empty()) {
            const size_t mib = (size_t) atoi(tok.c_str());
            if (mib > 0) {
                const size_t bytes = mib * 1048576ull;
                void * h = nullptr;
                void * d = nullptr;
                cudaError_t e = cudaHostAlloc(&h, bytes, cudaHostAllocDefault);
                if (e != cudaSuccess) {
                    fprintf(stderr, "tierspike: bench alloc host failed: %s\n", cudaGetErrorString(e));
                    return 1;
                }
                memset(h, 1, bytes);
                e = cudaMalloc(&d, bytes);
                if (e != cudaSuccess) {
                    fprintf(stderr, "tierspike: bench alloc device failed: %s\n", cudaGetErrorString(e));
                    return 1;
                }
                cudaEvent_t ev0, ev1;
                cudaEventCreate(&ev0);
                cudaEventCreate(&ev1);
                const int iters = 20;
                cudaMemcpy(d, h, bytes, cudaMemcpyHostToDevice); // warmup
                cudaEventRecord(ev0);
                for (int i = 0; i < iters; ++i) {
                    cudaMemcpyAsync(d, h, bytes, cudaMemcpyHostToDevice, 0);
                }
                cudaEventRecord(ev1);
                cudaEventSynchronize(ev1);
                float ms = 0.0f;
                cudaEventElapsedTime(&ms, ev0, ev1);
                const double gbps = (double) bytes * iters / (ms / 1000.0) / 1e9;
                fprintf(stderr, "{\"bench\":\"h2d\",\"mib\":%zu,\"iters\":%d,\"ms\":%.3f,\"gbps\":%.2f}\n",
                        mib, iters, ms, gbps);
                cudaEventDestroy(ev0);
                cudaEventDestroy(ev1);
                cudaFree(d);
                cudaFreeHost(h);
            }
        }
        if (comma == std::string::npos) {
            break;
        }
        pos = comma + 1;
    }
    return 0;
}

static void print_ids(const std::vector<llama_token> & ids) {
    fprintf(stderr, "\"token_ids\":[");
    for (size_t i = 0; i < ids.size(); ++i) {
        fprintf(stderr, "%s%d", i ? "," : "", ids[i]);
    }
    fprintf(stderr, "]");
}

} // namespace

int main(int argc, char ** argv) {
    std::string model_path;
    std::string prompt = "The capital of France is";
    std::string bench_sizes;
    int n_predict = 32;
    int n_ctx     = 4096;
    int n_threads = 4;
    int ngl       = 99;

    for (int i = 1; i < argc; i++) {
        const std::string a = argv[i];
        if      (a == "-m") { if (i + 1 < argc) model_path = argv[++i]; }
        else if (a == "-p") { if (i + 1 < argc) prompt = argv[++i]; }
        else if (a == "-n") { n_predict = atoi(argv[++i]); }
        else if (a == "-c") { n_ctx = atoi(argv[++i]); }
        else if (a == "-t") { n_threads = atoi(argv[++i]); }
        else if (a == "-ngl") { ngl = atoi(argv[++i]); }
        else if (a == "--bench-h2d") { if (i + 1 < argc) bench_sizes = argv[++i]; }
        else {
            fprintf(stderr, "tierspike: unknown argument: %s\n", a.c_str());
            return 1;
        }
    }

    if (!bench_sizes.empty()) {
        cudaFree(0); // init runtime
        return bench_h2d(bench_sizes.c_str());
    }
    if (model_path.empty()) {
        fprintf(stderr, "usage: tierspike -m model.gguf [-p prompt] [-n N] [-c N] [-ngl N]\n");
        fprintf(stderr, "       tierspike --bench-h2d 64,256,512\n");
        fprintf(stderr, "env: TIR_SPIKE=callback-count|zero-copy|h2d TIR_SPIKE_TENSOR=name TIR_SPIKE_MB=cap\n");
        return 1;
    }

    const char * env_mode = getenv("TIR_SPIKE");
    const char * env_tensor = getenv("TIR_SPIKE_TENSOR");
    const char * env_mb = getenv("TIR_SPIKE_MB");
    const char * env_base_ms = getenv("TIR_SPIKE_BASELINE_MS");
    if (env_mode != nullptr) {
        const std::string m = env_mode;
        if      (m == "callback-count") { g_mode = SPIKE_CALLBACK_COUNT; }
        else if (m == "zero-copy")      { g_mode = SPIKE_ZERO_COPY; }
        else if (m == "h2d")            { g_mode = SPIKE_H2D; }
        else {
            fprintf(stderr, "tierspike: unknown TIR_SPIKE=%s\n", env_mode);
            return 1;
        }
    }
    g_target_name = env_tensor != nullptr ? env_tensor : "blk.20.ffn_down.weight";
    const size_t cap_mib = env_mb != nullptr ? (size_t) atoll(env_mb) : 0;

    // B0 measures the CUDA path; the fork enables disk streaming by default, which forces no_alloc
#if defined(_WIN32)
    _putenv_s("LLAMA_DISK_STREAM_MB", "0");
#else
    setenv("LLAMA_DISK_STREAM_MB", "0", 1);
#endif

    llama_backend_init();

    llama_model_params mparams = llama_model_default_params();
    mparams.n_gpu_layers = ngl;

    const int64_t t_load = now_us();
    llama_model * model = llama_model_load_from_file(model_path.c_str(), mparams);
    if (model == nullptr) {
        fprintf(stderr, "tierspike: failed to load model\n");
        return 1;
    }
    fprintf(stderr, "tierspike: model loaded in %.1f s\n", (now_us() - t_load) / 1e6);

    std::string err;
    if (g_mode != SPIKE_OFF) {
        if (!setup_spike(model, cap_mib, err)) {
            fprintf(stderr, "tierspike: spike setup failed: %s\n", err.c_str());
            return 1;
        }
        ggml_cuda_set_node_residency_cb(spike_cb);
    }

    const llama_vocab * vocab = llama_model_get_vocab(model);
    const int n_prompt = -llama_tokenize(vocab, prompt.c_str(), (int32_t) prompt.size(), nullptr, 0, true, true);
    if (n_prompt <= 0) {
        fprintf(stderr, "tierspike: failed to tokenize\n");
        return 1;
    }
    std::vector<llama_token> tokens(n_prompt);
    if (llama_tokenize(vocab, prompt.c_str(), (int32_t) prompt.size(), tokens.data(), n_prompt, true, true) < 0) {
        fprintf(stderr, "tierspike: failed to tokenize (2)\n");
        return 1;
    }

    llama_context_params cparams = llama_context_default_params();
    cparams.n_ctx            = n_ctx;
    cparams.n_batch          = 1;
    cparams.n_ubatch         = 1;
    cparams.n_threads        = n_threads;
    cparams.n_threads_batch  = n_threads;
    cparams.no_perf          = false;

    llama_context * ctx = llama_init_from_model(model, cparams);
    if (ctx == nullptr) {
        fprintf(stderr, "tierspike: failed to create context\n");
        llama_model_free(model);
        return 1;
    }

    llama_sampler * smpl = llama_sampler_chain_init(llama_sampler_chain_default_params());
    llama_sampler_chain_add(smpl, llama_sampler_init_greedy());
    llama_batch batch = llama_batch_init(1, 0, 1);

    auto decode_one = [&](llama_token id, llama_pos pos, bool logits) -> bool {
        batch.n_tokens = 1;
        batch.token[0] = id;
        batch.pos[0] = pos;
        batch.n_seq_id[0] = 1;
        batch.seq_id[0][0] = 0;
        batch.logits[0] = logits;
        return llama_decode(ctx, batch) == 0;
    };

    int n_pos = 0;
    const int64_t t_prefill = now_us();
    for (int i = 0; i < n_prompt; ++i) {
        if (!decode_one(tokens[i], n_pos++, i == n_prompt - 1)) {
            fprintf(stderr, "tierspike: prefill failed at %d\n", i);
            return 1;
        }
    }
    const double prefill_s = (now_us() - t_prefill) / 1e6;

    std::vector<llama_token> gen_ids;
    const int64_t t_gen = now_us();
    for (int i = 0; i < n_predict; ++i) {
        const llama_token cur = llama_sampler_sample(smpl, ctx, -1);
        if (llama_vocab_is_eog(vocab, cur)) {
            break;
        }
        gen_ids.push_back(cur);
        if (!decode_one(cur, n_pos++, i + 1 < n_predict)) {
            fprintf(stderr, "tierspike: decode failed at %d\n", i);
            return 1;
        }
    }
    const double gen_s = (now_us() - t_gen) / 1e6;

    const double tok_s = gen_ids.empty() ? 0.0 : gen_ids.size() / gen_s;
    const double ms_per_token = gen_ids.empty() ? 0.0 : gen_s * 1000.0 / gen_ids.size();
    const double copy_ms = g_copy_us.load() / 1000.0;
    const double delta_ms = env_base_ms != nullptr ? ms_per_token - atof(env_base_ms) : 0.0;

    fprintf(stderr, "{\"mode\":\"%s\",\"tensor\":\"%s\",\"tensor_mib\":%.2f,\"cap_mib\":%zu,"
                    "\"cb_false\":%llu,\"cb_true\":%llu,\"cb_hits\":%llu,"
                    "\"prefill_tokens\":%d,\"prefill_s\":%.3f,\"gen_tokens\":%zu,\"gen_s\":%.3f,"
                    "\"tok_s\":%.2f,\"ms_per_token\":%.3f,\"delta_ms_per_token\":%.3f,"
                    "\"copy_count\":%llu,\"copy_ms\":%.3f,\"copy_ms_per_token\":%.3f,"
                    "\"pointer_type\":%d,\"baseline_ms_set\":%s,",
            env_mode != nullptr ? env_mode : "off",
            g_target_name.c_str(), g_bytes / 1048576.0, cap_mib,
            g_cb_false.load(), g_cb_true.load(), g_hits.load(),
            n_prompt, prefill_s, gen_ids.size(), gen_s,
            tok_s, ms_per_token, delta_ms,
            g_copy_count.load(), copy_ms, gen_ids.empty() ? 0.0 : copy_ms / gen_ids.size(),
            g_pointer_type, env_base_ms != nullptr ? "true" : "false");
    print_ids(gen_ids);
    fprintf(stderr, "}\n");

    llama_batch_free(batch);
    llama_sampler_free(smpl);
    llama_free(ctx);
    llama_model_free(model);

    return 0;
}
