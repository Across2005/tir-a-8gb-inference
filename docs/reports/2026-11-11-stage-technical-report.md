# TIR-A 阶段技术报告（2026-11-11 上午）

- 报告时间：2026-11-11 11:00 +0800
- 覆盖时间窗：2026-11-11 08:29 – 10:56 +0800
- 代码状态：工作树未提交，`git status --porcelain` **44 行**；`tir.dll` sha256 `8d64bd5d8857acc2…`（S3-b 后重建）
- 硬件：RTX 5060 Laptop 8151 MiB（检查期间余量 6875–7019 MiB，利用率 3–5%），CUDA 13.5
- 主模型：`Qwen3.8-9B-Q5_K_M.gguf`（门禁用）与 `qwen9b-Q4_K_M.gguf`（研究用），ctx 16384，q4 KV，greedy
- 口径：性能结论只采信 128-token 跑；8-token 短跑仅用于正确性与 parity；所有数字带模型/量化/ctx/prompt 长度/时间戳

---

## 1. 时间线

| 时刻 | 事件 | 证据 |
|---|---|---|
| 08:29:05 | K2 派发前基线（status 38 行 + sha256） | `k2-baseline-2026-11-11.txt` |
| 08:30–08:34 | K2 变异 RED-1 / RED-2，按 sha256 恢复 | `k2-mutant-*.raw`、`k2-mutation-sha.raw` |
| 08:31:43 | `tir_mtp.cpp` 补齐 9 字段遥测 | 文件 mtime |
| 08:34:38 | `bench.c` 扩打印 | 文件 mtime |
| 08:35–08:36 | E1 draft 账本、E0 4B 双模型对照 | `k2-e1-9b.raw`、`k2-e0-*.raw` |
| 08:38:56 | K3 margin oracle 实现（契约追加 `id=`） | `tir_generate.cpp` mtime |
| 08:38–08:41 | K3 短/长 prompt 采集 | `k3-baseline-id-9b.raw`、`k3-long-*.raw` |
| 08:46:02 | K2 主代理复跑 GREEN + gate RC=0 | `k2-final-9b.raw`、`k2-gate.raw` |
| 08:46–08:49 | K3 pb=512 有效重跑、长 prompt 复跑、负向控制 | `k3-repro-*.raw`、`k3-negative-9b.txt` |
| 08:50:04 | K3 摘要 + CORRECTION 块 + 最终裁决 | `k3-summary-9b.raw` |
| 08:57:34 | K2/K3 蓝图回填 + 阶段记录 | `2026-11-11-k2-k3-stage-report.md` |
| 09:00–09:34 | 脑暴定方向；S0 前缀探针（独立版失败 4 次 → 引擎内版成功） | `s0-prefix-probe.raw`（09:34:13） |
| 10:16:19 | 性能与稳定性检查：P0 门 + 8 测试 | `check-p0-gate.raw`、`check-tir-test-*.raw` |
| 10:21 | 检查报告成文（6 项静态风险） | `2026-11-11-engine-perf-stability-check.md` |
| 10:25:48–10:26:54 | S3 测试先行，**RED** 取证 | `test_generate.c` mtime、`s3-red.raw` |
| 10:27:22–10:28:10 | S3 实现（cancel 迁移 / n_ctx_train / 诊断 / 死字段） | 四个源文件 mtime |
| 10:29:12 | S3 **GREEN** | `s3-green.raw` |
| 10:34:51 | S3 回归 + P0 门 | `s3-p0-gate.raw` |
| 10:37:15–10:38:30 | S3-b 补两个残留缺口（0 值守卫 / MTP 越界测试） | `tir_core.cpp`、`test_mtp.c` mtime、`s3b-mtp.raw` |
| 10:44:00 | S3-b P0 门 | `s3b-p0-gate.raw` |
| 10:50:52–10:53:44 | 完整回归：9 个 C 测试 + 五模型矩阵 | `reg-*.raw` |
| 10:56:30 | 回归结论写入检查报告 §8 | 报告 mtime |

---

## 2. 本阶段的四个工作块

### 2.1 K2：MTP 遥测补齐（GREEN）

MTP 路径此前只填到 `mean_len`，等于黑盒。本片补齐 9 个 append-only 字段并配一条命令行 gate。

- 账本：`decode_ms=1637.04`、`eval_ms=123.93`、`prompt_eval_ms=1314.48`、`sampler_ms=21.81`、`step_us=1665381` → delta **1.73%**、host 残差 **1519.3 ms**，gate RC=0
  - **更正（Phase 0-D1）**：1519.3 ms 漏减了 `prompt_eval_ms`。prefill 后 sync+reset 重测：plain host **43.4 ms（1.9%）**、MTP host **317.3 ms（20.0%）**，`tok_s=82.05`（`build/logs/d1-clean-mtp*.raw`）
- 变异：noeval 与 step/callback 互换两次均 RC=1，恢复后 sha256 逐位一致
- E1：`drafted=67 accepted=62 steps=67`，draft `p_eval 421.8–452.2 ms` → ≈6.3–6.8 ms/step
- E0：4B qwen host 残差 109,974 µs（0.87 ms/token）、Nemotron 112,807 µs（0.89 ms/token）

