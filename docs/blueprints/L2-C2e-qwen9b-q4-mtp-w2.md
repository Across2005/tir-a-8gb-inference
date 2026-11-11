# L2 切片蓝图：qwen9b Q4_K_M + MTP width 2 spike

- 日期：2026-11-09
- 状态：已执行；结论 84.24 t/s（best 85.50），64-token parity 通过，未达 100；报告 `<WORKSPACE>\docs\reports\2026-11-09-qwen9b-q4-mtp-w2.md`
- 上游：`2026-11-09-key-nodes-roofline.md`（最高 ROI 未执行节点）
- 目标：验证 Qwen3.8-9B 在 Q4_K_M + MTP width2 下能否达到 p50 ≥100 t/s，且质量/parity 可接受

## 假设

- Qwen3.8-9B Q5 plain 已贴 HBM 墙（~51 t/s），MTP width1 74.8（mean_len 1.88）。
- Q4 权重约 5.2 GB，腾出 VRAM；width2 理论 mean_len ~2.66，目标 100–130。
- 已知风险：qwen35 hybrid 的 3-row verify 会移动 logits（之前 width2 破坏 greedy 一致）。本 spike 先量化影响，不先做近 tie 回退。

## 实现

1. 量化：`llama-quantize --allow-requantize Qwen3.8-9B-Q5_K_M.gguf Q4_K_M`，保留 nextn/MTP 头。
2. 运行时宽度：新增 `TIR_MTP_N_MAX` 环境变量（1/2/3，默认 1）：
   - `tir_internal.h` 声明 `int32_t tir_mtp_n_max();`
   - `tir_core.cpp`：`n_rs_seq = mtp ? tir_mtp_n_max() : 0`
   - `tir_mtp.cpp`：`draft.n_max = tir_mtp_n_max()`；`n_draft_max = min(..., tir_mtp_n_max())`
   - 默认不设 env = 原 width1，行为不变。
3. 基准：
   - `tir-bench <q4> 16384 1 128`（w1）
   - `TIR_MTP_N_MAX=2 tir-bench <q4> 16384 1 128`（w2）
   - 记录 tok_s/acceptance/mean_len；w1/w2 各 3 runs。
4. Parity：
   - `tir-test-mtp`（或 `tir-test-profile` 加 MTP 模式）64 token，w1 vs w2 与 plain 比较；
   - 记录差异位置、是否只近 tie。

## 验收

1. Q4 文件存在，`tier_gguf.py` 显示 `mtp=true`/nextn>0。
2. w1 能跑，tok_s/acceptance/mean_len 有值，64 token 与 plain 一致。
3. w2 能跑；记录 tok_s、mean_len、acceptance 与 parity 差异。
4. 若 w2 p50 ≥100 且差异可接受 → 进入近 tie 回退/生产化；否则记录失败，不改默认。

## 停止条件

- Q4 量化丢失 MTP 头 → 停止，换量化方式/保留 nextn。
- w2 崩溃/上下文回滚错误 → 停止，回 width1。
- w2 parity 大面积不一致且无法定位 → 记录，回 width1；近 tie 回退另开 L2。

## 写入域

- `src/llama.cpp-fork/src/tir-api/tir_internal.h`
- `src/llama.cpp-fork/src/tir-api/tir_core.cpp`
- `src/llama.cpp-fork/src/tir-api/tir_mtp.cpp`
- `src/llama.cpp-fork/tests/tir-api/`（如需 parity 测试）
- `<WORKSPACE>\artifacts\qwen9b-Q4_K_M.gguf`（量化产物）
- `<WORKSPACE>\docs\reports\2026-11-09-qwen9b-q4-mtp-w2.md`

## 读取域

- `TIR_MTP_N_MAX` 现有用法
- `common/speculative.cpp` 的 MTP 实现
- `test_mtp.c`、`tir-bench.c`
- `test/bench-ceiling.ps1`（只读）

## 禁止

- 改 plain 路径；
- 改 8B/4B/draft/disk；
- 提交/推送。

## 执行记录

| 时间 | 事件 | 证据 |
|---|---|---|
| 2026-11-09 | Q5→Q4_K_M 5501.86 MiB，nextn 保留 | `tier_gguf.py` mtp=true |
| 2026-11-09 | `TIR_MTP_N_MAX` 运行时开关；默认 1 | w1 回归 `test_mtp: OK ... parity=64` |
| 2026-11-09 | w1 75.43 / w2 **84.24** / w3 76.94 | `tir.p0-gate` JSON |
| 2026-11-09 | w2 64-token parity 通过；Q4_0 w2 在 38 失败 | `test_mtp` |
| 2026-11-09 | MTP draft RS 槽尝试更慢，已回退 | w2 84.2→80.3 |
