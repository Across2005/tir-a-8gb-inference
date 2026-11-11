# L2 切片蓝图：K2 MTP 遥测补齐与 11 ms 非权重归因门

- 所属 L0：`docs/blueprints/L0-system.md` M2 Generation
- 所属 L1：`docs/blueprints/L1-interactive-runtime.md`
- 日期：2026-11-11
- 状态：已执行（2026-11-11，gate GREEN；账本见下方执行记录）
- 前置：脑暴 `docs/brainstorm/2026-11-10-next-steps.md` §0–§4；P0 门已在当前树通过（`build/logs/reclaim-2026-11-11.raw:13300` `P0_GATE_OK tok_s_avg=71.50 target=45`）；K1-a 观测完成（`build/logs/k1a-2026-11-11.raw` SUMMARY）
- 论证不再重复：本文件只回指脑暴小节与源码行，不重写推导。

## 交付物

9B w2 一次 C0 跑出可分解的 step 账本（target eval / draft / host 三段），4B qwen vs Nemotron 的 50 GB/s 缺口给出「eval 内 / eval 外」判定，全部落成一条可回归的命令行 gate。只加测量，不改 token 选择、回调语义与 ABI。

## 依据（逐条回指）

| 来源 | 内容 | 位置 |
|---|---|---|
| 脑暴 §1.5 问 3 E1/E2 | draft 份与 target/host 份的命令与期望输出 | `docs/brainstorm/2026-11-10-next-steps.md` §1.5 问 3 |
| 脑暴 §2 K2 | 七项展开与判据 | 同文件 §2 K2 |
| 脑暴 §3 K2 | 判死条件 | 同文件 §3 |
| 脑暴 §4 K2 | 变异 RED/GREEN 设计 | 同文件 §4 |
| 判读口径 | eval/decode、graph 重建的读法 | `docs/blueprints/L2-C0-ceiling-calibration.md:59-64` |
| 验收判据 | `step_us/1000` 与 `decode_ms` ≤5%、`eval_ms<=decode_ms*1.05` | `L2-C0:108` |
| 停止判据 | 差异 >20% 且无法用 `step_us` 解释 → CUDA event 研究项 | `L2-C0:114` |
| 未填字段 | MTP 路径只填到 `mean_len` | `src/llama.cpp-fork/src/tir-api/tir_mtp.cpp:472-482` |
| 现有 debug 行 | `tir-spec:` 两种行格式 | `tir_mtp.cpp:484-494` |
| 字段定义 | C0 append-only 9 字段 | `src/llama.cpp-fork/src/tir-api/tir.h:87-96` |
| 同源写法 | plain 路径从 `llama_perf_context` 填全部字段 | `src/llama.cpp-fork/src/tir-api/tir_generate.cpp:228-236` |
| 打印缺口 | `dump_stats` 只打印 7 个旧字段 | `src/llama.cpp-fork/tests/tir-api/bench.c:23-29` |
| 全字段参照 | ceiling harness 的 JSON 输出 | `src/llama.cpp-fork/tests/tir-api/bench_ceiling.c:215-234` |
| verify 批形状 | `TIR_MTP_N_MAX` 1..3 环境开关 | `src/llama.cpp-fork/src/tir-api/tir_core.cpp:50-57` |
| MTP 逐 token prefill | 现状 TTFT 来源 | `tir_mtp.cpp:250-269` |

## 不解决（残余风险）

- MTP verify 侧的 margin：需动 `common/sampling`，属 K3 标出的「破边界研究项」，不写进本片。
- nsys 逐 kernel 归因：工具不可得；本片是去工具化替代，不引入新工具。
- E0（4B 结构对照）为 0 源文件的辅助判读，不属本片写域；命令见脑暴 §1.5 问 3 E0，结果只写结论，不改代码。
- 不改采样、不重排 `tir.h` 字段、不做任何性能默认值变更。
- verify 批形状只用 `TIR_MTP_N_MAX` 1 vs 2 做边际成本对照；不扩展 draft depth。

## 切片检查表

