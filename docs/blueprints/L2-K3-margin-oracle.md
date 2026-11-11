# L2 切片蓝图：K3 greedy margin 观测 oracle

- 所属 L0：`docs/blueprints/L0-system.md` M2 Generation
- 所属 L1：`docs/blueprints/L1-interactive-runtime.md`
- 日期：2026-11-11
- 状态：已执行（2026-11-11；判读结论见执行记录：长 prompt 可行，默认短 prompt 触发停止条件③）
- 前置：脑暴 `docs/brainstorm/2026-11-10-next-steps.md` §0–§4；K1-a 观测完成（`build/logs/k1a-2026-11-11.raw` SUMMARY）
- 论证不再重复：本文件只回指脑暴小节与源码行。

## 交付物

`TIR_MARGIN_DEBUG=1` 下 plain 路径逐 token 输出 greedy top1−top2 margin，给出 128-token 实测 min-margin 与候选翻转点，一句话判定 K1 的 0.13 位移预算能否覆盖。env 关闭时零开销、零输出；不改 token 选择、不改 ABI。

## 依据（逐条回指）

| 来源 | 内容 | 位置 |
|---|---|---|
| 脑暴 §1.5 问 1 | 逐位 parity 先交易，位移是 ~0.13 固定量、只翻近 tie | `docs/brainstorm/2026-11-10-next-steps.md` §1.5 问 1 |
| 脑暴 §1.5 问 3 | 不碰 kernel 的调度层实验原则 | 同文件 §1.5 问 3 |
| 脑暴 §2 K3 | 七项展开、输出格式与命令 | 同文件 §2 K3 |
| 脑暴 §3 K3 | 判死条件 | 同文件 §3 |
| 0.13 位移 | 3+ 行 verify 位移 ~0.13；1–2 行与逐 token 逐位一致 | `src/llama.cpp-fork/src/tir-api/tir_internal.h:12-19` |
| 采样点 | plain 循环的 `llama_sampler_sample(..., -1)` | `src/llama.cpp-fork/src/tir-api/tir_generate.cpp:167-171` |
| 计时变量位置 | `gen/step_us/detok_us/callback_us` 起点 | `tir_generate.cpp:161-166` |
| ABI 追加规则 | 若要进 JSON，只能末尾追加并先改 ABI.md | `docs/blueprints/L1-interactive-runtime.md:42`；`L2-C0:98-101` |

## 不解决（残余风险）

- **MTP verify 侧 margin**：需动 `common/sampling` / `common_speculative`，标「破边界研究项」，不入本片（脑暴 §2 K3 第 4 条）。
- 任何 token 序列、采样参数或回调行为变更：本片 stderr-only。
- 预算不可行时的生产策略回退：只回填 K1 停止条件①，不在本片改默认值。
- 把 margin 写进 `tir_stats` / JSON：不在本片；若未来要做，按 L1:42 末尾追加并先改 `ABI.md`。

## 切片检查表

| 检查项 | 是 / 否 |
|---|---|
| 预计 ≤30 分钟完成？ | 是（env 分支 + stderr 打印 + 统计行） |
| 修改源文件 ≤2 个（测试文件不计）？ | 是：仅 `tir_generate.cpp` |
| 是垂直切片？ | 是（一个数字：min-margin vs 0.13） |
| 不按横向阶段切？ | 是（采集、汇总、判读一次交付） |
| 有独立可运行验收？ | 是（输出自带判读行，命令见下） |
| 写入域与其他并行任务不重叠？ | 是（与 K2 的 `bench.c`、`tir_mtp.cpp` 不同文件） |

## 涉及文件

- 写：`src/llama.cpp-fork/src/tir-api/tir_generate.cpp`、`build/logs/k3-*.raw`（只追加）
- 读：`llama.h` 的 logits/sampler API（只读）、`tir_internal.h`（只读）、`tir.h`（只读）、`L2-C0`、`L1-interactive-runtime.md`
- 禁止触碰：`common/sampling.h`、`common_speculative`、kernel、`tir.h`、`tir_mtp.cpp`、`bench.c`、模型文件、`runtime/`、master、push/PR、基线 14 M + 21 ?? 中的任何既有未提交改动

## 设计

