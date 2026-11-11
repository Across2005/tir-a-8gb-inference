# L2 切片蓝图：A2 plain 路径分块 prefill

- 所属 L0：`docs/blueprints/L0-system.md` M2
- 所属 L1：`docs/blueprints/L1-interactive-runtime.md`
- 日期：2026-11-09
- 状态：完成（`8c963b9`；Minor：独立 P1 gate 脚本待建）

## 交付物

`tir_generate_plain` 的 prompt prefill 从“每 token 一次 decode”改为“2 token 一批 decode”；在 qwen9b hybrid 上保持 greedy token 完全一致，并让长 prompt（约 512 token）的 TTFT 明显低于逐 token 基线。

## 切片检查表

| 检查项 | 是 / 否 |
|---|---|
| 预计 ≤30 分钟完成？ | 是（实现 15 分钟，测试 15 分钟） |
| 修改文件 ≤2 个（测试文件不计）？ | 是：`tir_generate.cpp` + `src/tir-api/CMakeLists.txt`（测试目标） |
| 是垂直切片？ | 是（prefill → 采样 → 回调走通） |
| 不按横向阶段切分？ | 是 |
| 有独立可运行验收？ | 是 |
| 写入域与其他并行任务不重叠？ | 是（P1 当前只有此切片） |

## 涉及文件

- 写：
  - `src/llama.cpp-fork/src/tir-api/tir_generate.cpp`
  - `src/llama.cpp-fork/tests/tir-api/test_prefill.c`
  - `src/llama.cpp-fork/src/tir-api/CMakeLists.txt`（仅新增测试目标）
- 读：`tir.h`、`tir_internal.h`、`tir_mtp.cpp`（只读，确认 MTP 仍走原 prefill）
- 禁止触碰：`tir.h` 公共 ABI、`tir_mtp.cpp`、`tir_core.cpp`、`llama.cpp`/`ggml`/`common`、`runtime/`、模型文件、master。

## 设计

1. `tir_generate_plain`：
   - 新增内部 `prefill_batch_size(s)`：先按 `general.architecture` 白名单取默认（`qwen35` → 2，其它/未知 → 1）；`TIR_PREFILL_BATCH` 为 1..8 时覆盖，空/不可解析/越界时回落白名单。
   - 用 `llama_batch_init(pb, 0, 1)`；每批填 `token/pos/n_seq_id/seq_id/logits`，只在本批最后一个 token 置 `logits=1`；`llama_decode(ctx, batch)`。
   - 逐批检查 `engine->cancel`；最后一批结束后 `llama_sampler_sample`。
   - 任何 `llama_decode` 失败 → `TIR_E_INTERNAL`；batch 释放走 RAII/统一出口。
   - `TIR_PREFILL_BATCH=1` 必须保持 P0 的逐 token 行为（回退路径）。
2. 测试 `test_prefill.c`：
   - 设置 `LLAMA_DISK_STREAM_MB=0`；`TIR_TEST_MODEL` 缺失时 SKIP。
   - 构造 3 个 prompt：约 5、128、512 token（重复短句，打印实际 `stats.prompt_tokens`）。
   - 对每个 prompt：先用 `TIR_PREFILL_BATCH=2` 跑一次不计时的 warmup，再交替 pb=1/pb=2 各 3 次，各取 `ttft_ms` 中位数。
   - 断言所有 run 的 IDs 与 token 数完全一致；打印 `prompt_tokens / seq_runs / batch_runs / seq_med / batch_med`。
   - 对约 512 token 的 prompt，断言 `batch_med < seq_med`（若没有收益，记录数字并报告，不伪造）。
   - 追加 plain 取消/复用用例：回调在第 2 个 token 返回 1 → `TIR_E_CANCELLED`；同一 session 再正常生成 8 token → `TIR_OK`。
   - 每个 case 使用独立 session 或同一 session + memory clear；测试自行清理。

## 验收标准（≥2 条，可运行）

1. `build\build-tir-api.bat` → `BUILD_OK`。
2. `build\tir-api\bin\tir-test-prefill.exe` → 三个 prompt 均 `parity=OK`，并打印 `seq_med/batch_med`；512 档 `batch_med < seq_med`；取消/复用用例 `status=` 正确。
3. `build\run-p0-gate.bat` → 4/4 测试、`P0_GATE_OK`，无回归。

## 前置条件

- [x] A1 已完成（`8ff0181`）。
- [x] `tir.h` 冻结。
- [x] 工作区干净。

## 停止条件

- 2-token 批在 qwen9b 上 greedy token 不一致且无法修复 → 停止，回退 `TIR_PREFILL_BATCH=1`，报告 `BLOCKED`。
- 512 档 TTFT 无改善 → 记录数字，停止本切片，不进入更大 batch。
- 需要改 `tir.h`/核心/写域外文件 → 停止。
- 同一失败连续 2 次 → 停止。

## 执行记录

| 时间 | 事件 | 证据 |
|---|---|---|
| 2026-11-09 | 实现 + 修复 | 521 token: 9260→4852 ms（1.91x），parity OK；cancel/reuse OK；P0 gate 4/4 | `tir-test-prefill`；`build/logs/a2-*` |

Minor（parked）：`build/run-p1-gate.bat` 未建；当前 P1 门禁 = P0 gate + prefill test。