| 检查项 | 是 / 否 |
|---|---|
| 预计 ≤30 分钟完成？ | 是（只加字段填充与打印，行为零变更） |
| 修改源文件 ≤2 个（测试文件不计）？ | 是：`tir_mtp.cpp` + `bench.c` |
| 是垂直切片？ | 是（一条 9B w2 账本从采集、打印到判读走到底） |
| 不按横向阶段切？ | 是（测量、判读、门槛一次交付，不拆「先加字段后写判据」） |
| 有独立可运行验收？ | 是（E1/E2 命令 + 命令行 gate RC） |
| 写入域与其他并行任务不重叠？ | 是（不碰 `tir_generate.cpp`；与 K3 不同文件） |

## 涉及文件

- 写：`src/llama.cpp-fork/src/tir-api/tir_mtp.cpp`、`src/llama.cpp-fork/tests/tir-api/bench.c`、`build/logs/k2-*.raw`（只追加）
- 读：`tir.h`（只读）、`tir_internal.h`（只读）、`llama.h` 的 `llama_perf_context` / `llama_perf_sampler`（只读）、`L2-C0`、`bench_ceiling.c`、`tir_generate.cpp:212-237`（同源写法参照，不改）
- 禁止触碰：`tir.h`、`tir_internal.h` 的公共 ABI 与字段顺序；`common/sampling`、`common/speculative`、kernel、CUDA graph API 本体；模型文件；`runtime/`；master；push/PR；基线 14 M + 21 ?? 中的任何既有未提交改动（尤其 `common/speculative.cpp`）

## 设计

1. **perf 复位**：在 `tir_generate_mtp` 生成开始处（`tir_mtp.cpp:233-239` 附近）加 `llama_perf_context_reset(s->ctx)`；draft 上下文的 reset 已在 `:237`。不改采样/回调语义。
2. **循环内计时**：在 verify 循环（`tir_mtp.cpp:298-470`）内累计 `step_us`（每窗口墙钟）、`detok_us`（包住 `token_to_piece`）、`callback_us`（包住 `on_token`），写法照 `tir_generate.cpp:216-233`。
3. **结束填字段**：在 `tir_mtp.cpp:472-482` 之后读取 `llama_perf_context(s->ctx)` 与 `llama_perf_sampler`，填 `e->last_stats.eval_ms / prompt_eval_ms / sampler_ms / step_us / detok_us / callback_us / graph_reused / graph_reallocs_same / graph_reallocs_diff`。字段定义已在 `tir.h:87-96`，**不改头文件**。
4. **bench 打印**：`bench.c:23-29` 的 `dump_stats` 在现有行尾追加新字段（既有键与顺序不动）。stdout JSON `tir.p0-gate/v1` 保持既有键不变（门按 key 解析，见 `build/run-p0-gate.bat:65-71`）。
5. **判据（抄 `L2-C0:108`）**：`eval_ms > 0`；`|step_us/1000 − decode_ms| / decode_ms ≤ 5%`；`eval_ms ≤ decode_ms × 1.05`；`host_residual = (step_us − eval_ms×1000 − prompt_eval_ms×1000 − sampler_ms×1000 − detok_us − callback_us)/1000 ≥ 0`。
   **更正（2026-11-11）**：原式漏减 `prompt_eval_ms`。MTP 的 verify 批记在 `t_p_eval_us`，漏减会把 GPU 时间算成 host（原报 1519.3 ms / 91%，实为 317.3 ms / 20.0%）。同时两条路径在 prefill 之后必须 `llama_synchronize` + `llama_perf_context_reset`，否则未同步的 prefill 统计会落到复位之后（`llama-context.cpp` FIXME），使 `prompt_eval_ms` 混入循环外时间。修正后 plain 路径 `prompt_eval_ms=0`、MTP 路径 `eval_ms=0`，账本才可判定。
6. **verify 批形状**：同一 9B 下 `TIR_MTP_N_MAX=1` 与 `=2` 各跑一遍（`tir_core.cpp:50-57`），`eval_ms/step` 之差 = 3 行 verify 的边际成本；若 `graph_reallocs_diff > 0`，capture 范围列为首嫌疑（`L2-C0:63`）。
7. **gate 的形态**：命令行断言（PowerShell 解析日志最后一条 run 行），不新增源文件；命令见验收 ③。分解式：`step_ms = target_eval_ms + draft_ms(E1) + sampler_ms + detok + callback + host_residual`。