1. **env 开关**：在 decode 循环（`tir_generate.cpp:167`）之外读一次 `const bool margin_debug = std::getenv("TIR_MARGIN_DEBUG") != nullptr;`。关闭时循环体零新增工作、零 stderr 输出。
2. **取 margin**：在 `llama_sampler_sample`（`:171`）之前，若 `margin_debug`，读 `const float * logits = llama_get_logits_ith(s->ctx, -1);`，扫全 vocab 求 top1/top2 的 logit 值与 id；`m = top1 − top2`；打印固定格式 `tir-margin: idx=<i> m=<%.4f> flip=<0|1>`。
3. **flip 口径（实现级裁决，回指脑暴 §2 K3 / §3 K3）**：`flip=1` 表示该位置 margin `< 0.13`，即落在实测位移预算内的**候选**翻转点；**真实翻转**由两次运行的 top1 id 序列 diff 定位（per-token 参照 vs `TIR_PREFILL_BATCH=512`），取其打印行的 `m` 与 0.13 比较。若实施中发现需要跨运行状态才能判 flip，按停止条件①上报，不扩写域、不改输出格式。
4. **汇总行**：循环结束打印 `tir-margin: min=<m> (0.13 ref: <k>x)`，`k = min_m / 0.13`。
5. **正交组合**：与 `TIR_PREFILL_BATCH` 正交；同一 env 下加 pb 值即可做对照。不改 `prefill_batch_for_arch` 的默认（`tir_generate.cpp:27-36`）。
6. **不写 `tir_stats`**：stderr-only，`struct_size`/字段顺序不变。

## 验收标准（照抄脑暴 §2 K3）

```bat
build\build-tir-api.bat

rem ① 基线 margin 分布（逐 token prefill 参照）
set TIR_MARGIN_DEBUG=1
build\tir-api\bin\tir-bench.exe <WORKSPACE>\artifacts\qwen9b-Q4_K_M.gguf 16384 0 128 2>&1 | findstr tir-margin
rem 期望：128 行 idx=0..127，末行 tir-margin: min=<m> (0.13 ref: <倍数>x)

rem ② 提批下的对照：翻转点定位
set TIR_PREFILL_BATCH=512
build\tir-api\bin\tir-bench.exe <WORKSPACE>\artifacts\qwen9b-Q4_K_M.gguf 16384 0 128 2>&1 | findstr tir-margin
rem 期望：候选翻转点的 m 被打印；判读=全部实际 flip 的 m < 实测位移 → 预算可行

rem ③ 负向控制：不设 env
build\tir-api\bin\tir-bench.exe <WORKSPACE>\artifacts\qwen9b-Q4_K_M.gguf 16384 0 128 2>&1 | findstr tir-margin
rem 期望：无输出（findstr 不匹配，RC=1 属于预期），证明 env 关闭时零输出
```

判读口径：min-margin 与 0.13 的余量 ≥2×（即 min ≥0.26）且全部实际 flip 的 `m < 0.13` → 预算可行；任一不满足 → 按停止条件③回填 K1。

## 前置条件

- [x] K1-a 观测完成（`k1a-2026-11-11.raw` SUMMARY；MTP p50 9733.55 ms，plain pb=512 p50 265.28 ms）
- [x] P0 门在当前树通过（`reclaim-2026-11-11.raw:13300`）
- [ ] 工作区干净 —— **不成立**：基线 14 M + 21 ??；以基线 hash + `git status --porcelain` 对照，不提交、不 stash。
- [x] 公共 ABI 冻结（`tir.h` 只读）
- [x] 当前 `tir.dll` sha256 `fb320cdc…`（`build/logs/reclaim-2026-11-11.raw`）

## 停止条件

- 读 logits 需要越过写域（例如要改 `common/sampling`）→ 停。
- MTP 侧 margin 需求出现 → 另立「破边界」研究项，不扩本片。
- 输出证明预算不可行（出现实际 flip 的 `m ≥ 0.13`，或 min-margin 与 0.13 之比 <2×）→ 直接回填 K1 停止条件①，不自行改生产默认。
- 同一失败连续 2 次 → 停，写报告，不猜。
- 需要新增第二个源文件 → 停，重新拆解。

## K1-b 立卡条件（本次不写蓝图）

K1-b（默认批 2→512 + MTP prompt 分块）本次只立条件，不展开：

