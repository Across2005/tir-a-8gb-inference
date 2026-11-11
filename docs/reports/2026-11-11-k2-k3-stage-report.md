# K2 + K3 阶段性工程记录（2026-11-11）

- 记录时间：2026-11-11 08:57 +0800（全部时刻均为本机 +0800）
- 代码状态：工作树（未提交），`git status --porcelain` 39 行 = 派发前基线 38 行 + 1 行 `M src/llama.cpp-fork/tests/tir-api/bench.c`
- 二进制：`tir.dll` sha256 `5619f58a3c44c3d1dc6d01f827eb038b75793b53db81223b8eab55ff6ea5b8a1`（mtime 08:39:29）；基线 dll `fb320cdc…`（`reclaim-2026-11-11.raw`）
- 硬件/模型：RTX 5060 Laptop 8151 MiB，`artifacts/qwen9b-Q4_K_M.gguf`，`n_ctx=16384`，MTP w2（nextn→默认批 2），greedy，128 生成 token
- 口径：性能结论只采信 128-token 跑；8-token 短跑仅用于正确性与 parity，不进性能结论

## 1. 时间线

| 时刻 | 事件 | 证据 |
|---|---|---|
| 08:29 | 派发前基线：status 38 行、`bench.c` sha256 存档 | `build/logs/k2-baseline-2026-11-11.txt` |
| 08:30 | K2 RED-1：跳过 9 字段填充 → gate RC=1 | `k2-mutant-noeval-9b.raw` |
| 08:31 | K2 实现：`tir_mtp.cpp` perf 复位 + step/detok/callback 计时 + 9 字段填充 | 文件 mtime 08:31:43 |
| 08:33 | `TIR_MTP_N_MAX=1/2` 形状对照（无差异） | `k2-nmax1/2-9b.raw` |
| 08:34 | K2 RED-2：`step_us` 误打为 `callback_us` → RC=1；按 sha256 恢复后 RC=0 | `k2-mutant-swap-9b.raw`、`k2-mutation-sha.raw` |
| 08:34 | `bench.c` 扩打印（唯一新增 status 行） | 文件 mtime 08:34:38 |
| 08:35–08:36 | E1 draft 账本、E0 4B 双模型对照 | `k2-e1-9b.raw`、`k2-e0-*.raw` |
| 08:38 | K3 实现（margin oracle），契约追加 `id=` | 文件 mtime 08:38:56 |
| 08:38–08:39 | K3 短 prompt 基线 pb=2 | `k3-baseline-id-9b.raw` |
| 08:40–08:41 | K3 长 prompt 两设置；短 prompt 首次 pb=512（后判定为 env 未生效） | `k3-long-*.raw`、`k3-pb512-9b.raw` 前 4 块 |
| 08:46 | K2 主代理复跑 GREEN + gate RC=0 | `k2-final-9b.raw`、`k2-gate.raw` |
| 08:46–08:47 | K3 短 prompt pb=512 有效重跑（真实翻转定位） | `k3-pb512-9b.raw` 块 4–7、`k3-repro-short-pb512-9b.raw` |
| 08:49 | K3 长 prompt 复跑 + 负向控制 | `k3-repro-long-*.raw`、`k3-negative-9b.txt` |
| 08:50–08:57 | K3 摘要补 CORRECTION 块与最终裁决 | `k3-summary-9b.raw` |
| 08:57 | 回填两份 L2 执行记录；gate 证据落盘；本记录写入 | 本文件 |

## 2. K2：MTP 遥测补齐（已 GREEN）

**改动面**（切片内，行为不变）：`tir_mtp.cpp` 增加 `llama_perf_context_reset`、循环内 wall-clock 计时、结束填 9 个 append-only 字段；`bench.c` 的 `dump_stats` 行尾追加打印。`tir.h` 未动。

**主证据（08:46，`k2-final-9b.raw`）**

```
decode_ms=1637.04 eval_ms=123.93 prompt_eval_ms=1314.48 sampler_ms=21.81
step_us=1665381 detok_us=306 callback_us=40 graph_reused=71 graph_reallocs_diff=0
GATE delta_pct=1.73 host_residual_ms=1519.3 RC=0
```

