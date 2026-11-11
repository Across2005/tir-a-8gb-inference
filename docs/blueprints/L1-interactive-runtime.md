# L1 模块蓝图：交互运行时（M2 Generation）

- 日期：2026-11-09
- 父节点：`docs/blueprints/L0-system.md` M2
- 状态：P0 基线完成；P1-A 切片待执行
- 设计权威：`<WORKSPACE>\docs\superpowers\specs\2026-11-09-local-inference-engine-design.md` §3–§6

## 1. 模块职责

把“一次请求”变成“一段 token 流”，并在单用户交互场景下最小化：

- 首 token 延迟（TTFT）；
- 重复请求的上下文重建；
- MTP 上下文的重复创建；
- 采样/回调/取消的边界开销。

P1 只做 **RESIDENT dense**；TIERED 与 MoE 不在本模块的 P1 范围。

## 2. 对外接口（冻结）

公共 ABI 不变（`tir.h`）：

```c
tir_session * tir_session_create(tir_engine *);
tir_status    tir_session_generate(tir_session *, const tir_request *,
                                   const tir_callbacks *, void *);
void          tir_session_cancel(tir_session *);
void          tir_session_destroy(tir_session *);
```

内部入口（`tir_internal.h`，P0 已冻结签名）：

```c
extern "C" tir_status tir_generate_plain(tir_session *, const tir_request *,
                                         const tir_callbacks *, void *);
extern "C" tir_status tir_generate_mtp(tir_session *, const tir_request *,
                                       const tir_callbacks *, void *);
```

**不得单方修改**：`tir.h`、上述内部签名、`tir_stats` 字段顺序。

C0 允许在 `tir_stats` **末尾追加** 性能字段（`eval_ms`、`step_us`、`graph_*` 等）；旧调用者按 `struct_size` 只拿到前缀，字段顺序不变。

## 3. 状态模型

`tir_session` 在 P0 已有：

```cpp
tir_engine * engine;
llama_context * ctx;
llama_sampler * smpl;
int32_t n_past;
bool failed;
```

P1 允许追加（不改变公共 ABI）：

| 字段 | 用途 | 生命周期 |
|---|---|---|
| `mtp_state * mtp` | 缓存的 MTP spec + draft context | 首次 MTP generate 惰性创建；session 销毁时释放 |
| `prompt_tokens` / `prompt_len` | 多轮前缀复用（A3） | 每次成功 generate 后更新 |
| `prefill_policy` | 分块 prefill 开关/桶（A2） | 创建时由模型能力决定 |

## 4. P1 切片路线（按顺序）

| 切片 | 内容 | 预期收益 | 风险 |
|---|---|---|---|
| **A1 MTP 上下文缓存** | 同一 session 复用 `common_speculative` + draft context | 重复请求 TTFT −30–80 ms；减少分配抖动 | 复用残留状态导致 token 不一致 |
| **A2 分块 prefill** | prompt 用 batch/ubatch 处理；带 parity 门 | 长 prompt TTFT 显著下降 | hybrid chunked kernel logits 偏移；必须自动回退 |
| **A3 前缀/KV 复用** | 多轮共享前缀，trim 到公共前缀后只 prefill 增量 | 多轮聊天 TTFT −50% 以上 | hybrid SSM 回滚；前缀匹配边界 |
| **A4 真实采样** | temperature/top-k/top-p/seed；plain 与 MTP 统一 sampler | 产品可用性 | MTP 接受率与采样一致性 |

每个切片独立 L2、独立 gate；A1 不依赖 A2–A4。

## 5. 写入域（P1）

- 可写：`src/llama.cpp-fork/src/tir-api/tir_internal.h`、`tir_generate.cpp`、`tir_mtp.cpp`、`tir_core.cpp`（仅 session 状态/生命周期）、`tests/tir-api/**`、`build/run-p1-gate.bat`。
- 只读：`tir.h`、`llama.cpp`/`ggml`/`common`、`docs/tir-api/ABI.md`（需变更时先改文档并记录）。
- 禁止：TIERED/MoE 代码、模型文件、`runtime/`、master 分支、push/PR。

