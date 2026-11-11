# L2 切片蓝图：A1 MTP 上下文缓存

- 所属 L0：`docs/blueprints/L0-system.md` M2
- 所属 L1：`docs/blueprints/L1-interactive-runtime.md`
- 日期：2026-11-09
- 状态：待执行

## 交付物

同一 `tir_session` 连续两次 MTP generate 复用同一个 `common_speculative` 与 draft context：第二次不需要重建 MTP 上下文，wall time 明显低于第一次，且两次 greedy token 完全一致。

## 切片检查表

| 检查项 | 是 / 否 |
|---|---|
| 预计 ≤30 分钟完成？ | 是（实现约 20 分钟，测试 10 分钟） |
| 修改文件 ≤2 个（测试文件不计）？ | **否：3 个源文件**（header/core/mtp）。生命周期闭环必须跨这三层；若强行压到 2 个会引入已知泄漏或 use-after-free。按协议 §2.5 记录例外。 |
| 是垂直切片（接口 → 逻辑 → 测试走通一条链路）？ | 是 |
| 不按横向阶段切分？ | 是 |
| 有独立可运行验收？ | 是 |
| 写入域与其他并行任务不重叠？ | 是（P1 当前只有此切片） |

## 涉及文件

- 写：
  - `src/llama.cpp-fork/src/tir-api/tir_internal.h`
  - `src/llama.cpp-fork/src/tir-api/tir_core.cpp`
  - `src/llama.cpp-fork/src/tir-api/tir_mtp.cpp`
  - `src/llama.cpp-fork/tests/tir-api/test_mtp.c`（测试，不计入 2 文件）
  - `src/llama.cpp-fork/src/tir-api/CMakeLists.txt`（仅在新测试目标需要时）
- 读：`tir.h`、`tir_generate.cpp`、`llama.cpp-fork/common/speculative.h`、`examples/speculative-simple/speculative-simple.cpp`
- 禁止触碰：`tir.h` 公共 ABI、`llama.cpp`/`ggml`/`common` 核心、`runtime/`、模型文件、master 分支

## 设计

1. `tir_internal.h`：
   - `struct tir_mtp_state;`
   - `tir_session` 追加 `std::unique_ptr<tir_mtp_state> mtp;`
   - 声明 `~tir_session();`（定义放 `tir_mtp.cpp`，使 `tir_core.cpp` 不需要知道 common 类型）。
2. `tir_mtp.cpp`：
   - 定义 `struct tir_mtp_state { common_speculative_init_result_ptr init; common_speculative * spec; ~tir_mtp_state(); }`。
   - `ensure_mtp_state(tir_session*)`：首次创建 `common_params`、`common_speculative_init_from_params`、`common_speculative_init`，存入 `s->mtp`；后续直接复用。
   - `tir_generate_mtp` 使用缓存中的 `spec`/`ctx_dft`，每次请求仍执行 `llama_memory_clear` + `common_speculative_begin` 重置序列状态。
   - `tir_session::~tir_session()`：释放 spec（在 target/draft context 仍存活时）。
3. `tir_core.cpp`：
   - `tir_session_destroy` 调整顺序：先 `delete session`（触发 spec 释放），再 `llama_sampler_free` / `llama_free`，避免 spec 析构访问已释放 context。
4. `test_mtp.c`：
   - 同一 session 连续两次 MTP generate（同 prompt、8 tokens、greedy）；
   - 记录两次 wall time（`std::chrono`，测试里用 `clock_gettime`/`QueryPerformanceCounter` 或 C `clock()` 足够）；
   - 断言两次 token IDs 完全一致；
   - 断言 `warm_ms + 15 < cold_ms`（首次包含 MTP 上下文创建；若该阈值在实测中过紧，允许改为 `warm_ms < cold_ms` 并记录）。
   - 测试顶部继续设置 `LLAMA_DISK_STREAM_MB=0`。

## 验收标准（≥2 条，可运行）

1. `build\build-tir-api.bat` → `BUILD_OK`。
2. `build\tir-api\bin\tir-test-mtp.exe` → `test_mtp: OK plain=8 mtp=8 parity=8`，并打印 `cache cold_ms=... warm_ms=...`，`warm_ms + 15 < cold_ms`。
3. `build\run-p0-gate.bat` → 4/4 测试、`P0_GATE_OK`，无回归。

## 前置条件

- [x] 项目已 git 化，`git status --porcelain` 为空（P1 分支起点）。
- [x] `tir.h`、`tir.stats` 契约已冻结。
- [x] P0 已完成（c9a5043..9a70d1d）。

## 停止条件

- 复用 context 导致 plain/MTP token 不一致且无法通过 `common_speculative_begin`/memory clear 修复；
- 需要改 `tir.h` 或 llama.cpp 核心；
- 同一次失败连续 2 次；
- 改动超出上述写域。

## 执行记录

| 时间 | 事件 | 证据 |
|---|---|---|
| | | |