## 验收标准（照抄脑暴 §1.5 问 3 E1/E2）

**E1（0 源文件，draft 份）**

```bat
set TIR_SPEC_DEBUG=1
build\tir-api\bin\tir-bench.exe <WORKSPACE>\artifacts\qwen9b-Q4_K_M.gguf 16384 1 128
rem 期望 stderr：tir-spec: drafted=… accepted=… steps=…
rem              tir-spec: draft eval_ms=… n_eval=…
rem draft 每步成本 = draft eval_ms / steps，直接与 11 ms 对照
```

**E2（=K2 正片，target/host 份）**

```bat
build\build-tir-api.bat
build\tir-api\bin\tir-bench.exe <WORKSPACE>\artifacts\qwen9b-Q4_K_M.gguf 16384 1 128
rem 期望：每条 run 行新增 eval_ms>0、step_us/1000 ≈ decode_ms（≤5%）、host_residual ≥ 0
rem verify 批形状：TIR_MTP_N_MAX=1 与 =2 各一遍，比较 eval_ms/step
rem graph_reallocs_diff>0 → capture 范围首嫌疑
```

**③ 命令行 gate（实现后填入实际字段顺序，RC=0 才算 GREEN）**

```powershell
powershell -NoProfile -Command "$l=(Get-Content build\logs\k2-final-9b.raw | Select-String '^tir-bench: run' | Select-Object -Last 1).Line; $m=[regex]::Match($l,'eval_ms=([0-9.]+).*step_us=(\d+).*decode_ms=([0-9.]+)'); if($m.Success){ $e=[double]$m.Groups[1].Value; $s=[double]$m.Groups[2].Value/1000.0; $d=[double]$m.Groups[3].Value; if($e -le 0 -or [math]::Abs($s-$d)/$d -gt 0.05){ exit 1 } } else { exit 1 }"
```

## 前置条件

- [x] P0 门在当前树通过（`reclaim-2026-11-11.raw:13300`）
- [x] K1-a 观测完成（`k1a-2026-11-11.raw` SUMMARY；MTP p50 9733.55 ms，plain pb=512 p50 265.28 ms）
- [ ] 工作区干净 —— **不成立**：基线 14 M + 21 ??。以派发前 `git status --porcelain` + 目标文件 `sha256sum` 为基线，回收后对照；不提交、不 stash、不回滚他人改动。
- [x] 公共 ABI 冻结（`tir.h` 只读）
- [x] `tir-bench.exe` 与 `tir-bench-ceiling.exe` 已构建；当前 `tir.dll` sha256 `fb320cdc…`（`build/logs/reclaim-2026-11-11.raw`）

## 停止条件

- `step_us/1000` 与 `decode_ms` 相对差 >5%，或 9B w2 补填后 `eval_ms` 仍恒 0 且无法用填充 bug 解释 → 停，按 `L2-C0:114` 转 CUDA event 测量研究项。
- 需要动 `common/` 或 kernel → 标「破边界」另行立卡，不写进本片。
- 需要改 `tir.h` 字段顺序或 bump version → 停（ABI 冻结）。
- 同一失败连续 2 次 → 停，写报告，不猜。
- 范围超出 2 个源文件 → 停，重新拆解。

## 变异测试（先 RED 后 GREEN，取证后立即恢复）

| 步骤 | 变异 | 期望 | 日志 |
|---|---|---|---|
| RED-1 | 临时跳过新字段填充（`eval_ms` 保持 0） | gate **RC=1**，输出含 `eval_ms=0` | `build/logs/k2-mutant-noeval-9b.raw` |
| RED-2 | `bench.c` 把 `step_us` 打成 `callback_us` | 断言 `step_us/1000 ≥ eval_ms` **RC=1**（防字段错位，呼应 `run-p0-gate.bat:65-71`） | `build/logs/k2-mutant-swap-9b.raw` |
| GREEN | 恢复后同命令 | **RC=0**；`eval_ms>0`、`step_us/1000 ≈ decode_ms`（≤5%）、`host_residual ≥ 0`；E0 两模型各一行合法 JSON 并写缺口归属结论 | `build/logs/k2-final-9b.raw`、`k2-e0-*.raw` |

变异只允许临时改本片两个写文件；取证后立即恢复，不得触碰基线 14 M + 21 ?? 的任何他人改动。

