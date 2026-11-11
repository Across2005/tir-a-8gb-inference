# MTP 落地报告（插件 v1.1 + B1 重规划）

- 日期：2026-11-09
- 执行：DSH
- 依据：`DSH-HANDOFF/TASK-2026-11-09-MTP.md`、`tir-b/test/gpu-ceiling-report.md`
- 结论：**插件已自动识别 nextn 模型并启用 `--spec-type draft-mtp`；qwen9b 16k q4 + MTP 实测 59.2 t/s（acceptance 0.748）、2k q8 + MTP 87.6 t/s（acceptance 0.818）；dsr1 未加 MTP 参数且正常；B1 目标已改为 16k MTP ≥50 / tier+MTP ≥30，planner 已加 MTP 因子。**

## 1. 插件 v1.1 改动

- `src/host/catalog.js`：新增轻量 GGUF 解析器（buffered reader，跳过 tokenizer 大数据）：
  - 读取 `general.architecture`、`${arch}.nextn_predict_layers`、张量表名；
  - entry 增加 `arch`、`mtp`、`nextnLayers`；
  - 实测：qwen9b `mtp=true,nextn=1`；dsr1/gemma12/gemma26 `mtp=false`；单模型解析 33–80 ms。
- `src/host/config.js`：新增 `mtp: auto|on|off`（默认 auto）；`modelOverrides[].mtp` 支持逐模型覆盖。
- `src/host/server.js`：
  - `resolveMtp()`：auto 仅在 nextn 模型启用；on 强制；off 关闭。
  - 仅 MTP 模型追加 `--spec-type draft-mtp`；无 MTP 模型不加。
  - qwen9b override：ctx 16384 / kv q4_0 / mtp auto；若 16k 启动失败自动回退 4096 并写 warning + `mtp.fallbackCtx`。
  - `status().mtp` 暴露 `enabled/modelMtp/nextnLayers/requested/acceptance/meanLen/fallbackCtx`；acceptance/meanLen 从 server 日志解析。
- `cordis.patch.yml`、`README.md` 更新 MTP 字段与 qwen9b 16k 说明。
- 单测：`node --test` → **29 tests / 28 pass / 0 fail / 1 skip**（integration 默认跳过），日志 `tir-b/test/mtp-node-test.txt`。

## 2. 实测（真实 llama-server b12202，2026-11-09 09:37）

| 场景 | ctx/KV | MTP | tok/s | acceptance | mean len | 备注 |
|---|---|---|---:|---:|---:|---|
| qwen9b 16k | 16384/q4_0 | on | **59.23** | 0.748 | 3.24 | overcommit（free 6886 MiB；need 7359）；无 fallback |
| qwen9b 2k | 2048/q8_0 | on | **87.58** | 0.818 | 3.43 | 128 token |
| dsr1-8b | 8192/q4_0 | off | 54.44 | — | — | 未加 `--spec-type`，正常 |

- 证据：`tir-b/test/mtp-plugin/results.json`；每次启动的 server 日志在 `%TEMP%\mtp-plugin-*\*.log`。
- 插件日志确认参数：`--load-mode none --jinja --metrics -fa on --spec-type draft-mtp`；dsr1 启动行无 `--spec-type`。
- 2k 2k 组为单请求 128 token，非 30 min 稳定值。

## 3. 30 分钟稳定性

（运行中：单 server、16k q4 MTP、每 10 s 一次 greedy 64-token 请求；记录 tok/s/acceptance/free VRAM/温度/功耗；若检测到 Qoder 并发 llama-server 则跳过该样本。完成后补 summary。）

- 首轮（09:38–09:43）受 Qoder `mtp-bench.ps1 -C 2048` 并发干扰，已停止并重跑。
- 脚本：`tir-b/test/mtp-stability.mjs`；输出 `tir-b/test/mtp-plugin/stability.jsonl` + `stability-summary.json`。

## 4. B1 重规划（优先级 2）

- `tools/tier_gguf.py`：profile 增加 `mtp`。
- `tools/tier_plan.py`：`--mtp auto|on|off`、`--mtp-factor 2.0`、`--mtp-mean-len 3.2`：
  - host 溢出预算按 `spill_bytes / mean_len` 计；`expected_tok_s × factor`；warnings 注明。
- 自测 8/8（新增 MTP 用例）。新 plan（free 6800 MiB）：
  - qwen9b 16k q4 + MTP：host 溢出 7 层 FFN、0.32 GiB/token、**57.2–80 tok/s**；
  - dsr1 16k q4 全 GPU：18–28 tok/s（无 MTP）；
  - gemma12：host 溢出 1.31 GiB/token、12.2–21.7。