**关键认知**：MTP 的 `eval_ms`/`prompt_eval_ms` 与 plain 路径语义相反——verify 的 2-token 批被记入 `t_p_eval_us`，`eval_ms≈124 ms` 只是 prefill 残量。原文"host 段占 step 的 91%"已在 Phase 0-D1 更正为 **20.0%**（317.3 ms）；同时修掉了 `prompt_eval_ms` 漏减与 prefill 污染两个口径缺陷。

### 2.2 K3：margin oracle（负结果，触发停止条件）

| 场景 | pb=2 | pb=512 | 真实翻转 |
|---|---|---|---|
| 默认短 prompt（8 tok） | min 0.0549（0.42×） | min 0.0080（0.06×） | idx=41，86/128 id 变化 |
| 长 prompt（521 tok） | min 1.4155（10.89×） | min 1.5411（11.85×） | 0/128 |

长 prompt TTFT 4224.97 → 252.49 ms。**裁决**：短 prompt 触发停止条件③ → 回填 K1 停止①，本轮不改任何生产默认值；只支持限定长 prompt 或带 parity 门控的批变更。

过程中抓到一次**假阳性**：首次 pb=512 日志与 pb=2 逐位相同，实为 env 未进入进程；已作 CORRECTION 保留，不重写历史。

### 2.3 S0：前缀复用可行性探针

独立 llama-API 探针 4 次全部在首次 decode 崩溃（CUDA illegal memory access），根因未定位，放弃。改为引擎内 env 门控两轮模式后一次跑通。

| 跑次 | pb | δ | reuse TTFT | fresh TTFT | 逐位一致 |
|---|---|---|---|---|---|
| Agent 前缀 163→243 tok，64 gen | 2 | **0** | 131 ms | 1951 ms | **YES 0/64** |
| 同上 | 512 | 0 | 21 ms | 37 ms | NO 41/64 |
| 短前缀 29→41 tok，8 gen | 2 | **0** | 39 ms | 316 ms | **YES 0/8** |

**三个结论**：
1. "BPE 拼接处必然错位"的假设**被推翻**——两次都 δ=0，路线 A（零裁剪）可能就够。
2. pb=512 的分歧不能归因于续算：K3 已证明批宽本身移动 logits，参照系必须是引擎默认的 fresh。
3. **实现陷阱**：采样循环最后一个 token 被采样但未 decode，续算前必须补这一行，否则 54/64 分歧。

探针取证后已恢复，`tir_generate.cpp` diff 回到 77 行，一次性产物删除。

### 2.4 S3 / S3-b：稳定性硬化 + 完整回归

检查发现 6 项静态风险，按优先级处置：

| ID | 处置 | 验证 |
|---|---|---|
| R1 cancel 挂 engine | 迁至 session（7 处读写） | T3 守卫测试；parity 与取消复用未退 |
| R3 `failed` 死字段 | 删除 | 全测试 RC=0 |
| R4 `n_ctx` 未对照训练长度 | load 期拒绝 `n_ctx > n_ctx_train` | **真 RED→GREEN**：`300000 > 262144` |
| R5 越界分支无测试 | plain + MTP 两条路径各补一条 | `tokens_after_reject=8` ×2 |
| R6 无跨 session 取消测试 | 补守卫测试 | `b_tokens=8` |
| R2 stats 挂 engine | **未改**（公共 ABI 签名约束） | 留待文档澄清 |

S3-b 另补两个残留缺口：`n_ctx_train > 0` 守卫（防病态 GGUF 拒绝一切）、MTP 越界分支测试。

---

## 3. 性能数字汇总

| 模型 / 量化 | ctx | 路径 | tok_s | TTFT | 时间 |
|---|---|---|---|---|---|
| 9B Q5_K_M | 16384 | MTP | 71.86 → 71.77 → **71.08** | 173→170→175 ms | 10:16 / 10:34 / 10:44 |
| 9B Q5_K_M | 16384 | plain | 47.00 → 47.27 → **46.80** | 104→102→104 ms | 同上 |
| 9B Q4_K_M | 16384 | MTP | 76.57（acc 0.925） | 149 ms | 10:53 |
| 9B Q4_K_M | 16384 | plain | 53.76 | 89 ms | 10:53 |
| 4.2B Q4_0 | 8192 | plain | 101.51 | 21 ms | 10:52 |
| 0.8B Q4_K_M | 8192 | plain | 282.62 | 13 ms | 10:52 |
| 0.6B Q8_0 | 8192 | plain | 210.10 | 13 ms | 10:52 |
| nemotron-4b Q4_0（522 tok） | 8192 | plain | 122.26 | 123 ms | 10:52 |
| 9B Q4_K_M ngram spec | 16384 | spec | 102.11（acc 1.000） | — | 10:50 |

三次 P0 门的 MTP 数字 71.86 / 71.77 / 71.08 差异在跑间噪声内，**无性能回归**。

**最大的未兑现收益**：521-token prompt 下 MTP TTFT p50 **9733.55 ms** vs plain pb=512 **265.28 ms**（K1-a 实测），9.47 s 缺口至今未动。

