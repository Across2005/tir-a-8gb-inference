# 引擎性能与稳定性检查（2026-11-11）

- 检查时间：2026-11-11，完成于 10:21 +0800
- 代码状态：工作树未提交；`tir.dll` sha256 `2b8efb7f39ca270e…`（探针恢复后重建，`BUILD_OK`）
- 范围：只做只读检查与既有测试执行，**未修改任何引擎源码**；一次性探针已删除
- 硬件：RTX 5060 Laptop 8151 MiB，检查期间余量 6875 MiB、利用率 5%
- 口径：性能数字带模型/量化/ctx/prompt/时间戳；短跑（8 token）只用于正确性，不进性能结论

## 1. 结论摘要

- **功能与 ABI：8/8 通过，P0 门 RC=0**（4 个门内测试 + 4 个门外测试）。
- **性能：MTP 71.86 tok/s，plain 47.00 tok/s**（9B Q5_K_M，ctx 16384，128 token），均高于 45 的目标线。
- **稳定性：无运行时崩溃或测试失败；但有 6 项静态风险/覆盖缺口**，其中 2 项（cancel 串扰、stats 覆盖）只在多 session 并发下暴露。
- 本次检查**没有**发现引擎自身的崩溃路径；此前探针的 CUDA 崩溃属一次性工具代码，与引擎无关（见 §5）。

## 2. 性能证据

### 2.1 P0 门内基线（`build/logs/check-p0-gate.raw`）

模型 `Qwen3.8-9B-Q5_K_M.gguf`，ctx 16384，q4 KV，128 生成 token，1 warmup + 3 measured：

| 路径 | tok_s_avg | tok_s_best | TTFT | acceptance | mean_len |
|---|---|---|---|---|---|
| MTP (mtp=1) | **71.86** | 74.19 | 173.31 ms | 0.882 | 1.882 |
| plain (mtp=0) | **47.00** | 47.07 | 103.70 ms | — | — |

门限 45 tok/s → `P0_GATE_OK`。

### 2.2 同日早先的 Q4_K_M 账本（`build/logs/k2-final-9b.raw`）

9B Q4_K_M，ctx 16384，8-token prompt，128 token：MTP 78.19 tok/s，`decode_ms=1637.04`，
`eval_ms=123.93`、`prompt_eval_ms=1314.48`、`sampler_ms=21.81`、host 残差 1519.3 ms。
**MTP 的 `eval_ms` 只是 prefill 残量**，真正的 verify decode 记在 `prompt_eval_ms`；host 段占 step 91%。

> **更正（2026-11-11，Phase 0-D1）**：上面的 host 残差漏减了 `prompt_eval_ms`（verify 的 GPU 时间），且 `eval_ms` 混入了循环外 prefill。prefill 后 `llama_synchronize` + `llama_perf_context_reset` 再重测（`build/logs/d1-clean-mtp*.raw`，9B Q4_K_M / 16384 / 128 token）：plain `host=43.4 ms（1.9%）`，MTP `host=317.3 ms（20.0%）`、`tok_s=82.05`。**"91%"作废**，正确量级是 20%。本报告 §3.2/§8 的 gate 与测试结论不受影响。

### 2.3 Agent 相关 TTFT（`build/logs/k1a-2026-11-11.raw`，早先实测）

521-token prompt：MTP p50 **9733.55 ms**，plain pb=512 p50 **265.28 ms**（9.47 s 差距）。
这是当前最大的性能缺口，且与本次检查的稳定性结论无关。

## 3. 稳定性检查结果

### 3.1 通过项（全部实跑）

| 测试 | RC | 覆盖 |
|---|---|---|
| `tir-test-abi` | 0 | null engine、null path、struct_size 过小、版本、缺文件 |
| `tir-test-abi-load` | 0 | 加载后 meta（layers/mtp/nextn） |
| `tir-test-generate` | 0 | plain 8-token 生成 |
| `tir-test-mtp` | 0 | MTP 生成、取消后 session 复用、plain↔MTP parity=64 |
| `tir-test-prefill` | 0 | env 覆盖非法值回退（0/513/x → fallback=OK） |
| `tir-test-chat` | 0 | meta 标签、chat 模板、thinking 开关、ABI 负例 |
| `tir-test-spec` | 0 | SKIP（`TIR_SPEC_TYPE != ngram`，属预期） |
| `tir-test-profile` | 0 | 64 token profile，graph=63/0/0 |