- B1 验收改为：qwen9b 16k q4+MTP ≥50 t/s，或 tier+MTP ≥30 t/s；原 20 t/s 门作废。
- 计划文档：`tir-b/docs/b1-plan.md`（已更新）。

## 5. 未完成/风险

- 30 min 稳定性结果待补；16k 依赖 WDDM overcommit（free ~6.9 GiB、模型 ~7.2 GiB），持续负载可能抖动；建议关 Edge/微信/Overlay 或重量化 Q4_K_M。
- MTP 质量验证只记录了 acceptance/mean len；同 prompt greedy 的 on/off 文本差异尚未逐条比对。
- 功耗上限（94.12→115 W）未执行（需管理员，代理不碰 UAC）。

---

## 3.1 稳定性运行记录（进行中）

- 运行 1（09:38:38–09:50:39，30 min 窗口内）：32 个成功样本后 llama-server 被外部清理（无崩溃日志，最后一行是正常 request release；同时段 Qoder `mtp-bench.ps1 -C 2048` 在跑，疑似其清理脚本按进程名停止所有 llama-server）。
  - 32 样本：tok/s avg **36.3**、min 18.1、max 79.5；acceptance avg **0.865**；free VRAM 247–335 MiB（overcommit）。
  - 证据：`tir-b/test/mtp-plugin/stability-run1-killed.jsonl`。
- 运行 2（09:57 起）：同配置重跑；脚本检测到 server 掉线会自动重启并记录 `restarts`；若检测到其他 llama-server 进程则跳过该样本（Qoder 干扰）。结果见 `stability-summary.json`（完成后补）。

## 3.2 功耗记录（只记录，不执行）

- `nvidia-smi -q -d POWER`（2026-11-09 09:57）：Instantaneous 17.95 W（空闲）、**Current Power Limit 115.00 W**、Default 50.00 W、Max 115.00 W；mclk 9001 MHz（空闲）、gfx 1635 MHz、47°C。
- 与 `gpu-ceiling-report.md` 的“当前上限 94.12 W”不一致：本次读数为 115 W（可能是 vBIOS/驱动状态或报告采样时刻不同）。**未执行 `nvidia-smi -pl`，不碰提权**。
- 证据：`tir-b/test/power-record.txt`。

---

## 3.3 30 分钟稳定性结果（run2，有效）

- 配置：qwen9b 16k q4_0 + MTP，单 server，每 10 s 一次 greedy 64-token 请求。
- 2026-11-09 09:57–10:27，**30.0 min / 151 samples / 0 errors / 0 restarts / 0 contention skip**。
- tok/s：**avg 42.78，min 37.09，max 51.50**；acceptance 恒 **0.865**（同一 prompt 确定性）；mean len 3.5。
- free VRAM：133–230 MiB（16k overcommit）；温度 47–51 °C；功耗 16.9–20.7 W（10 s 间隔含空闲）。
- 结论：**无 OOM/崩溃，MTP 持续可用**；但 64-token 短生成下持续吞吐 42.8 t/s，低于“16k MTP ≥50”的短跑值；128-token 单请求为 59.2 t/s。差异来自生成长度/预热与 overcommit，不是崩溃。
- 证据：`tir-b/test/mtp-plugin/stability-summary.json`、`stability.jsonl`。

## 3.4 质量对照（greedy，MTP off vs on）

- 同模型/16k/q4、同 prompt、greedy、128 token：MTP on/off 的 reasoning 文本 **457 字符完全相同**（`identicalText=true`，firstDiff=-1）；content 均空（模型把预算用于 reasoning）。
- 单请求 tok/s：off 46.8 / on 46.0（同 run 内几乎相同；MTP 增益对该 prompt 不显著，acceptance 0.867、mean len 3.6）。
- 证据：`tir-b/test/mtp-plugin/quality-mtp-vs-off.json`。
- 说明：MTP 是验证式投机，输出与 off 一致；吞吐增益依赖 prompt/生成长度/acceptance，不能对所有场景承诺 1.6x。

## 6. 结论与建议（更新）

- 插件 v1.1 满足：nextn 自动识别、仅 MTP 模型加 `--spec-type draft-mtp`、16k q4 MTP、失败回退、acceptance 可见、单测通过。
- 验收状态：
  - 2k q8 MTP ≥75：**通过**（87.6）。
  - 16k q4 MTP ≥50：**单请求通过**（59.2）；30 min 持续 64-token 请求 **42.8**，未达 50；无崩溃/OOM。
  - dsr1/gemma 不加 MTP：dsr1 通过（54.4，无参数）。
- 建议：若要求 30 min 持续 ≥50，优先关闭 Edge/微信/Overlay（多出 0.5–1 GB）或把 qwen9b 重量化 Q4_K_M（~5.2 GB，避免 overcommit）；本代理未改模型文件。
