# B1 实施计划（G3）

- 日期：2026-11-09
- 依据：`tir-b-blueprint/docs/blueprints/L2-candidates-b1-b3.md`、`L1-tier-memory.md`、`L1-planner.md`、`L1-loader-kv.md`、`L1-frontends.md`、`L1-verification.md`
- 基线修正（来自 B0）：**正确性基线 = tier 模式全 GPU**（安装回调、关融合/graph），不再与 stock 逐 token 对比；若产品要求 stock 等价，另开“融合等价”切片。

## 0. 当前事实

- B0 已 GO（机制）：回调计数 30,756=30,756；27 MiB zero-copy 与 486.86 MiB H2D 均与 tier 基线 32/32 一致；H2D 256 MiB 20.96 GB/s、512 MiB 18.80 GB/s。
- **MTP 实测（Qoder，2026-11-09）**：qwen9b 自带 `blk.32.nextn.*`，`--spec-type draft-mtp` 无需额外 draft；2k q8 80.31 vs 37.08 t/s（2.17x），16k q4 53.12/78.05 vs 47.90；接受率 72–75%、3.16–3.24 token/步。**原 20 tok/s 目标作废**。
- 模型：dsr1-8b 4.79 GiB（36 层全 attention，16k q8 KV ≈1.15 GiB）；qwen9b 6.19 GiB（33 层 hybrid，16k q8 KV ≈256 MiB）；gemma12 6.48 GiB 权重。
- 显存：free 约 6.2–6.9 GiB；qwen9b 16k q4 靠 WDDM overcommit 可跑，q8 不可全 GPU。

## 1. 切片顺序（每步独立验收）

### B1c 规划器（先做，纯逻辑，不等 GPU）
- 写：`tools/tier_gguf.py`、`src/tier-plan.{h,cpp}`
- 读：GGUF metadata（head_count_kv 可能是数组；qwen35 hybrid；gemma4 sliding+global；MoE）
- 输出：`tir.plan/v1` JSON（schema 见 `docs/contracts/tier-plan.schema.json`），支持：
  - 全 GPU / q4 KV / 降 ctx / FFN host 溢出 / REFUSE 决策
  - `expected_tok_s` 区间、`warnings`、`why`
- 单测：7 个决策用例 + 确定性（同输入字节级相同）。
- 验收：`tierrun --plan-only --profile profile.json --ctx 16384 --kv q8_0` 10 s 内出 plan；不加载模型。

### B1a T0/T1 arena 与槽管理
- 写：`src/tier-memory.{h,cpp}`、`src/CMakeLists.txt`
- 内容：T0 VRAM/T1 pinned host；首次适配 + 2 MiB 对齐 + 合并；pin/evict；状态机 ABSENT/LOADING/RESIDENT/FAILED；常驻张量不参与 LRU；失败显式中止。
- 单测：分配/释放/合并/淘汰/并发 pin/失败中止；1 GiB T0 + 2 GiB T1 分配。

### B1b 异步 H2D + 预取
- 写：`src/tier-memory.cpp`
- 内容：2 个 copy stream + 每槽 event；`ensure()` 只入队不阻塞；计算流 `cudaStreamWaitEvent`；`done` 后事件回收；层包预取（不 pin）。
- 单测/集成：32 MB <5 ms、256 MB <15 ms（在完整路径复现 B0 数字）；无半拷贝；预取不改变 token。
- 约束：B1 单 compute stream；B0 的同步 memcpy 换成异步后必须复测 token 一致。

### B1d 装载集成与延迟 T0
- 写：`src/llama-model.cpp`（`TIR_MODE=tier`、no_alloc、CUDA dummy buffer、注册、context 后 `tier::commit()`、析构 `shutdown()`）、`src/llama.cpp`（commit 挂点）
- 内容：`TIR_MODE` 与 `LLAMA_DISK_STREAM_MB` 互斥；`params.n_gpu_layers` 必须全部层；非 CUDA 主后端拒绝；`params.no_alloc` 保持 false；plan 不可行装载失败。
- 验收：加载 dsr1-8b 16k，日志有 plan/T0/T1/KV，token 正常；连续加载两个模型（`--fit`）不串状态。

### B1e tierrun/tierc + B1 达标
- 写：`examples/tierrun/**`、`examples/tierc/**`、`src/tier-stats.*`、`examples/CMakeLists.txt`
- 验收（MTP 修正后）：
  1. dsr1-8b 16k q4（无 MTP）：机制通过，token 与 tier 基线一致；记录 tok/s。
  2. gemma12 16k q4：≥18 tok/s（显存允许时）。
  3. **qwen9b 16k q4 + MTP：≥50 tok/s**（prebuilt server 已达到 53–78）；若走 tier host 溢出，**tier + MTP ≥30 tok/s** 为最低门。
  4. VRAM 余量 ≥300 MiB；30 分钟无泄漏。
- planner：`expected_tok_s` 乘 MTP 因子（默认 2.0），host 溢出按 `bytes_per_token = spill_bytes / mean_len(3.2)` 估算；MTP 模型自动识别（GGUF nextn）。

## 2. 关键实现点（来自 L1）

- T1：`cudaHostAlloc(Portable|Mapped)`；默认路径 H2D 暂存，零拷贝只作小张量选项。
- 槽复用：只复用 `cudaEventQuery == cudaSuccess` 的槽；`done=true` 只表示入队。
- 失败：`tier::set_fail` + decode 返回非 0，禁止继续算垃圾。
- KV：不硬编码公式；用启动日志 `KV self size` 校准；先降 ctx 再考虑 host spill。
- 统计：`tier_stats` 字段只追加；`h2d_us` 由事件测得。

## 3. 风险与停止条件

- 异步回收错误 → 间歇乱码/崩溃：B0 必须用 64+ token greedy 对比；失败即停。
- T0 延迟分配挂点不稳：找不到稳定挂点 → 停止并报告。
- qwen9b 16k 超出显存：记录实际 free/用量，先 dsr1 机制，不虚报 ≥20。
- 与 Qoder 并发写同一文件：B1 只由 DSH 写 `src/tier-*`、`examples/tierrun|tierc`；共享文件（llama-model.cpp/CMakeLists）改前记录 diff。
- 写域：`tir-b/**`、`packages/dsh-local-model/**`、`DSH-HANDOFF/**`、日志目录；不改 `_source`/计划目录/DSH 核心。

## 4. 交付

- 每步：代码 + 单测 + 实际命令输出。
- B1 完成或被阻塞：`tir-b/test/tier-b1-report.md` + `DSH-HANDOFF/STATUS.md` 更新 + `git diff --stat`。
