# TIR-A C ABI

Contract for `tir.dll` (source: `src/tir-api/tir.h`). The header carries 14 functions and
8 structs: the 11 functions and 6 structs frozen for TIR-A P0, plus the two metadata/chat
functions and the `tir_chat_message` struct appended in S2, plus `tir_chat_apply_ex` and the
`tir_chat_options` struct appended in S2c. A host that follows this file needs no other
documentation.

## Overview

```c
uint32_t    tir_api_version(void);
const char *tir_last_error(void);

tir_engine * tir_engine_create(const tir_engine_options * opt);
tir_status   tir_engine_load(tir_engine * engine);
tir_status   tir_engine_info(tir_engine * engine, tir_model_info * out);
void         tir_engine_destroy(tir_engine * engine);

tir_session * tir_session_create(tir_engine * engine);
tir_status    tir_session_generate(tir_session * session, const tir_request * req,
                                   const tir_callbacks * cb, void * user);
void          tir_session_cancel(tir_session * session);
void          tir_session_destroy(tir_session * session);

tir_status    tir_stats_snapshot(tir_engine * engine, tir_stats * out);

/* S2, appended */
tir_status    tir_model_meta(tir_engine * engine, char * buf, size_t cap, size_t * out_len);
tir_status    tir_chat_apply(tir_engine * engine,
                             const tir_chat_message * msgs, size_t n_msgs,
                             int32_t add_generation_prompt,
                             char * out, size_t cap, size_t * out_len);

/* S2c, appended */
tir_status    tir_chat_apply_ex(tir_engine * engine,
                                const tir_chat_message * msgs, size_t n_msgs,
                                const tir_chat_options * opt,
                                char * out, size_t cap, size_t * out_len);
```

Typical order: create -> load -> info -> (per request) session_create -> generate ->
stats_snapshot -> session_destroy -> engine_destroy.

## Ownership and callback lifetime

- `tir_engine_create` copies `opt.model_path` (an internal `std::string`). The caller may free
  its string as soon as the call returns.
- `tir_session_generate` copies `req.prompt` before prefill. The caller may free its string
  as soon as the call returns.
- The engine owns the loaded model and the last-request statistics. The session owns its
  `llama_context`, its sampler chain and its KV/state. Both are created by the library and must
  be released with the matching `_destroy` function; there is no other way to free them.
- Destroy sessions before the engine. `tir_engine_destroy` frees the model but does not track
  sessions, so a session that outlives its engine dereferences freed memory.
- `tir_engine_load` is idempotent: a second call on a loaded engine returns `TIR_OK` without
  reloading.
- `tir_token.piece` points into a buffer owned by the library that lives only for the duration
  of the `on_token` call. Copy the bytes inside the callback if you need them afterwards.
- `tir_callbacks` itself is only read during `tir_session_generate`; the struct and the `user`
  pointer can live on the caller's stack. Both `cb` and `cb.on_token` may be `NULL`, in which
  case generation runs without notification.
- `tir_token.index` is the 0-based index of the token within the current request.
- `cb.on_event` is declared but not called in P0. Leave it `NULL`; event strings are not part
  of the P0 contract yet.
- A non-zero return from `on_token` cancels the request: generation stops, the call returns
  `TIR_E_CANCELLED`, and `tir_last_error` reads `cancelled by callback`.
- `tir_session_cancel` is safe to call from another thread while `tir_session_generate` runs
  on this session. The flag is cleared at the start of every `tir_session_generate`, so a
  cancelled session can serve the next request without being recreated.

## Metadata and chat template (S2, appended)

`tir_model_meta` and `tir_chat_apply` are new entry points. Nothing in the P0 contract above
changed: the existing 11 functions, 6 structs and `tir_api_version() == 0x00010000` are
untouched. The additions are append-only, so an old host keeps working against the new DLL.
A new host that calls them against an older DLL fails at load/resolve time; probe with
`GetProcAddress`/`dlsym` if the host must run on both.

### Buffer protocol (both functions)

- `out_len` (or `buf`-side `out_len`) is required and is always written when the call does not
  fail on argument checks. It is the length of the payload in bytes, excluding the trailing NUL.
