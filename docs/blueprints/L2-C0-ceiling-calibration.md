# L2 切片蓝图：C0 上限校准与真实长上下文基线

- 所属 L0：`docs/blueprints/L0-system.md`（TIR-A 交互运行时）
- 所属 L1：`docs/blueprints/L1-interactive-runtime.md`（M2 Generation）
- 日期：2026-11-09
- 状态：已执行（C0a/C0b）；结果见 `<WORKSPACE>\docs\reports\2026-11-09-ceiling-calibration.md`
- 上游决策：`<WORKSPACE>\docs\reports\2026-11-09-tir-a2-integrated-decision.md`；不加磁盘层，先吃满 GPU

## 目标

把“4B 92 / 8B 64 / 1B 336”从短序列单次数字，变成可复现的真实上限基线：

1. 真实填 2k/8k/16k 上下文，而不是只分配 16k；
2. 拆分每 token 的 GPU eval、sampler、detok、callback 与 gap；
3. 用 `llama_perf_context` 的 `n_reused / n_reallocs_*` 判断 graph 是否真的复用；
4. 给 C1（host 热路径）和 C2（GPU 效率）提供“该改哪里”的证据。

不做：磁盘层、MTP 宽度、投机、量化重定、kernel 改动、8B 100 t/s。

## 事实包（执行前先读）

| 事实 | 位置 |
|---|---|
| 生产 worktree 是 `<TIR_ROOT>` master `727fa5c`；`tir-b-p0` 是 TIR-C 分支 | `git worktree list` |
| `build\build-tir-api.bat` 当前硬编码 `ROOT=<TIR_ROOT>-p0`，在 master 跑会构建错树 | `build\build-tir-api.bat:4` |
| `llama_perf_context` 提供 `t_eval_ms / t_p_eval_ms / n_reused / n_reallocs_same / n_reallocs_diff` | `include/llama.h:1680` |
| `llama_perf_sampler` 提供 `t_sample_ms / n_sample`，且有 reset | `include/llama.h:1694` |
| `tir_stats` 当前 9 个字段，`write_versioned` 按 `struct_size` 拷前缀 | `src/tir-api/tir.h:77`、`tir_core.cpp:17` |
| plain 热路径每 token 两次 `token_to_piece` + vector 分配 | `src/tir-api/tir_generate.cpp:160-171` |
| CUDA graph 默认开启，但节点类型/同步可能禁用 | `ggml/src/ggml-cuda/ggml-cuda.cu:2738` |
| 模型：1B `<MODEL_DIR>\blobs\sha256-b1c3bf...`；4B `<MODEL_DIR>\blobs\sha256-de8cf245...`；Nemotron 4B、DSR1 8B 在 `<MODEL_DIR>\bionic\...` | 见 §测试矩阵 |
| 硬件：HBM 306–330 GB/s；launch 7.5–8.1 µs；功耗 105–109 W | `<WORKSPACE>\docs\reports\2026-11-09-hardware-ceiling-probe.md` |

## 设计

### C0a：stats 追加与阶段计时

`tir_stats` 末尾追加（append-only，不改旧字段顺序）：

```c
double eval_ms;          /* llama_perf_context.t_eval_ms */
double prompt_eval_ms;   /* llama_perf_context.t_p_eval_ms */
double sampler_ms;       /* llama_perf_sampler 增量 */
uint64_t step_us;        /* 每个 decode 迭代的墙钟总和 */
uint64_t detok_us;       /* token_to_piece 总和 */
uint64_t callback_us;    /* on_token 总和 */
int32_t graph_reused;    /* n_reused */
int32_t graph_reallocs_same;
int32_t graph_reallocs_diff;
```

`tir_generate_plain` 内：

- 生成开始时 `llama_perf_context_reset` + `llama_perf_sampler_reset`；
- 每轮记录 `step_us`、`detok_us`、`callback_us`；
- 结束时读 `llama_perf_context` / `llama_perf_sampler` 填字段；
- 不改变采样、token 序列或回调语义。

判读口径：

- `eval_ms` 接近 `decode_ms` → GPU 受限；
- `eval_ms` 明显小于 `decode_ms`，且 `sampler_ms + detok + callback` 占比高 → host 受限；
- `graph_reallocs_same > 0` 且随 token 增长 → graph 每 token 重建，C2 先查；
- `graph_reused` 随 token 增长 → graph 已复用，C2 不再做“重开 graph”。

### C0b：ceiling harness

新增 `tests/tir-api/bench_ceiling.c`，目标 `tir-bench-ceiling`：

```text
tir-bench-ceiling <model> <n_ctx> <n_prompt_tokens> <n_predict> <kv_q4> <runs>
```

- prompt 由固定段落重复到约 `n_prompt_tokens`，报告实际 token 数；
- 1 次 warmup + `runs` 次测量；输出一行 JSON `tir.ceiling/v1`；
- 字段：`prompt_tokens, gen_tokens, tok_s_p50, tok_s_p95, ttft_ms, eval_ms, prompt_eval_ms, sampler_ms, step_us, detok_us, callback_us, graph_*`；
- 不链接新库，不新增公共 API；只读 `tir_stats`。

`test/bench-ceiling.ps1`：

- 调用前/后 `nvidia-smi --query-gpu=clocks.sm,clocks.mem,power.draw,temperature.gpu,memory.used --format=csv,noheader`；
- 跑矩阵，结果追加到 `test/ceiling/results.jsonl`；
- 同时打印同轮 `llama-bench` 命令，便于人工对照（不自动解析）。

### 测试矩阵