1. **K3 数字在档**：min-margin 与全部实际 flip 的 margin 已测，0.13 预算的可行性有裁决。
2. **K1-a 基线确认收益 >1 s**：已满足。本机实测 MTP 路径 521-token TTFT p50 **9733.55 ms**（`build/logs/k1a-2026-11-11.raw`，3 次 9691.56/9733.55/9745.48）；plain pb=512 p50 **265.28 ms**（261.61/265.28/265.65，对照 `a4-full-9b.raw:12306` 的 266.0 ms，delta −0.27%）→ **潜在收益 9.47 s**；对照 plain 默认 pb=2 的 4799 ms（`a4-full-9b.raw:14357`）→ **4.53 s**。两者均 >1 s。
3. **完整 L2**：五模型矩阵 + 变异 RED/GREEN + 64-token parity 门，不得伪装成即时切片；写域 `tir_generate.cpp` + `tir_mtp.cpp`，不碰 kernel/common/`tir.h`。
4. 立卡前先把 K1-a/K3 证据回填 `L1-interactive-runtime.md` §8 与本文件执行记录。

## 执行记录

| 时间 | 事件 | 证据 |
|---|---|---|
| — | 蓝图建立，未派发 | 本文件；K1-a 基线见 `build/logs/k1a-2026-11-11.raw` |
| 2026-11-11 08:38 | 实现：`tir_generate.cpp:168-187,237-240` 加 `TIR_MARGIN_DEBUG` 分支，逐 token 打印 `tir-margin: idx=… id=… m=… flip=…`，末尾打印 `min=… (0.13 ref: kx)`。**契约修订**：设计 §2 的输出格式不含 top1 id，实测无法跨运行定位真实翻转点，故追加 `id=<top1>` 字段（stderr-only，不触 ABI）。 | `tir_generate.cpp`；本文件设计 §2 |
| 2026-11-11 08:38–08:39 | 基线（pb=2，默认短 prompt 8 token，128 生成）：min=0.0549（0.42×），候选翻转点 idx=41 id=58737；重复进程 margin/ids 逐位一致 | `k3-baseline-id-9b.raw`、`k3-baseline-9b.raw` |
| 2026-11-11 08:40–08:41 | 首次 pb=512 对照得到与 pb=2 **逐位相同**的 margin（0.0549、0 个 id 差异）→ 判为 env 未生效的假阳性，未采纳 | `k3-pb512-9b.raw` 前 4 块 |
| 2026-11-11 08:46–08:47 | 同一命令行内验证 env 已生效后重跑：短 prompt pb=512 min=0.0080（0.06×）；首个分歧 token = idx=41（pb2 id=58737 m=0.0549 flip=1 vs pb512 id=9357 m=0.6136 flip=0），其后 86/128 top1 id 不同 → **1 个真实翻转，参照侧 margin 0.0549 < 0.13** | `k3-repro-short-pb512-9b.raw`、`k3-pb512-9b.raw` 后 4 块 |
| 2026-11-11 08:40–08:41 | 长 prompt（521 token / 2340 B / prompt_tokens=521）：pb=2 min=1.4155（10.89×，TTFT 4224.97 ms），pb=512 min=1.5411（11.85×，TTFT 252.49 ms）；两种设置内部 0/128 id 差异 | `k3-long-pb2-9b.raw`、`k3-long-pb512-9b.raw` |
| 2026-11-11 08:49 | 长 prompt 复跑（第二进程）：ids 0/128、margin 逐位一致 → 可复现 | `k3-repro-long-pb2-9b.raw`、`k3-repro-long-pb512-9b.raw` |
| 2026-11-11 08:49 | 负向控制：不设 env → 0 条 `tir-margin`，bench RC=0 | `k3-negative-9b.txt` |
| 2026-11-11 08:50–08:57 | 更正块 + 最终裁决写入摘要日志 | `k3-summary-9b.raw`（CORRECTION 块） |

**判读结论（裁决）**

- **默认短 prompt：停止条件③成立**——min-margin 与 0.13 之比 0.42×（参照）/0.06×（pb=512）< 2×，且存在 1 个真实翻转（idx=41，参照 side m=0.0549 < 0.13）。→ 回填 K1 停止条件①：**本轮不改任何生产默认值**。
- **长 prompt 可用**：两设置均 ≥10.89× 余量、0 真实翻转 → 批变更若做，只能限定在长 prompt 语境；K1-b 的 L2 必须把「默认短 prompt 64-token parity 门」写成硬门。
- 假阳性教训：`set TIR_PREFILL_BATCH=…` 必须在与 bench 同一命令行内设置并回显验证，否则日志与 pb=2 逐位相同却不自知。
- 阶段记录（含时间线、代码状态、备选与裁决）：`docs/reports/2026-11-11-k2-k3-stage-report.md`。