**变异**：RED-1（eval=0）RC=1；RED-2（step↔callback）RC=1；恢复后 sha256 `da5ffbc7…` 与变异前逐位一致，复跑 RC=0。

**draft 份（E1，08:35）**：`drafted=67 accepted=62 steps=67`；`draft eval_ms=0.000 p_eval_ms=421.8–452.2 n_eval=1` → draft ≈6.3–6.8 ms/step（p_eval/steps 上界）。`eval_ms=0` 是 MTP 单 token 批的记账限制，不是填充 bug。

**4B 结构对照（E0，08:36）**

| 模型 | step_us | eval_ms | host_residual | 占 decode | step/decode 偏差 |
|---|---|---|---|---|---|
| qwen35 4.2B IQ4_XS | 1,545,235 | 1,405,204 | 109,974 µs（0.87 ms/tok） | 7.4% | 4.43% |
| Nemotron 4B | 1,461,875 | 1,336,558 | 112,807 µs（0.89 ms/tok） | 8.2% | 6.36% |

**判读**：MTP 的 `eval_ms`/`prompt_eval_ms` 与 plain 路径语义相反——verify 的 2-token 批被 `llama-context.cpp:888-917` 记入 `t_p_eval_us`，`eval_ms≈124 ms` 只是 prefill 残量，真正 verify decode 在 `prompt_eval_ms≈1.31 s`。按分解式 `step = eval + sampler + detok + callback + host`：1.665 s ≈ 0.124 + 0.022 + 0.0003 + 0.00004 + 1.519 s，host 段占 91%。4B 的 50 GB/s 级差距不在 eval 内，落在 host/调度段。

> **更正（2026-11-11，Phase 0-D1）**：上一段的 host 残差公式漏减 `prompt_eval_ms`，且 `eval_ms` 里混入了循环外的 prefill 时间。修正后两条路径在 prefill 之后先 `llama_synchronize` 再 `llama_perf_context_reset`，并用完整式子
> `host = step − eval − prompt_eval − sampler − detok − callback`。
> 重测（9B Q4_K_M，ctx 16384，128 token，`build/logs/d1-clean-mtp*.raw`）：
> plain `step=2304.08 ms, eval=2234.53, prompt_eval=0, host=43.4 ms（1.9%）`；
> MTP `step=1586.24 ms, eval=0, prompt_eval=1246.95, host=317.3 ms（20.0%）`，`tok_s=82.05`、`acceptance=0.925`。
> **"host 段占 91%"作废**，正确量级是 MTP 20%。gate 的通过判定（残差 ≥0、delta ≤5%）不受影响。E0 的 4B 对照是在同一有缺陷的式子下算的，其 host 数值同样偏高，引用时须注明。

**已知瑕疵**：E0 走的 ceiling harness，Nemotron 的 step/decode delta 6.36% 超本片 5% 判据；E0 是 0 源文件的辅助判读，不参与 gate，但该数字不应被引用为精确值。`TIR_MTP_N_MAX=1/2` 在此路径无实测差异（acceptance/mean_len/graph 形状全同），不能据此推断边际成本。

## 3. K3：greedy margin oracle（已裁决，负结果）

**实现**：`tir_generate.cpp:168-187,237-240`，`TIR_MARGIN_DEBUG` 开启时逐 token 打印 `tir-margin: idx=… id=… m=… flip=…`，末尾打印 `min=… (0.13 ref: kx)`；env 关闭零开销零输出。

**契约修订**：蓝图设计 §2 原输出无 top1 id，实测无法跨运行定位真实翻转点，故追加 `id=<top1>`。stderr-only、env 门控、不写 `tir_stats`、不改 `struct_size`。

**短默认 prompt（8 token）**