---

## 4. 决策与备选

| 决策点 | 备选 | 裁决 | 理由 |
|---|---|---|---|
| Agent 部署形态 | 单会话多轮 / 多会话并发 / 服务化 | 单会话多轮 | 8G 显存不支持多份 context；调度器属 YAGNI |
| 前缀复用路线 | A 零裁剪 / B 有界裁剪 / C 状态 blob | B + 探针先行 → 探针后 A 可能就够 | δ=0 实测推翻错位假设 |
| 前缀接口边界 | 改 ABI / append-only / 不改 | 不改 `tir.h`，session 内隐式 | 用户定；宿主须跨轮复用 session |
| K3 预算结论 | 全局放开默认批 / 限定长 prompt | 后者 | 短 prompt 触发停止条件③ |
| R1 验证方式 | 伪造 RED / 守卫测试 | 守卫测试 | 受支持用法下构造不出 RED，如实声明 |
| R2 是否改 | 改签名 / 不改 | 不改 | 公共 ABI 冻结，顺序形态无影响 |

---

## 5. 主流对标

- **vLLM / SGLang**：automatic prefix caching 与 continuous batching 是 Agent 场景标配。本阶段确认了前缀复用在 hybrid（gated delta net）模型上**可做到逐位一致**（pb=2 下 0/64），这是能落地的前提；但尚未实现。continuous batching 因单会话形态与显存被明确裁掉。
- **llama.cpp server**：上游有 slot 级 `cache_prompt` 前缀复用。我们的 fork 是冻结 C ABI 的库，没有 server 层，因此前缀复用必须做在 session 层，不能直接搬上游实现。
- **本项目的差异化约束**：8G 显存、`tir.h` 冻结、plain↔MTP 逐位 parity 硬门。上游不保证最后一条，而它是我们所有批处理决策的前置条件——K3 的停止条件正是为它设的。

---

## 6. 局限与未解决

1. **S0 只测了 2 轮、单模型、plain 路径**。MTP 路径的前缀复用、3 轮以上累积、上千 token 长历史均未测。
2. **δ>0 未出现**，B 路线的有界裁剪从未被验证；`n_rs_seq` 是否需提高仍是开放问题。
3. **R1 无 RED**：顺序用法下 `session_generate` 入口重置标志，串扰只在并发下暴露，而 ABI 明说不可重入。T3 是守卫，不是缺陷复现；反向变异未执行。
4. **R2 未改**：`last_stats` 仍在 engine，并发场景统计会互相覆盖。
5. **nemotron 短 prompt 首 token 即 EOG**（`gen_tokens=0`）。同模型 522-token prompt 正常生成 128 token，判为模型/prompt 交互行为；但历史 A4 用的是另一套 harness，**没有该默认 prompt 的逐位历史对照**。
6. **`n_ctx_train=0` 的病态 GGUF 无样本**，该守卫属外部输入边界防御，未实跑复现。
7. **`test/*.mjs` 三个门不经过 tir.dll**（打上游 llama-server 与 DSH 宿主，DSH 已暂停），无法验证本次引擎改动。
8. **E0 的 Nemotron step/decode 偏差 6.36%** 超 5% 判据，属 ceiling harness 辅助判读，不应作精确值引用。
9. 所有性能数字均为 128-token 短跑，长历史外推未测。

---

## 7. 下一步建议（按收益/风险排序）

1. **K1-b：MTP TTFT 的 9.47 s 缺口**——本阶段所有工作里最大的未兑现收益。必须带默认短 prompt 的 64-token parity 硬门（K3 裁决）。
2. **S2：前缀复用**——先补 MTP 路径与多轮累积的探针，再按路线 A 立 spec；末 token 补 decode 是必须写进设计的陷阱。
3. **R2 文档澄清**——在 ABI.md 写明 `tir_stats_snapshot` 是"最近一次完成的请求"，零代码风险。
4. **S3 ModelTraits**——把 `prefill_batch_for_arch` 白名单、MTP ngram 参数、nextn 回退集中到从 GGUF metadata 读取的内部结构。

---

## 8. 证据索引

| 类别 | 位置 |
|---|---|
| K2/K3 阶段记录 | `docs/reports/2026-11-11-k2-k3-stage-report.md` |
| 检查 + S3 + 回归 | `docs/reports/2026-11-11-engine-perf-stability-check.md` |
| 蓝图 | `docs/blueprints/L2-K2-*.md`、`L2-K3-*.md`、`L2-S3-stability-hardening.md` |
| K2 日志 | `build/logs/k2-*.raw` |
| K3 日志 | `build/logs/k3-*.raw`（含 CORRECTION 块） |
| S0 探针 | `build/logs/s0-prefix-probe.raw` |
| 检查 | `build/logs/check-*.raw` |
| S3 / S3-b | `build/logs/s3-*.raw`、`s3b-*.raw` |
| 完整回归 | `build/logs/reg-*.raw` |
| 计划文件 | `<USER>\.qoder-cn\plans\crisp-jungle-loach.md` |