- `cap == 0`: nothing is written to the buffer (`buf`/`out` may be `NULL`), the required length
  is written to `out_len`, and the call returns `TIR_OK`. This is the length query.
- `cap >= out_len + 1`: the payload is copied, NUL-terminated, and `out_len` is the payload
  length. The NUL is not counted.
- `0 < cap <= out_len`: nothing is copied, the required length is still written to `out_len`,
  and the call returns `TIR_E_INVALID`. Retry with `out_len + 1`.
- A non-zero `cap` with a `NULL` buffer is `TIR_E_INVALID`.

### `tir_model_meta`

Returns a compact JSON object, UTF-8, with `"schema":"tir.model-meta/v1"` and these fields
(no indentation, no line breaks; the template is one escaped string):

```json
{"schema":"tir.model-meta/v1","arch":"qwen35","n_layer":32,"n_embd":4096,"n_ctx_train":262144,"n_vocab":248320,"nextn":1,"mtp":true,"bos":11,"eos":248046,"chat_template":"...","has_chat_template":true,"thinking_start_tag":"<think>","thinking_end_tags":["\n</think>","</think>","<tool_call>"],"additional_stops":[],"supports_thinking":true}
```

(The template above is shortened; the real field holds the whole escaped source.)

| field | source |
|---|---|
| `arch` | `general.architecture` from the GGUF, `""` when absent |
| `n_layer`, `n_embd`, `n_ctx_train`, `n_vocab` | `llama_model_n_layer`, `llama_model_n_embd`, `llama_model_n_ctx_train`, `llama_vocab_n_tokens` |
| `nextn` | `llama_model_n_layer_nextn`, `0` when the file has no MTP head. JSON number |
| `mtp` | JSON boolean `true`/`false`, `nextn > 0`. Never the number `1`/`0` |
| `bos`, `eos` | `llama_vocab_bos`, `llama_vocab_eos` |
| `chat_template` | raw `tokenizer.chat_template` source, JSON-escaped (`"`, `\`, control chars) |
| `has_chat_template` | `true`/`false` |
| `thinking_start_tag` | `common_chat_params.thinking_start_tag`, `""` when the model has none |
| `thinking_end_tags` | `common_chat_params.thinking_end_tags`, JSON array of strings, `[]` when none |
| `additional_stops` | `common_chat_params.additional_stops`, JSON array of strings, `[]` when none |
| `supports_thinking` | `common_chat_params.supports_thinking`, JSON boolean |

- `has_chat_template` is `true` only when the GGUF carries the template. llama.cpp falls back to
  a built-in chatml source when the file has none; that fallback does not count, and `chat_template`
  is then `""`. A missing template is not an error: the call returns `TIR_OK`.
- A template that does not parse is reported the same way (`""`, `false`) and the rest of the
  metadata is still returned; `tir_last_error` carries the parser message.
- `n_layer` excludes nextn layers, `nextn` reports them separately.
- The JSON is unordered by contract but stable in practice: do not parse it with anything that
  cannot handle a reordered key set, and ignore unknown keys.
- The four reasoning fields are the model's own markers, not a host constant. They come from
  `common_chat_templates_apply` on a one-message `user: "x"` request with `use_jinja = true`,
  `enable_thinking = true`, `add_generation_prompt = true`, `add_bos = false`, `add_eos = false`;
  the markers do not depend on the conversation, so a placeholder message is enough. A host that
  wants to strip reasoning must read these instead of matching `<think>` itself.
- `thinking_end_tags` is a list, and the first entry is not always the bare closer: qwen3.8 with
  the specialized qwen3 parser reports `["\n</think>", "</think>", "<tool_call>"]`, the newline
  variant first because the template closes the block with a leading newline. Match any entry,
  and expect this list to change when the parser set changes.
- Match semantics (S2d-1 contract): entries are terminators, not all the same kind. Try the
  list in order and take the first match in the stream; when the matched entry is
  `"\n</think>"`, the leading newline belongs to the terminator and is consumed with it. The
  `"<tool_call>"` entry is a tool-call opener: terminate the reasoning segment there and route
  the remainder to the tool parser, do not emit it as reasoning. A host must not do a plain
  substring replace of `"</think>"` alone, or it will leave the newline and mismatch the
  `<tool_call>` case. `additional_stops` are separate generation stops, not reasoning tags.
- Segment rules for a host-side filter (S2d-1 contract, revised):
  - `additional_stops` are generation-wide, so they are matched in both segments. A match
    sends the text before it with the segment kind, then the stop, and the rest of the
    generation is dropped.
  - `thinking_end_tags` are matched only while the reasoning segment is open. A second
    `"</think>"` after the segment switched is plain content; do not switch again on it.
  - `"<tool_call>"` opens a tool call from either segment. A stream that starts in content
    (`starts_in_reasoning = false`) or one that emitted its closer before the opener must
    still emit the opener as a tool call and not as content text. The tool JSON after the
    opener is not content.
  - After a terminator the leading run of `"\n"` is dropped; this is the only trim. Text is
    not trimmed at the start of the reasoning or content segment otherwise.
  - Matching is byte-level. Hold back only the tail of the pending text that is still a
    proper prefix of a tag or a stop, emit the rest immediately, and flush the held tail
    with a final call at end of stream.
- No explicit template, a template that fails to apply, or one whose parser cannot be built
  gives `""`, `[]`, `[]`, `false` and still `TIR_OK`. The failed detection is reported through
  `tir_last_error` only; the remaining fields are unaffected.
- The fields are appended after `has_chat_template`; `schema` stays `tir.model-meta/v1` and no
  struct changed (S2d-0).

### `tir_chat_apply`

Formats OpenAI-style messages with the model's own GGUF `tokenizer.chat_template` (jinja) and
returns the prompt text. Feed the result to `tir_session_generate`; the ABI has no HTTP layer.

- `tir_chat_message` is `{struct_size, version, role, content}`. `role` and `content` are
  borrowed for the duration of the call and copied internally; `content` is UTF-8 plain text.
  Multi-turn order is preserved. Set `struct_size = sizeof(tir_chat_message)` and `version = 1`.
  Every message is checked before the template runs: `struct_size < sizeof(tir_chat_message)`
  (including `0`) and `version != 1` are rejected with `TIR_E_INVALID`, and the error slot
  names the offending index (`message 1 struct_size is too small`,
  `unsupported message version 2 at index 0`). `struct_size` larger than the library's
  `sizeof` is accepted, same rule as the other input structs.
- `role` is passed through as written (`system`, `user`, `assistant`, `tool`, ...). The template
  decides what it does with an unknown role.
- `add_generation_prompt != 0` appends the assistant generation prefix (for Qwen:
  `<|im_start|>assistant\n`). Pass `0` only when you continue an assistant message yourself.
- The rendered text is the model's own template with the model's own defaults. `tir_chat_apply`
  has no argument to change them (`enable_thinking` is left at the template default, `true`),
  so a thinking model emits its reasoning opener: Qwen renders
  `<|im_start|>assistant\n<think>\n` for `add_generation_prompt != 0`. That is intended - S2
  formats what the model would be served. Use `tir_chat_apply_ex` with
  `enable_thinking = 0` (S2c) to ask the template for the no-thinking render instead of
  post-processing the text; other template kwargs (tools, extra variables) are still not
  reachable from the ABI.
- No BOS/EOS is added by the formatter, and none is added by the template engine: the prompt is
  the template rendering only. `tir_session_generate` tokenizes it as-is.
- Failures: `n_msgs == 0`, `msgs == NULL`, an entry with `struct_size`/`version` outside the
  contract, or an entry with `role`/`content == NULL` is `TIR_E_INVALID`; an engine that is not
  loaded is `TIR_E_INVALID`; a model without an explicit GGUF template, a template that fails to
  parse, or a template that fails to render is `TIR_E_MODEL`. Read `tir_last_error()` for the
  parser message.
- The rendered prompt is not checked against `n_ctx`. A prompt that does not fit fails inside
  `tir_session_generate`, as with any other prompt.
- Not a hot path: the template is parsed on every call. A host that formats many conversations
  should cache the prompt itself rather than call this per token.

### `tir_chat_apply_ex` and `tir_chat_options` (S2c, appended)

Same rendering, same buffer protocol and the same message checks as `tir_chat_apply`, plus a
`tir_chat_options` argument that reaches one template variable.

```c
typedef struct tir_chat_options {
    uint32_t struct_size;
    uint32_t version;
    int32_t add_generation_prompt; /* 1/0 */
    int32_t enable_thinking;       /* 1 on, 0 off, -1 template default */
} tir_chat_options;
```

- `opt == NULL` is the `tir_chat_apply` behaviour: `add_generation_prompt = 1`,
  `enable_thinking = -1`. `tir_chat_apply` itself is a thin wrapper that builds that default
  struct and calls `tir_chat_apply_ex`, so its output is byte-identical to S2.
- Set `struct_size = sizeof(tir_chat_options)` and `version = 1`. The same input-struct rule as
  `tir_engine_options` applies (`struct_size >= sizeof`, `version == 1`); anything else is
  `TIR_E_INVALID` with `options struct_size is too small` or `unsupported options version N`.
- `add_generation_prompt` accepts `0`/`1` only, `enable_thinking` accepts `-1`/`0`/`1` only.
  Any other value is `TIR_E_INVALID` and names the field and the value.
- `enable_thinking` is passed to the template as
  `common_chat_templates_inputs.enable_thinking = (opt && opt->enable_thinking >= 0) ? (opt->enable_thinking != 0) : true`.
  `0` is the no-thinking request, `1` and `-1` both render the thinking form for a template
  whose default is on.
- What "off" looks like is the template's decision, not the ABI's. The qwen3.8 template used by
  the P0 model does not delete the marker: it renders
  `<|im_start|>assistant\n<think>\n` when thinking is on (the block is left open for the model)
  and `<|im_start|>assistant\n<think>\n\n</think>\n\n` when it is off (a closed, empty block is
  prepended). The off render is therefore 11 bytes longer than the on render for the same
  conversation (121 vs 110 bytes in `test_chat`). Compare the two renders by content, not by
  length, and do not assume `enable_thinking = 0` removes `<think>`.
- `enable_thinking` only changes the rendered prompt. It does not constrain generation: the ABI
  has nothing that stops the model from emitting reasoning text after the closed block, and
  this field does not hide such text from the caller. Separating reasoning from the answer, and
  hiding it, is the S2d parser's job. S2c stops at the render.
- `test_chat.c` covers: thinking on has the open block, thinking off has the closed empty block,
  `opt == NULL`, `enable_thinking = -1` and `enable_thinking = 1` all match `tir_chat_apply`
  byte for byte, `add_generation_prompt = 0` still omits the assistant prefix, a `struct_size`
  larger than `sizeof(tir_chat_options)` is accepted, and the four invalid options
  (`struct_size`, `version`, `enable_thinking`, `add_generation_prompt`) are rejected.

## Threading and reentrancy

- One `tir_session_generate` at a time per session. The session owns `n_past`, the KV cache and
  the sampler; concurrent calls on the same session corrupt all three.
- P0 does not serialize calls on one engine either. `tir_stats_snapshot` reads
  `engine->last_stats`, which a running generate writes without a lock. Run at most one
  generate per engine at a time, or accept racy statistics. Separate engines are independent
  and may run in parallel, subject to VRAM.
- Callbacks run on the thread that called `tir_session_generate`, on the same stack. Do not
  call back into the engine from `on_token` (no nested generate, no destroy from the callback):
  the engine is single-threaded and not reentrant, and `tir_session_destroy` on the running
  session frees the context underneath the decode loop.
- `tir_session_cancel` is the only entry point intended for another thread.
- `tir_last_error` is thread-local. A message set on one thread is not visible on another.

## Errors

- Every function returning `tir_status` uses `TIR_OK == 0`. Any non-zero value is a failure:
  `TIR_E_INVALID` (1), `TIR_E_MODEL` (2), `TIR_E_PLAN` (3), `TIR_E_OOM` (4),
  `TIR_E_DEVICE` (5), `TIR_E_CANCELLED` (6), `TIR_E_INTERNAL` (7).
- Functions that return a pointer (`tir_engine_create`, `tir_session_create`) report failure by
  returning `NULL`; there is no status value to check.
- `tir_last_error()` returns the message of the last failed call on this thread, or `""` when
  the last call on this thread succeeded. It never returns `NULL`.
- Every exported function except `tir_api_version` and `tir_last_error` clears the slot on
  entry, so read `tir_last_error()` right after the failing call. The returned pointer is owned
  by the library and stays valid until the next call on the same thread; copy the string if you
  need to keep it.
- An error does not poison the ABI but it can leave the session in an undefined state, because
  the KV cache may hold a partial prompt or a partial decode. After `TIR_E_INTERNAL`,
  `TIR_E_MODEL`, `TIR_E_OOM` or `TIR_E_DEVICE`, destroy and recreate the session. After
  `TIR_E_CANCELLED` the session is reusable (the next generate resets `n_past`), and
  `TIR_E_INVALID` from argument checks means nothing was touched.
- `tir_stats_snapshot` reports the statistics of the last request that ran on the engine.
  Both `tir_generate_plain` and `tir_generate_mtp` zero `last_stats` as their first action, so
  one request never mixes with the numbers of an earlier one. The MTP path fills every field;
  the plain path fills the token and timing counters and reports `acceptance = 0` and
  `mean_len = 0`. A cancellation or an error after a run has started returns before the
  counters are written, so the snapshot reads all zeros - not the values of an earlier MTP
  request. Read `acceptance` and `mean_len` only from a successful MTP run. A call rejected by
  the argument checks in `tir_session_generate` (including the `struct_size`/`version` checks)
  never reaches either path and leaves the previous snapshot in place.

## Versioning

- `tir_api_version()` returns `major << 16 | minor`. P0 returns `0x00010000` (1.0).
  Hosts should refuse anything below `0x00010000`.
- Struct headers are not uniform. Two input structs, two output structs and the S2
  `tir_chat_message` carry `uint32_t struct_size` followed by `uint32_t version`;
  `tir_token` and `tir_callbacks` carry neither.
  - Input: `tir_engine_options` and `tir_request` start with `struct_size` and `version`.
    `tir_engine_create` validates them, and so does `tir_session_generate` before it
    dispatches. Set `struct_size = sizeof(struct)` and `version = 1`. The test is
    `struct_size >= sizeof(struct)`, so `struct_size == 0` is rejected for input structs
    (there is no header-only form), and so is any `version != 1`. Both calls fail with
    `TIR_E_INVALID` (`NULL` plus the error slot for `tir_engine_create`) and the message
    `... struct_size is too small` or `unsupported ... version`.
  - Per message input: `tir_chat_message` follows the same input rule, checked for every
    element of the array (`tir_chat_apply`). `struct_size == 0` and `version != 1` are
    `TIR_E_INVALID` with the message index in the error slot.
  - Output: `tir_model_info` and `tir_stats` start with `struct_size` and `version` as well.
    Pass `sizeof(struct)` to receive the full struct. `struct_size == 0` means "current full
    size": it is not read as a request for a shorter prefix, the library copies the header
    only, and it writes `struct_size = sizeof(struct)` and `version = 1` back so the caller
    can see the current size. The remaining fields are left as the caller had them, so a
    `0` request returns no data. A non-zero `struct_size` below `sizeof(struct)` is rejected
    with `TIR_E_INVALID`.
  - No header: `tir_token` and `tir_callbacks` have no `struct_size` and no `version`. Any
    layout change to them is an ABI break and needs a new DLL name.
- New fields are appended; existing fields never change type, order or meaning within a major
  version. There is no prefix compatibility in either direction: a non-zero `struct_size`
  below the library's `sizeof(struct)` is rejected, never served the old prefix. A
  `struct_size` larger than the library's `sizeof(struct)` is accepted (a newer host calling
  an older DLL): the library touches only its own fields and reports its own size back, so
  the tail is ignored.
- The `tir_chat_message` struct and the `tir_model_meta`/`tir_chat_apply` functions were
  appended in S2 without touching any existing declaration and without a `tir_api_version`
  bump (adding entry points is backward compatible for existing hosts). Detect them by symbol
  presence, not by version.
- The same applies to S2c: `tir_chat_options` and `tir_chat_apply_ex` are appends, no existing
  signature changed, `tir_api_version()` is still `0x00010000`. `tir_chat_options` follows the
  input-struct rule (`struct_size` and `version` validated, `version == 1`).
- S2d-0 only appends JSON keys to `tir_model_meta` (`thinking_start_tag`, `thinking_end_tags`,
  `additional_stops`, `supports_thinking`). No struct, no signature, no `tir_api_version` change;
  `schema` is still `tir.model-meta/v1`. A host that ignores unknown keys needs no change.
- An ABI major change ships under a new DLL name. Never reuse `tir.dll` for a breaking change.

## CUDA context

- P0 uses the primary CUDA context of the device llama.cpp picks. All tensors of the engine and
  of its sessions live in that context.
- The host must not call `cudaDeviceReset()` while the engine is loaded, and must not call
  `cudaCtxResetPersistingL2Cache` or any other function that destroys the primary context. A
  reset frees every allocation the engine owns and the next decode step touches freed memory.
- The host must not create its own context on the same device and assume the engine will share
  it, and must not switch the current context under a running generate. If the host needs CUDA
  for its own work, use a separate non-primary context or wait until `tir_engine_destroy`.
- Threading: CUDA work is submitted from the calling thread inside `tir_session_generate`.
  Do not rely on the host's current context on another thread.
- `tir_engine_destroy` releases the engine's resources but does not reset or destroy the
  primary context; the process keeps it until exit.

## Runtime prerequisites

- **`LLAMA_DISK_STREAM_MB=0` is required for CUDA offload in this fork.** The fork streams
  weights from disk by default and its residency hook is CPU-only, so disk streaming combined
  with `n_gpu_layers > 0` is unsupported and crashes (or fails to map) during load. Set
  `LLAMA_DISK_STREAM_MB=0` in the process environment before the first model load; the
  library reads it once and caches the answer. With `n_gpu_layers <= 0` (CPU only) the
  variable may be left unset. All three host samples set it before they load the DLL, because
  a static-CRT host cannot set it from inside the DLL.
- **CUDA runtime DLLs must be on `PATH`**: `<TIR_ROOT>\runtime\cuda-13.5\bin\x64`
  (the CUDA runtime and cuBLAS DLLs) and `<TIR_ROOT>\runtime\cuda-13.5\bin` (nvcc
  support files, needed at build time). `tir.dll` also needs `llama.dll`, `llama-common.dll`
  and the `ggml*.dll` from the same `bin` directory; those are not copied next to the host,
  so either put the host in `build\tir-api\bin`, or add that directory to the DLL search
  path. On Windows the safe way to do the latter is `PATH`, not `os.add_dll_directory`:
  `ctypes.CDLL` defaults to `LOAD_LIBRARY_SEARCH_DEFAULT_DIRS`, which ignores `PATH`, so
  `python_host.py` prepends the `tir.dll` directory to `PATH` and then calls
  `ctypes.CDLL(path, winmode=0)` (legacy search). `winmode=0` makes the loader use `PATH`
  and ignores any directory added with `os.add_dll_directory`, so do not mix the two. Node
  does the same with `process.env.PATH`. The C# host does not modify `PATH`; see the host
  section for what it expects.
- The model must be a GGUF file with a supported Qwen3.8 layout. For MTP the file must carry a
  nextn head; `tir_engine_load` silently falls back to plain decode when it does not, and
  `tir_engine_info().mtp` reports `0` in that case.
- `tir_request.prompt + n_predict` must fit inside `n_ctx`, otherwise the call fails with an
  error instead of truncating.

## P0 limitations

- **Greedy only.** `tir_session_generate` always samples greedily: the plain path installs a
  greedy sampler and the MTP path pins `temp = 0, top_k = 1`. P0 implements no temperature,
  top-k or seed sampling on the plain path. `req.temperature`, `req.seed` and `req.greedy`
  exist for forward compatibility: they are accepted without validation and have almost no
  effect. `req.temperature` is never read by the plain path, `req.greedy` is never read at
  all (passing `greedy = 0` does not change the output), and `req.seed` only reaches the MTP
  draft parameters, where the draft temperature is pinned to `0` anyway. A host that needs
  real sampling must wait for a later phase.
- **MTP width is 1.** `TIR_MTP_N_MAX` is 1, so every MTP step drafts one token and
  `tir_stats.acceptance` / `mean_len` are measured with a ceiling of
  `mean_len <= 2.0` tokens per verify step. The limit exists because a target verify batch of
  3 or more rows on this hybrid (gated delta net) model takes a chunked kernel that shifts
  logits by about 0.13 against sequential decode and breaks plain/MTP token parity. Batches of
  1-2 rows are bit-identical, and parity is what P0 gates on. A later phase may widen it.
- `req.n_predict == 1` with `mtp = 1` takes the plain path; there is nothing to draft against.
- P0 is a single-model, single-request-per-engine implementation. There is no batching of
  independent prompts, no continuous batching, no prompt cache reuse across requests.
- `tir_stats.tok_s` excludes prefill (it is `gen_tokens / decode_ms`); `ttft_ms` includes
  tokenization and prefill of the whole prompt.

## Host smoke tests

Three hosts in `tests/tir-api/` check the same four things: the DLL loads, the version is at
least 1.0, `tir_last_error` exists, and a rejected call (`tir_engine_create(NULL)`) leaves a
message in the thread-local error slot. All three default to
`build\tir-api\bin\tir.dll` (C#: the DLL next to its exe) and honour `TIR_DLL`.

```bat
rem Python, no dependencies
python src\llama.cpp-fork\tests\tir-api\python_host.py

rem Node, koffi 2.16.3 is pinned in tests\tir-api\package.json: npm ci once
pushd src\llama.cpp-fork\tests\tir-api && npm ci && popd
node src\llama.cpp-fork\tests\tir-api\node_host.mjs

rem C#, compiled with the .NET Framework compiler into the DLL directory
csc /nologo /out:build\tir-api\bin\csharp_host.exe src\llama.cpp-fork\tests\tir-api\csharp_host.cs
build\tir-api\bin\csharp_host.exe
```

If `csc` is not on `PATH`, use the one in
`C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe`. A .NET SDK machine can build the
same file as a one-file project instead (`dotnet run` needs a project file, so put
`<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType>
<TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>` in a `csharp_host.csproj`
next to the source); copy the resulting exe next to `tir.dll` or set `TIR_DLL`.

C# specifics: `[DllImport("tir.dll")]` resolves by base name, not by `TIR_DLL`. The loader
searches the directory of the exe, the current directory and `PATH`. `TIR_DLL` is honoured
only by pinning that file first with `LoadLibraryW`; the P/Invoke import then reuses the
module already loaded under the base name `tir.dll`. The exe is built into
`build\tir-api\bin`, so that directory is both the exe directory and the module directory:
`tir.dll` and its `llama.dll` / `ggml*.dll` siblings are found without a copy step. The CUDA
runtime is not there, so put `<TIR_ROOT>\runtime\cuda-13.5\bin\x64` on `PATH` (or copy
the CUDA DLLs next to the exe). If you build the exe elsewhere, either copy the whole
`build\tir-api\bin` next to it, or put that directory and the CUDA directory on `PATH` and set
`TIR_DLL` to the absolute path of `tir.dll`.

Each host must print its `OK` line and exit 0. The Python and Node hosts prepend the DLL
directory to `PATH` before loading, because the loader finds `llama.dll` and the `ggml*.dll`
only through `PATH` when the DLL is opened by absolute path. The C# host does not touch
`PATH`; it relies on the exe-adjacent layout and on the CUDA directory being visible.
