# B1c 规划器交付报告（DSH）

- 日期：2026-11-09
- 范围：B1c「GGUF 分析器 + TierPlan 规划器」
- 工具：`tir-b/tools/tier_gguf.py`、`tir-b/tools/tier_plan.py`
- 契约：输出符合 `tir-b-blueprint/docs/contracts/tier-plan.schema.json`（`tir.plan/v1`）
- 结论：**B1c 完成（Python 参考实现；B1d 运行时读取 plan JSON）**。7/7 决策自测通过；4 个真实模型 plan 已生成。

## 1. 分析器（tier_gguf.py）

- 直接解析 GGUF v3：全量 metadata + 张量表（name/type/dims/offset）；按 ggml type 表算张量字节；按 `blk.N.` 聚合每层 attn/ffn/expert/norm 字节；识别 qwen35 hybrid、gemma4 sliding-window、MoE。
- KV 估算按真实几何：
  - qwen35：`full_attention_interval=4` → 只有 1/4 层 full attention；SSM 状态单独估算（f32，48 MiB 级），报告注明需校准。
  - gemma4：`sliding_window_pattern` 逐层；local 层 `min(ctx,1024)`，global 层随 ctx；`key_length(_swa)` 区分。
  - qwen3：全 attention。
- 输出 `tir.profile/v1`：每层字节、KV 每层字节、SSM 状态、总权重、最大张量、专家数。4 个 profile 在 `tir-b/test/tier-profiles/`。

| 模型 | 权重合计 | 最大张量 | 16k q8 KV | 备注 |
|---|---:|---:|---:|---|
| qwen9b | 6324.36 MiB | output.weight 795.7 MiB | 256 MiB + SSM≈49.5 MiB | hybrid 32 trunk + 1 MTP |
| dsr1-8b | 4789.19 MiB | output.weight 486.86 MiB | 1152 MiB | 36 层全 attention |
| gemma12 | 6637.63 MiB | token_embd 787.5 MiB | 288 MiB | local 层封顶 1024 |
| gemma26 | 13755.36 MiB | token_embd 577.5 MiB | 260 MiB | 128 experts / 8 used |

## 2. 规划器（tier_plan.py）

- 纯函数：profile + resources + policy → plan；同输入字节级一致。
- 决策树：全 GPU(q8) → q4 KV → 降 ctx（16k→8k→4k q4）→ 按层从后往前溢出 FFN 到 host（≤0.6 GiB 达标；≤1.0 GiB 且 H2D≥25 给警告）→ RAM 允许则 host（警告）→ REFUSE；MoE 在 B1 直接 REFUSE。
- 输出：`tiers.t0/t1/t2`、`resident`/`stream_host`、`expected_tok_s`、`warnings`、`why`、`feasible`、`backend`。
- 自测 7/7：全 GPU 9B、紧 9B 溢出、12B 降 q4、26B REFUSE、hybrid KV、sliding KV、确定性；日志 `tir-b/test/tier-plan-selftest.txt`。

## 3. 本机真实 plan（2026-11-09 09:3x，free VRAM 6629 MiB，RAM free 6443 MiB，H2D 20.96 GB/s）

| 模型 | backend | ctx | KV | t0/t1 MiB | 预估 tok/s | 结论 |
|---|---|---|---:|---:|---:|---|
| qwen9b | host | 16384 | q4_0 | 5142 / 1182 | 13.5–23.8 | 溢出 8 层 FFN（1.15 GiB/token），低于 0.6 预算，**当前显存下 20 tok/s 不保** |
| dsr1-8b | cuda | 8192 | q4_0 | 4789 / 0 | 18–28 | 16k q8/q4 超出默认 reserve；8k q4 全 GPU |
| gemma12 | host | 16384 | q4_0 | 5045 / 1592 | 10.6–19.1 | 溢出 13 层 FFN（1.55 GiB），低于 18 目标 |
| gemma26 | refuse | — | — | — | — | MoE，B1 不做 |

- 用 `--reserve-mib 512` 时 dsr1-8b **16k q4 全 GPU** 可容纳（4789+576+512+512=6389 ≤ 6629）。
- 结论与任务书一致：**qwen9b 16k 在当前 free VRAM 下无法全 GPU**；B1 机制验收先用 dsr1-8b（16k q4 或 8k q8），qwen9b 只能溢出/降级，达标前不虚报。
- plan 文件：`tir-b/test/tier-plans/*.json`。

## 4. 架构说明与后续

- 本机 B1 采用「离线分析/规划 → TierPlan JSON → 运行时消费」：B1d 的 `tier::commit()` 读 plan JSON，不在运行时跑 Python。
- `src/tier-plan.{h,cpp}` 的 C++ 等价实现留到需要在 `tierrun` 内联规划时再补；当前不改契约，plan JSON 已是稳定接口。
- 下一步：B1a `src/tier-memory.{h,cpp}`（T0/T1 arena + 槽/pin/evict）+ 单测；随后 B1d 装载集成（dsr1-8b 16k q4 全 GPU 优先）。

---

## B1c MTP 更新（2026-11-09 09:4x）

- 分析器新增 `mtp`（GGUF `nextn_predict_layers` / `blk.N.nextn.*` 检测）；qwen9b profile `mtp=true`，dsr1/gemma12/gemma26 `mtp=false`。
- 规划器新增 `--mtp auto|on|off`、`--mtp-factor`（默认 2.0）、`--mtp-mean-len`（默认 3.2）：
  - host 溢出按 `bytes_per_token = spill_bytes / mean_len` 计入 PCIe 预算；
  - `expected_tok_s` 乘 MTP 因子；
  - `warnings` 注明 MTP 因子与每 token 字节。
- 新 plan（free 6800 MiB、16k、q4、MTP auto）：
  - qwen9b：host 溢出 7 层 FFN、0.32 GiB/token、**57.2–80 tok/s**（与实测 53–78 吻合）；
  - dsr1：16k q4 全 GPU、18–28 tok/s（无 MTP）；
  - gemma12：host 溢出 1.31 GiB/token、12.2–21.7；gemma26 REFUSE。
- 自测 8/8（新增 MTP 降 bytes/token 用例），日志 `tir-b/test/tier-plan-selftest.txt`。
- plan 文件：`tir-b/test/tier-plans/*-16k-mtp.json`。