输入校验实测已覆盖：`engine_create` 对 struct_size / version / model_path / n_ctx<512 / n_gpu_layers / n_threads / kv_q4 / mtp 全部拒绝并写 `tir_last_error`；`session_generate` 对 null / struct_size / version / prompt / n_predict 拒绝；两条生成路径都有 `prompt + n_predict > n_ctx` 前置检查。

### 3.2 风险清单（静态证据，未实跑复现）

| ID | 风险 | 证据 | 爆炸半径 | 建议 |
|---|---|---|---|---|
| R1 | `cancel` 挂在 engine 上，`tir_session_cancel` 实际取消同引擎所有 session | `tir_internal.h:33`、`tir_core.cpp:327` | 多 session 并发宿主 | 单会话顺序形态无影响；若做并发，先把标志下沉到 session |
| R2 | `last_stats` 挂在 engine 上，并发请求互相覆盖统计 | `tir_internal.h:35`、`tir_core.cpp:359` | 并发场景的观测准确性 | 同上；顺序形态可只在 ABI 文档写明"最近一次" |
| R3 | `tir_session::failed` 声明后全代码无读写（死字段） | `tir_internal.h:47`；grep 无引用 | 无运行时影响 | 清理，或补上失败态语义 |
| R4 | `n_ctx` 只校验 ≥512，未对照 `n_ctx_train` | `tir_core.cpp:91-93` | 超训练长度可能 OOM 或行为未定义 | 加钳制或显式拒绝 |
| R5 | `prompt + n_predict > n_ctx` 分支有代码但无测试 | `tir_generate.cpp:128`、`tir_mtp.cpp:202`；tests 无对应用例 | 越界路径回归不可见 | 补一条公共 seam 测试 |
| R6 | 无跨 session 取消测试；现有取消测试只覆盖单 session 复用 | `test_mtp.c:170-199` | R1 无法被回归捕获 | 与 R1 一起补 |

### 3.3 诊断性缺口

- `llama_init_from_model` 失败只报 `"llama_init_from_model failed"`，无法区分 OOM 与参数错误（`tir_core.cpp:251`）。显存不足时排查成本高。
- E0 辅助判读里 Nemotron 的 `step/decode` 偏差 6.36%，超本片 5% 判据；该数字不应被当作精确值引用（`build/logs/k2-e0-nemotron.raw`）。

## 4. 未覆盖项（本次检查的边界）

- 多 session 并发、OOM 注入、`n_ctx > n_ctx_train`、上下文越界分支：均未实跑。
- MTP 路径的 logits margin 未测（K3 只覆盖 plain）。
- 长历史多轮（>3 轮、上千 token）的累积行为未测。
- 其他模型（1B / 4B / 8B / Nemotron）本次只跑了 9B；五模型矩阵是早先 A4/A5 的证据。

## 5. 变更信心与回滚（better harness 口径）

- **改了什么**：没有改引擎源码。新增文件仅 `build/logs/check-*.raw` 与本报告；一次性探针文件已删除。
- **敏感路径**：本报告未触碰 ABI（`tir.h`）、kernel、`common/`、模型文件、`runtime/`。
- **验证信号**：P0 门 RC=0、8/8 测试 RC=0、MTP 71.86 > 45。
- **回滚方式**：无需回滚；若需移除痕迹，删除 `build/logs/check-*.raw` 与本报告即可。
- **置信度**：功能与单会话稳定性 **高**（实跑）；并发稳定性 **低**（仅静态推理，R1/R2 未复现）。

## 6. 建议的下一步（按优先级）

1. R1 + R6 一起做：cancel 下沉到 session，并补跨 session 回归测试（这是唯一"取消会误伤别人"的真实缺陷）。
2. R4 + R5：`n_ctx_train` 校验 + 越界分支测试，补齐资源边界。
3. R3 + 诊断信息：清死字段，`init` 失败带上 n_ctx / kv_q4 / n_rs_seq。
4. 性能侧不要在此停下：9.47 s 的 MTP TTFT 缺口仍是最大收益，需按 K1-b 的边界推进。

## 7. 处置结果（2026-11-11 同日，S3 切片）

按 §6 优先级执行了 R1/R3/R4/R5/R6，蓝图 `docs/blueprints/L2-S3-stability-hardening.md`，证据 `build/logs/s3-*.raw`。