| 模型 | 路径 | 填充 | KV | 目的 |
|---|---|---|---:|---|
| minicpm 1.1B | `<MODEL_DIR>\blobs\sha256-b1c3bf...` | 512/2k | q4/q8 | host 开销金丝雀 |
| qwen3.5 4.2B | `<MODEL_DIR>\blobs\sha256-de8cf245...` | 2k/8k | q4/q8 | 主目标，看 8–15% 缺口 |
| Nemotron 4B | `<MODEL_DIR>\bionic\lmstudio-community\NVIDIA-Nemotron-3-Nano-4B-GGUF\NVIDIA-Nemotron-3-Nano-4B-Q4_K_M.gguf` | 2k/8k | q4 | 4B 已接近上限的对照 |
| DSR1 8B | `<MODEL_DIR>\bionic\lmstudio-community\DeepSeek-R1-0528-Qwen3-8B-GGUF\DeepSeek-R1-0528-Qwen3-8B-Q4_K_M.gguf` | 2k/8k | q4 | 确认 8B 没有剩余空间 |

16k 先只跑 qwen3.5 4.2B 一次（prefill 慢），其余用 8k。

## 接口契约

- `tir_stats.struct_size` 仍是调用者传入值；旧调用者只拿到前缀，不破坏 ABI；
- `version` 保持 1（append-only，不 bump）；在 `tir.h` 注释说明；
- `tir.ceiling/v1` JSON 字段名固定，后续只追加；
- 不修改 `tir_generate` 的 token 选择、回调次数、错误码。

## 测试与验收

1. 在 `<TIR_ROOT>` 执行 `build\build-tir-api.bat` → `BUILD_OK`，且 `build\tir-api\bin\tir-bench.exe` 与 `tir-bench-ceiling.exe` 存在。
2. `set TIR_TEST_MODEL=<MODEL_DIR>\blobs\sha256-b1c3bf...`，`build\tir-api\bin\tir-test-generate.exe` → `test_generate: OK`（token 序列不变）。
3. `build\tir-api\bin\tir-bench-ceiling.exe <minicpm> 2048 512 64 1 3` → 一行合法 JSON；`gen_tokens=64`、`eval_ms>0`、`tok_s_p50>0`、`graph_reallocs_same>=0`。
4. `build\tir-api\bin\tir-bench-ceiling.exe <qwen3.5-4.2B> 8192 4096 128 1 3` → 完成；`step_us/1000` 与 `decode_ms` 误差 ≤5%；`eval_ms<=decode_ms*1.05`。
5. `test\bench-ceiling.ps1` → `test/ceiling/results.jsonl` 至少包含 1B/4B/8B 三行，且每行带 clock/power。
6. 同一 prompt 的 64 token 在 C0 前后完全一致（用 `test_generate` 的断言或保存 token id 对比）。

## 停止条件

- `llama_perf_context` 的 `t_eval_ms` 与 `decode_ms` 差异 >20%，且无法用 `step_us` 解释 → 改用 CUDA event 包住 decode+sample 对，先修测量再继续；
- 16k prefill 单次 >10 分钟 → 16k 只跑一次，其余降到 8k，并在报告标注；
- `tir_stats` 追加导致任何旧 host 崩溃 → 回退字段，改用独立 `tir_profile_snapshot` API；
- 同一切片连续 2 次失败 → 停止，写报告，不猜。

## 写入域

- `src/llama.cpp-fork/src/tir-api/tir.h`
- `src/llama.cpp-fork/src/tir-api/tir_generate.cpp`
- `src/llama.cpp-fork/src/tir-api/tir_core.cpp`（仅 stats 清零/快照如需）
- `src/llama.cpp-fork/tests/tir-api/bench_ceiling.c`（新）
- `src/llama.cpp-fork/tests/tir-api/test_profile.c`（新）
- `src/llama.cpp-fork/src/tir-api/CMakeLists.txt`（加 target）
- `build/build-tir-api.bat`（`ROOT` 改为 `%~dp0..`；加 target）
- `test/bench-ceiling.ps1`（新）
- `build/run-profile.bat`、`build/run-ceiling.bat`（复现 helper）
- `docs/blueprints/L1-interactive-runtime.md`（追加 stats 说明一行）
- `<WORKSPACE>\docs\reports\2026-11-09-ceiling-calibration.md`（结果报告，新）

## 读取域

- `include/llama.h`（perf API）
- `src/llama-context.cpp`、`src/llama-sampler.cpp`
- `tests/tir-api/bench.c`、`tests/tir-api/test_generate.c`
- `ggml/src/ggml-cuda/ggml-cuda.cu`（只读，确认 graph 条件）
- `src/tir-api/tir_internal.h`、`tir_mtp.cpp`（只读，避免破坏）

## 禁止

- `ggml` / `llama.cpp` 核心改动；
- 磁盘 T2、MTP 宽度、draft 模型、量化文件；
- 改 `tir_generate` 的 token 语义；
- 提交/推送（用户明确要求才做）。

## 回收方式

- `git status --porcelain` 对照写入域；
- 若出现写入域外文件，先审计再决定；
- 验收命令的实际输出贴进执行记录；
- 不合并、不提交，等用户确认。

## 执行记录

| 时间 | 事件 | 证据 |
|---|---|---|
| 2026-11-09 | C0a RED：`test_profile.c` 对 `eval_ms/step_us/graph_*` 报 C2039 | `cl` 输出 9 个 C2039 |
| 2026-11-09 | C0a GREEN：追加 stats 字段、接 `llama_perf_context/sampler`、`no_perf=false` | `test_profile: OK tokens=64 ... graph=68/0/0` |
| 2026-11-09 | C0b：`tir-bench-ceiling` + PS1 遥测 | 1B p50 308.3；4B 81.8–85.9；8B 57.1 |
| 2026-11-09 | 报告 | `<WORKSPACE>\docs\reports\2026-11-09-ceiling-calibration.md` |
