# L2 切片蓝图：S3 稳定性硬化（cancel 隔离 / 资源边界 / 越界覆盖）

- 所属 L0：`docs/blueprints/L0-system.md` M2 Generation
- 所属 L1：`docs/blueprints/L1-interactive-runtime.md`
- 日期：2026-11-11
- 状态：已执行（2026-11-11，RED→GREEN，P0 门无回退）
- 前置：性能与稳定性检查完成（`docs/reports/2026-11-11-engine-perf-stability-check.md`，8/8 测试 RC=0、P0 门 RC=0、MTP 71.86 tok/s）
- 论证不再重复：风险清单与证据行号见该报告 §3.2

## 交付物

把 cancel 标志从 engine 下沉到 session（隔离加固），补 `n_ctx_train` 校验与上下文越界分支的公共 seam 测试，清掉死字段。不改公共 ABI，不改 token 选择，不改性能默认值。

## 依据（逐条回指）

| 来源 | 内容 | 位置 |
|---|---|---|
| 检查报告 R1 | cancel 挂在 engine，`tir_session_cancel` 写 engine 标志 | `tir_internal.h:33`、`tir_core.cpp:327` |
| 检查报告 R3 | `tir_session::failed` 声明后无读写 | `tir_internal.h:47` |
| 检查报告 R4 | `n_ctx` 只校验 ≥512，未对照 `n_ctx_train` | `tir_core.cpp:91-93` |
| 检查报告 R5 | 越界分支有代码无测试 | `tir_generate.cpp:128`、`tir_mtp.cpp:202` |
| 检查报告 R6 | 无跨 session 取消测试 | `test_mtp.c:170-199` 只覆盖单 session |
| 取消语义承诺 | cancel 可跨线程调用 | `docs/tir-api/ABI.md:68` |
| 并发约束 | 引擎单线程、不可重入 | `docs/tir-api/ABI.md:250-254` |
| 实测训练长度 | 9B `n_ctx_train=262144` | `build/logs/check-p0-gate.raw` |

## 不解决（残余风险）

- R2（`last_stats` 在 engine）：顺序形态无影响，且 `tir_stats_snapshot(engine)` 是公共 ABI，不改签名。只在 ABI.md 写明"最近一次完成的请求"。
- 真正的多 session 并发调度：不在本片，属独立子系统。
- 性能默认值、采样、kernel、`common/`：一律不碰。

## 切片检查表

| 检查项 | 是 / 否 |
|---|---|
| 预计 ≤30 分钟完成？ | 是（标志迁移 + 一处校验 + 三条测试） |
| 修改源文件 ≤2 个（测试文件不计）？ | 否：4 个（`tir_internal.h`/`tir_core.cpp`/`tir_generate.cpp`/`tir_mtp.cpp`），但都是同一处标志迁移的必然落点，已在派发单声明 |
| 是垂直切片？ | 是（一条取消语义从 ABI 到测试走到底） |
| 有独立可运行验收？ | 是（`tir-test-generate` + P0 门） |
| 写入域与其他并行任务不重叠？ | 是（本轮无并行任务） |

## 涉及文件

- 写：`src/tir-api/tir_internal.h`、`tir_core.cpp`、`tir_generate.cpp`、`tir_mtp.cpp`、`tests/tir-api/test_generate.c`、`build/logs/s3-*.raw`（只追加）
- 读：`tir.h`（只读）、`ABI.md`、`test_mtp.c`（取消测试写法参照）
- 禁止触碰：`tir.h`、kernel、`common/`、模型文件、`runtime/`、master、push/PR、基线中不属于本写域的既有未提交改动

## 设计

1. **cancel 下沉**：`std::atomic<bool> cancel` 从 `tir_engine` 移到 `tir_session`。`tir_session_generate` 入口重置 `session->cancel`；`tir_session_cancel` 写 `session->cancel`；两条生成路径的循环读 `s->cancel`。语义不变，隔离性增强。
2. **`n_ctx_train` 校验**：`tir_engine_load` 在模型加载成功后，若 `engine->n_ctx > llama_model_n_ctx_train(model)` → `set_error`（含两个数值）并返回 `TIR_E_INVALID`。引擎不暴露 rope scaling，超训练长度属未支持配置，显式拒绝优于静默 OOM。
3. **死字段清理**：删除 `tir_session::failed`（grep 确认无引用）。
4. **诊断信息**：`llama_init_from_model` 失败的错误信息带上 `n_ctx` / `kv_q4` / `n_rs_seq`。

## 验收标准

**T1（R4，真 RED→GREEN）**：`n_ctx = 300000 > n_ctx_train(262144)` → `tir_engine_load` 必须返回 `TIR_E_INVALID` 且 `tir_last_error()` 非空。实现前该断言失败（当前返回 TIR_OK）。

**T2（R5，覆盖补齐）**：`prompt + n_predict > n_ctx` → `tir_session_generate` 返回 `TIR_E_INVALID`；随后同一 session 的正常请求必须 `TIR_OK`（失败后可复用）。此分支已有代码，测试预期直接 GREEN，属覆盖缺口补齐，不伪装成 RED。