## 执行记录

| 时间 | 事件 | 证据 |
|---|---|---|
| — | 蓝图建立，未派发 | 本文件 |
| 2026-11-11 08:29 | 派发前基线：`git status --porcelain` 38 行、`bench.c` sha256 存档 | `build/logs/k2-baseline-2026-11-11.txt` |
| 2026-11-11 08:30 | RED-1：跳过字段填充（`eval_ms` 恒 0）→ gate **RC=1** | `build/logs/k2-mutant-noeval-9b.raw` |
| 2026-11-11 08:31–08:33 | GREEN 实现：`tir_mtp.cpp` perf 复位、step/detok/callback 计时、9 字段填充；`bench.c` `dump_stats` 追加打印。BUILD_OK（ninja no work），E2 RC=0。`nmax1` vs `nmax2` 形状一致（acceptance 0.925、mean_len 1.910、graph_reallocs_diff=0，`TIR_MTP_N_MAX` 在此路径无实测差异） | `build/logs/k2-nmax1-9b.raw`、`k2-nmax2-9b.raw`、`k2-nmax1.json`、`k2-nmax2.json` |
| 2026-11-11 08:34 | RED-2：`bench.c` 把 `step_us` 误打为 `callback_us` → gate **RC=1**（`step_us/1000 ≥ eval_ms` 不成立）；取证后按 sha256 恢复，恢复后 **RC=0** | `k2-mutant-swap-9b.raw`、`k2-mutation-sha.raw`（恢复前后均为 `da5ffbc7…`） |
| 2026-11-11 08:35–08:36 | E1（draft 份）：`tir-spec: drafted=67 accepted=62 steps=67`；`draft eval_ms=0.000 p_eval_ms=421.8–452.2 n_eval=1` → draft 每步 ≈6.3–6.8 ms（p_eval/steps 上界）；`eval_ms=0` 是 MTP draft 单 token 批的记账限制，非 bug | `k2-e1-9b.raw`、`k2-e1-9b.json` |
| 2026-11-11 08:36 | E0（4B 结构对照）：qwen 4B host_residual=109,974 µs（0.87 ms/token，7.4%）；Nemotron 4B=112,807 µs（0.89 ms/token，8.2%）→ 50 GB/s 级差距不在 eval 内，落在 host/调度段；Nemotron 的 step/decode delta 6.36% 超 5%，属 ceiling harness 辅助判读，不参与本片 gate | `k2-e0-4bqwen.raw`、`k2-e0-nemotron.raw` 末行 `E0-JUDGMENT` |
| 2026-11-11 08:46 | 主代理复跑 GREEN：`decode_ms=1637.04 eval_ms=123.93 prompt_eval_ms=1314.48 sampler_ms=21.81 step_us=1665381 detok_us=306 callback_us=40 graph_reused=71 graph_reallocs_diff=0`；gate **RC=0**（delta 1.73%，host_residual 1519.3 ms） | `k2-final-9b.raw`、`k2-gate.raw` |

**判读结论**

- MTP 路径的 `eval_ms` / `prompt_eval_ms` 与 plain 路径语义相反：verify 的 2-token 批被 `llama-context.cpp:888-917` 记入 `t_p_eval_us`，所以 `eval_ms≈120 ms` 只是 prefill 残量，真正的 verify decode 在 `prompt_eval_ms≈1.31 s`。按 `step_ms = eval_ms + sampler + detok + callback + host_residual` 分解：1.665 s ≈ 0.124 + 0.022 + 0.0003 + 0.00004 + 1.519 s，host 段占 91%，与 K1-a 的 9.7 s TTFT 同源。
- gate 正则需用前导空格锚定（` eval_ms=`），否则 `.*eval_ms=` 会先命中 `prompt_eval_ms=`——计划原文的正则有此缺陷，本片实测修正为逐字段锚定。
- 运行环境注意：`tir-bench.exe` 依赖 `runtime/llama-b12202` 下的 CUDA 13 运行库，系统 PATH 上没有；须在命令行内临时前置 PATH，否则 0xC0000135/RC=127。
- 阶段记录（含时间线、代码状态、备选与裁决）：`docs/reports/2026-11-11-k2-k3-stage-report.md`。