## 6. 模块级验收

1. `build\build-tir-api.bat` → `BUILD_OK`。
2. `build\run-p0-gate.bat` → 4/4 测试、`P0_GATE_OK`（不得回归）。
3. `build\run-p1-gate.bat` → A1 warm TTFT < cold TTFT 且 token 一致；后续切片追加各自门。

## 7. 停止条件

- 复用 MTP 上下文导致 plain/MTP token 不一致且无法定位；
- 需要改 `tir.h` 或 llama.cpp 核心；
- 分块 prefill 在任何模型上无法通过 parity 且无法自动回退；
- 同一失败连续 2 次；
- 范围超过 L2 写清单。

## 8. 执行记录

| 时间 | 切片 | 结果 | 证据 |
|---|---|---|---|
| 2026-11-09 | P0 基线 | 完成 | `test/tir-api/p0-gate.json` |
| 2026-11-09 | A1 MTP 上下文缓存 | 完成；cold/warm 328/204 ms，token 一致 | `tir-a-p1` 8ff0181；`test_mtp` cache 行 |
| 2026-11-09 | A2 plain 分块 prefill | 完成；521 token TTFT 9260→4852 ms（1.91x），parity OK；仅 qwen35 默认 2，未知 arch 回退 1 | `tir-a-p1` 8c963b9；`tir-test-prefill` |
| 2026-11-09 | S1 小模型兼容门禁 | 7 个 1.1B–9B load+128-token 全 OK；compat_check 11→22 测试；Q5_0 白名单有实测证据 | `tir-a-p1` 57490bf；`test/compat/results.json` |
| 2026-11-09 | S2 chat template | `tir_model_meta` + `tir_chat_apply`；qwen9b chat prompt 110 B；22/22 compat + P0 gate 4/4 | `tir-a-p1` 4434fd2；`tir-test-chat` |
| 2026-11-09 | S2c 思考开关 | `tir_chat_apply_ex` + `enable_thinking`；qwen9b on 110 B / off 121 B（closed empty block）；22/22 + P0 gate 4/4 | `tir-a-s2c` 63b8213；`tir-test-chat` |
| 2026-11-09 | S2d-0 reasoning tags | meta 暴露 `<think>`/`["
</think>","</think>","<tool_call>"]`/stops/supports | `tir-a-s2d` b969f9f |
| 2026-11-09 | S2d-1 流式过滤器 | ReasoningFilter：safe-prefix、tool call、stops 全局；14 测试 | `tir-a-s2d` 857c622；`tir-test-stream` |
| 2026-11-10 | A4 prefill 默认批 512（prefill 系列，非本表 §4 的 A4 真实采样）| 完成；白名单 `llama/qwen3/qwen35/nemotron_h → 512`（取代 A2 行"仅 qwen35 默认 2"），`nextn>0` 仍 2；五模型 520 token 默认路径 parity OK，1B/4.2B/Nemotron/8B 收益 29.4–31.8×，9B(MTP) 1.91× 且 `tir-test-mtp parity=64` | `L2-A4-prefill-default-512.md`；`build/logs/a4-full-*.raw`、`a4-reg-mtp-9b-final.raw` |
| 2026-11-10 | A5 A4 门禁加固 | 完成；最近邻判据 `def_err < 0.5*seq_err` + oracle `"mtp":true`；9B `expect=2 def_err=34.2 seq_err=4505.1 match=OK`；五模型全 RC=0；`tir-test-mtp parity=64`；`abi-load` 实跑 `layers=24 ... mtp=0`；1B 变异未单跑（会先被 profile 下界拦住） | `L2-A5-a4-gate-hardening.md`；`build/logs/a5-final-*.raw`、`a5-reg-*.raw`、`a5-abi-load.raw` |
