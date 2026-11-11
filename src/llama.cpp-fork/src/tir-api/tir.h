#pragma once

#include <stddef.h>
#include <stdint.h>

#ifdef _WIN32
#  ifdef TIR_BUILD
#    define TIR_API __declspec(dllexport)
#  else
#    define TIR_API __declspec(dllimport)
#  endif
#else
#  define TIR_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef struct tir_engine  tir_engine;
typedef struct tir_session tir_session;

typedef enum tir_status {
    TIR_OK = 0,
    TIR_E_INVALID = 1,
    TIR_E_MODEL = 2,
    TIR_E_PLAN = 3,
    TIR_E_OOM = 4,
    TIR_E_DEVICE = 5,
    TIR_E_CANCELLED = 6,
    TIR_E_INTERNAL = 7
} tir_status;

typedef struct tir_engine_options {
    uint32_t struct_size;
    uint32_t version;
    const char * model_path;   /* UTF-8, copied by engine_create */
    int32_t n_ctx;             /* >= 512 */
    int32_t n_gpu_layers;      /* 99 = all */
    int32_t n_threads;         /* CPU threads for batch */
    int32_t kv_q4;             /* 1 = q4_0 KV, 0 = q8_0 */
    int32_t mtp;               /* 1 = enable MTP if model has nextn */
} tir_engine_options;

typedef struct tir_request {
    uint32_t struct_size;
    uint32_t version;
    const char * prompt;       /* UTF-8, copied by generate */
    int32_t n_predict;
    int32_t greedy;            /* 1 = temperature 0 */
    float temperature;
    uint32_t seed;
} tir_request;

typedef struct tir_token {
    int32_t id;
    const char * piece;        /* valid only during on_token */
    uint32_t piece_len;
    uint32_t index;
} tir_token;

typedef struct tir_callbacks {
    int (*on_token)(void * user, const tir_token * tok); /* 0 continue, !=0 cancel */
    void (*on_event)(void * user, const char * event);   /* optional */
} tir_callbacks;

typedef struct tir_model_info {
    uint32_t struct_size;
    uint32_t version;
    int32_t n_layer;
    int32_t n_embd;
    int32_t n_ctx_train;
    int32_t n_vocab;
    int32_t mtp;
} tir_model_info;

typedef struct tir_stats {
    uint32_t struct_size;
    uint32_t version;
    uint64_t prompt_tokens;
    uint64_t gen_tokens;
    double ttft_ms;
    double decode_ms;
    double tok_s;
    double acceptance;
    double mean_len;
    /* append-only C0 perf fields; old callers pass a smaller struct_size */
    double eval_ms;          /* llama_perf_context.t_eval_ms */
    double prompt_eval_ms;   /* llama_perf_context.t_p_eval_ms */
    double sampler_ms;       /* llama_perf_sampler.t_sample_ms */
    uint64_t step_us;        /* sum of decode-loop wall time */
    uint64_t detok_us;       /* token_to_piece total */
    uint64_t callback_us;    /* on_token total */
    int32_t graph_reused;    /* llama_perf_context.n_reused */
    int32_t graph_reallocs_same;
    int32_t graph_reallocs_diff;
} tir_stats;

typedef struct tir_chat_message {
    uint32_t struct_size;
    uint32_t version;
    const char * role;         /* "system" | "user" | "assistant", copied by the call */
    const char * content;      /* UTF-8, copied by the call */
} tir_chat_message;

typedef struct tir_chat_options {
    uint32_t struct_size;
    uint32_t version;
    int32_t add_generation_prompt; /* 1/0, appended assistant prefix */
    int32_t enable_thinking;       /* 1 on, 0 off, -1 template default */
} tir_chat_options;

TIR_API uint32_t    tir_api_version(void);
TIR_API const char * tir_last_error(void);

TIR_API tir_engine * tir_engine_create(const tir_engine_options * opt);
TIR_API tir_status   tir_engine_load(tir_engine * engine);
TIR_API tir_status   tir_engine_info(tir_engine * engine, tir_model_info * out);
TIR_API void         tir_engine_destroy(tir_engine * engine);

TIR_API tir_session * tir_session_create(tir_engine * engine);
TIR_API tir_status    tir_session_generate(tir_session * session,
                                           const tir_request * req,
                                           const tir_callbacks * cb,
                                           void * user);
TIR_API void          tir_session_cancel(tir_session * session);
TIR_API void          tir_session_destroy(tir_session * session);

TIR_API tir_status    tir_stats_snapshot(tir_engine * engine, tir_stats * out);

/* Metadata and chat template. cap == 0 only writes the required length to out_len
   (buffer untouched) and returns TIR_OK; a too small cap writes the required length
   and returns TIR_E_INVALID. out_len excludes the trailing NUL, which is written
   when cap is large enough. */
TIR_API tir_status    tir_model_meta(tir_engine * engine,
                                     char * buf, size_t cap, size_t * out_len);

TIR_API tir_status    tir_chat_apply(tir_engine * engine,
                                     const tir_chat_message * msgs, size_t n_msgs,
                                     int32_t add_generation_prompt,
                                     char * out, size_t cap, size_t * out_len);

/* opt == NULL keeps the template defaults: add_generation_prompt = 1, enable_thinking = -1. */
TIR_API tir_status    tir_chat_apply_ex(tir_engine * engine,
                                        const tir_chat_message * msgs, size_t n_msgs,
                                        const tir_chat_options * opt,
                                        char * out, size_t cap, size_t * out_len);

#ifdef __cplusplus
}
#endif