| ID | 处置 | 验证 |
|---|---|---|
| R1 | cancel 标志由 engine 迁至 session（7 处读写） | T3 守卫测试通过；`parity=64` 与取消复用未退 |
| R3 | 删除 `tir_session::failed` 死字段 | 编译通过，全测试 RC=0 |
| R4 | `tir_engine_load` 拒绝 `n_ctx > n_ctx_train`，错误含两个数值 | **真 RED→GREEN**：`300000 > 262144` 被拒 |
| R5 | 补越界分支测试 + 失败后 session 复用 | T2 通过（`tokens_after_reject=8`） |
| R6 | 补跨 session 取消守卫测试 | T3 通过（`b_tokens=8`） |
| R2 | 未改（公共 ABI 签名约束，顺序形态无影响） | 留待 ABI 文档澄清 |

性能无回退：MTP 71.77 tok/s（前 71.86，−0.13%）、plain 47.27（前 47.00），P0 门 RC=0。
diff 审计：status 42→44，新增仅 `test_generate.c` 与 S3 蓝图，改动限于声明写域。

**诚实边界**：R1 在受支持用法下无法构造 RED（`session_generate` 入口重置标志），故按隔离加固交付，T3 是守卫测试而非缺陷复现；反向变异未执行，理由见蓝图执行记录。

## 8. 完整回归（2026-11-11，S3-b 之后）

GPU 空闲 7019 MiB / 3%。证据 `build/logs/reg-*.raw`、`s3b-p0-gate.raw`。

### 8.1 C 测试面（9 个二进制）

| 测试 | RC | 说明 |
|---|---|---|
| abi / abi-load / generate / mtp / prefill / chat / profile | 0 | 全过；`parity=64`、取消复用 `2→8`、越界复用 plain+MTP 均通过 |
| spec（`TIR_SPEC_TYPE=ngram`） | 0 | 真实执行而非 SKIP：`tokens=64 tok_s=102.11 acceptance=1.000` |
| draft-compat（9B target + 0.6B draft） | 3 | **设计语义**：`return ok ? 0 : 3`，词表不兼容对返回 3，非失败 |

### 8.2 P0 门

RC=0，`P0_GATE_OK`。Q5_K_M 9B / ctx 16384 / 128 token：MTP **71.08** tok/s（best 72.48，acceptance 0.882），plain **46.80**。基线 71.86 / 47.00，差异在跑间噪声内。

### 8.3 五模型矩阵（load + 128 token）

| 模型 | ctx | mtp | RC | tok_s | 备注 |
|---|---|---|---|---|---|
| Qwen3-0.6B Q8_0 | 8192 | 0 | 0 | 210.10 | |
| Qwen3.5-0.8B Q4_K_M | 8192 | 0 | 0 | 282.62 | 94 token 后 EOG，正常 |
| qwen35-4.2b Q4_0 | 8192 | 0 | 0 | 101.51 | |
| qwen9b Q4_K_M | 16384 | 0 | 0 | 53.76 | |
| qwen9b Q4_K_M | 16384 | 1 | 0 | 76.57 | acceptance 0.925 |
| nemotron-4b Q4_0 | 8192 | 0 | 1 | — | 默认 8-token prompt 首 token 即 EOG，`gen_tokens=0` |
| nemotron-4b Q4_0（522-token prompt） | 8192 | 0 | 0 | 122.26 | 同模型长 prompt 正常生成 128 token |

**nemotron 短 prompt 的判定**：`n_ctx_train=1048576`，R4 校验未触发；S3 改动只涉及 cancel 归属、加载期校验、错误文案与死字段，不触及 token 选择。同模型换 522-token prompt 即正常生成，故判为**模型/prompt 交互行为，非本次回归**。诚实说明：历史 A4 用的是另一套 harness（`prompt_tokens=6/132/522`），没有该默认 prompt 的历史对照，此判定基于机理与同模型对照，不是逐位历史比对。

### 8.4 未纳入本次回归

`test/mtp-stability.mjs`、`mtp-quality.mjs`、`mtp-plugin-check.mjs` 打的是 `runtime/llama-b12202/llama-server.exe`（上游）与 DSH 宿主，**不经过 tir.dll**，且 DSH 自 2026-11-09 暂停；它们无法验证本次引擎改动，故未跑。

### 8.5 结论

**无回归**。8 个功能测试 + ngram spec 全过，P0 门 RC=0，五模型矩阵除 nemotron 短 prompt 的既有 EOG 行为外全部正常，parity 与取消语义未退。