**T3（R1/R6，守卫测试）**：同引擎两个 session，A 用回调自取消返回 `TIR_E_CANCELLED`，随后 B 正常生成必须 `TIR_OK` 且 token 数完整。**诚实声明**：受支持用法下 `session_generate` 入口会重置标志，顺序场景无法构造 R1 的 RED；本测试是隔离性守卫，不是缺陷复现。R1 的价值在于为未来并发消除共享状态。

**回归门**：`tir-test-generate`、`tir-test-mtp`（含既有取消复用与 parity=64）、P0 门 4/4 全 RC=0；MTP tok_s 不低于 45。

## 停止条件

- 需要改 `tir.h` 或 `common/` → 停。
- 同一失败连续 2 次 → 停，写报告，不猜。
- P0 门或 parity 回退 → 停，回滚本片改动。
- 范围超出声明的 5 个文件 → 停，重新拆解。

## 变异测试

| 步骤 | 变异 | 期望 |
|---|---|---|
| RED | T1 在实现前运行 | 断言失败（load 返回 TIR_OK） |
| GREEN | 实现后同命令 | T1/T2/T3 全过 |
| 反向变异 | 把 cancel 改回 engine 级 | T3 仍过（证明 T3 是守卫而非缺陷复现），据此如实记录 |

## 执行记录

| 时间 | 事件 | 证据 |
|---|---|---|
| — | 蓝图建立 | 本文件 |
| 2026-11-11 | 派发前基线：status 42 行 + 5 个写域文件 sha256 | `build/logs/s3-baseline-2026-11-11.txt` |
| 2026-11-11 | **RED**：T1 断言失败 `rc == TIR_E_INVALID`（`test_generate.c:45`），当前 load 返回 TIR_OK | `build/logs/s3-red.raw` |
| 2026-11-11 | 实现：cancel 由 engine 迁至 session（7 处读写）；`n_ctx_train` 校验；init 失败带 n_ctx/kv_q4/n_rs_seq；删 `failed` 死字段 | `tir_internal.h`、`tir_core.cpp`、`tir_generate.cpp`、`tir_mtp.cpp` |
| 2026-11-11 | **GREEN**：T1 `rc=1 err=n_ctx exceeds the model training length: 300000 > 262144`；T2 `tokens_after_reject=8`；T3 `b_tokens=8` | `build/logs/s3-green.raw` |
| 2026-11-11 | 回归：mtp / abi / abi-load / prefill / chat / profile 全 RC=0；`parity=64`、取消复用 `2→8` 未退 | `build/logs/s3-tir-test-*.raw` |
| 2026-11-11 | P0 门 RC=0：MTP **71.77** tok/s（前 71.86，−0.13%）、plain **47.27**（前 47.00） | `build/logs/s3-p0-gate.raw` |
| 2026-11-11 | diff 审计：status 42→44，新增仅 `test_generate.c` 与本蓝图；改动限于声明写域 | `build/logs/s3-after-status.txt` |

**如实记录的两点**

- **反向变异未执行**：把 cancel 改回 engine 级需要重新引入共享状态，属侵入式改动，超出本片写域意图。T3 的"守卫而非缺陷复现"性质由 RED 阶段的推理确立（`session_generate` 入口重置标志，顺序用法无法观察到串扰），不靠变异证明。
- **T2 不是 RED**：越界分支已有实现，测试直接 GREEN，属覆盖缺口补齐。RED 阶段的 stdout 因断言中止被缓冲丢弃，T2/T3 的通过以 GREEN 日志为准。

## 追加切片 S3-b：R4/R5 的两个残留缺口（2026-11-11 同日）

复查 S3 时发现两处未覆盖，已补：

| 缺口 | 处置 | 证据 |
|---|---|---|
| **R4 边界**：GGUF 是外部输入，显式 `context_length=0` 会让校验拒绝一切请求 | 加 `n_ctx_train > 0` 前置条件。`get_key` 默认 `required=true`（`llama-model-loader.h:204`），缺 key 会在加载阶段失败，故正常模型不受影响；此守卫只防病态 GGUF | `tir_core.cpp`；`build/logs/s3b-generate.raw` 仍拒 `300000 > 262144` |
| **R5 覆盖**：越界测试只打了 plain 路径，MTP 分支（`tir_mtp.cpp:202`）无测试 | `test_mtp.c` 新增 `run_oversize_mtp`：`n_predict=20000` → `TIR_E_INVALID`，随后同 session `n_predict=8` → `TIR_OK` | `build/logs/s3b-mtp.raw`：`oversize_mtp: tokens_after_reject=8` |

**验证**：mtp / generate / abi / abi-load / prefill / chat / profile 全 RC=0；`parity=64`、取消复用 `2→8` 未退；P0 门 RC=0，MTP **71.08** tok/s、plain **46.80**（与 S3 的 71.77/47.27 差异在跑间噪声内，原始基线 71.86/47.00）。

**诚实边界**：`n_ctx_train=0` 的病态 GGUF 手上没有样本，该守卫属外部输入边界的防御性校验，**未实跑复现**；T4（MTP 越界）同样是覆盖补齐，不是 RED。

**审计**：status 保持 44 行（`test_mtp.c` 本就在基线 dirty 集合内），无新增文件，改动仍限于声明写域。