| 设置 | min-margin | 相对 0.13 | 首个分歧 token | 后续 id 差异 |
|---|---|---|---|---|
| pb=2 | 0.0549 | 0.42× | idx=41 id=58737 m=0.0549 flip=1（参照侧） | — |
| pb=512（env 验证生效） | 0.0080 | 0.06× | idx=41 id=9357 m=0.6136 flip=0 | 86/128 |

两设置各自跨进程逐位一致。

**长 prompt（521 token / 2340 B）**

| 设置 | min-margin | 相对 0.13 | TTFT | 跨设置 id 差异 |
|---|---|---|---|---|
| pb=2 | 1.4155 | 10.89× | 4224.97 ms | 0/128 |
| pb=512 | 1.5411 | 11.85× | 252.49 ms | 0/128 |

两进程 × 两设置全部逐位可复现。批宽会扰动 logits（127/128 行的 margin 第 4 位起不同），但 top1 不变。

**假阳性记录**：08:40 首次 pb=512 短 prompt 结果与 pb=2 逐位相同（0.0549 / 0 diff），后确认为 `TIR_PREFILL_BATCH` 未进入进程；已作 CORRECTION 块保留，不重写历史。另：长 prompt 的「margin diff 127/128」是真实批宽效应，两者可用「top1 id 是否变化」区分。

**最终裁决**（预注册规则见 `L2-K3-margin-oracle.md:80,94`）：

- 521-token 长 prompt：两腿均过（≥10.89×、0 真实翻转）→ 0.13 位移预算在该语境可行。
- 默认短 prompt：余量 0.42×/0.06× < 2×，且 pb=512 产生 1 个真实翻转（86/128 id 变化）→ **触发停止条件③**。
- 后果：回填 K1 停止条件①，**本轮不改任何生产默认值**；K1-b 的 L2 必须带「默认短 prompt 64-token parity 门」。只支持限定在长 prompt（或有 parity 门控）的批变更。

## 4. 边界与审计（08:57）

- 写域实改：`tir_mtp.cpp`、`bench.c`、`tir_generate.cpp`；文档新增/回填：两份 L2、本记录；日志只追加 `build/logs/k2-*.raw`、`k3-*.raw`。
- 禁改项今日未动：`tir.h`（mtime 11-09 19:14）、`tir_internal.h`（11-09 20:57）、`tir_core.cpp`（11-09 20:56）、`tests/CMakeLists.txt`（11-08）、`common/speculative.cpp`（11-09 21:02）；无 `.cu` 于 11-11 被修改。
- 未执行：commit / stash / reset / checkout / push / PR / master 操作；未下载模型、未装依赖、未改环境变量（`TIR_*` 均命令行内临时设置）。
- `L1-interactive-runtime.md` §8 未回填：该文件属既有未提交改动，且 K1-b 尚未立卡；按 K1-b 条件④留到立卡前。

## 5. 复现环境注意

`tir-bench.exe` 依赖 `runtime/llama-b12202/` 下的 CUDA 13 运行库，系统 PATH 无此目录；须在同一命令行临时前置，例如：

```bash
PATH="/e/Deepseek/tir-b/runtime/llama-b12202:$PATH" build/tir-api/bin/tir-bench.exe ...
```

否则报 0xC0000135 / RC=127。`TIR_PREFILL_BATCH` 等 env 必须在与 bench 同一命令行内设置，并用 margin 是否变化回验其确实生效。

## 6. 备选与裁决

| 决策点 | 备选 | 裁决 | 理由 |
|---|---|---|---|
| MTP draft 成本口径 | 直接读 `eval_ms` / 用 `p_eval/steps` 上界 | 后者 | draft 单 token 批记账为 0 |
| K3 flip 判据 | 仅看 `flip=1` 候选 / 跨运行 top1 id diff 定位真实翻转 | 两者并用 | 候选数不等于真实翻转数；本例候选 4 个，真实翻转 1 个 |
| K3 预算结论 | 全局放开默认批 / 仅长 prompt 或 parity 门控 | 后者 | 短 prompt 触发停止条件③ |
| 本轮是否改默认值 | 改 / 不改 | 不改 | 预注册规则优先于收益预期 |
