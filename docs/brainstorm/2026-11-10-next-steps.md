# 2026-11-10 TIR-A 下一步 L2 脑暴：next steps

- 工作区：`E:/Deepseek/tir-b`；本文是本次脑暴的**唯一交付物**（派发单 §输出格式）。
- 阶段性质：L2 前置脑暴。取证全程只读，**未跑任何 GPU 推理、未改任何现有文件、未动环境变量**；文中标注「未测」的项一律不猜。
- 口径优先级（派发单 §0）：工程 `.raw` 时间戳 > 蓝图执行记录 > 论文附录/正文。
- 候选编号：K1–K4；必答四问见 §1.5；证伪清单见 §3；排序与变异测试见 §4。

---

## 0. 四项事实裁决

### 0.1 A5 的真实状态：**工程侧已全部补齐；论文正文写"未完成"已过期**

**结论**：A5 五模型 GREEN + 64-token MTP parity + 四项回归在 2026-11-10 12:47–12:58 全部完成（RC=0），与 `L2-A5-a4-gate-hardening.md:95-103` 执行记录一致。不同步发生在**论文正文**：`paper.md:315/:353/:427` 仍写"标未完成 / 没补完"，而附录 D `99-appendix.md:66` 已写"全部完成"——附录与正文互相矛盾，且正文定稿（13:03:08）晚于补跑（12:45–12:58），属写作时点滞后，不是工程未完成。

证据（文件:行 + 时间戳）：

| 项 | 证据 |
|---|---|
| 1B GREEN | `build/logs/a5-final-1b.raw` mtime **12:47:26**，`:16445` `expect=512 gain=30.95x def_err=1.0 seq_err=1209.4 match=OK parity=OK profile_match=OK`，末行 `test_prefill: OK` |
| 4.2B GREEN | `a5-final-4b.raw` **12:49:15**，`:14093` `gain=32.12x def_err=6.0 seq_err=4920.7 match=OK parity=OK` |
| Nemotron 4B GREEN | `a5-final-nemotron.raw` **12:51:04**，`:14931` `gain=31.14x def_err=4.3 seq_err=4383.9 match=OK parity=OK` |
| 8B GREEN | `a5-final-8b.raw` **12:53:49**，`:23032` `gain=32.49x def_err=3.4 seq_err=7700.5 match=OK parity=OK` |
| 9B GREEN（关键） | `a5-final-9b.raw` **12:57:45**，`:14357` `expect=2 gain=1.92x profile=0.99 def_err=34.2 seq_err=4505.1 match=OK parity=OK profile_match=OK` |
| MTP 回归 | `a5-reg-mtp-9b.raw` **12:58:33**，`:4688` `test_mtp: OK plain=64 mtp=64 parity=64`，RC=0 |
| chat/generate/abi/abi-load 回归 | `a5-reg-chat-9b.raw` 12:58:52 / `a5-reg-generate-1b.raw` 12:58:53 / `a5-abi.raw` 12:58:54 / `a5-abi-load.raw` 12:58:54（含 `layers=24 embd=1536 ctx_train=131072 vocab=130560 mtp=0`），全 RC=0 |
| 变异 RED 已取证 | `a5-mutant-new-9b.raw` 9:50:32 `def_err=4507.2 seq_err=1.9 match=FAIL`、`a5-mutant-new2-9b.raw` 9:54:27 复跑同失败（蓝图 `L2-A5:89-90`） |
| 实施偏差（仍真） | 蓝图 `L2-A5:105`：1B 变异 RED 未单跑（会先被 `profile<0.5` 拦住）——与附录 E:70 一致，**该条不同步不成立，附录 E 是对的** |

**这些日志对应哪份构建**：`build\tir-api\bin\tir-test-prefill.exe` mtime **2026-11-10 10:24:22**；GPU 跑分时源码为 `tir_generate.cpp` sha `9b2588…` 与 `test_prefill.c` sha `3570d264…`（蓝图 `:92`）。12:55 A5b 仅改注释（`d67f37f5…`，蓝图 `:102`），重建后只做 CPU 侧 `tir-test-abi` 复核；`tir.dll` mtime **2026-11-10 13:00:56** 是 A5b 之后的重建产物，**不是**跑分时的二进制。

### 0.2 run-p0-gate.bat 的 ROOT：**仍漂移；此前 P0_GATE_OK 测的是 tir-b-p0 树；A5 没经过该脚本**

**结论**：
1. `build/run-p0-gate.bat:6` = `set "ROOT=<TIR_ROOT>-p0"`，未修；`:7 BIN`、`:9 OUT`、`:10 LOGS` 全部派生自 ROOT，而 `:8 CUDA_ROOT=<TIR_ROOT>\runtime\cuda-13.5` 又取自当前树——**两棵树混用**。
2. 此前 `P0_GATE_OK`（`:85-86`）测的是 **tir-b-p0 树**：其产物 `<TIR_ROOT>-p0\test\tir-api\p0-gate*.json` mtime **2026-11-09 16:46:28**，对应那棵树的 `tir.dll`（2026-11-09 16:24:42）；当前树 `tir-b\test\tir-api\p0-gate*.json` mtime 2026-11-09 16:00:45 更早。**两份都不是**当前工作树的 `tir.dll`（2026-11-10 13:00:56）。
3. **A5 的五模型 GREEN 未经过 run-p0-gate.bat**：蓝图 `L2-A5:95-101` 直接跑 `tir-test-prefill.exe` 等单测；日志互不包含——`tir-b-p0\build\logs` 无 `a5-*`，当前树 `build\logs` 无 `p0-*`。

影响：自 HEAD（11-09 16:47）之后的全部改动（含 A1–A5）**从未在当前树过过 P0 门**。派发单 §回收落点第 1 条成立：先修 ROOT 再谈任何 gate 数字。

### 0.3 git status 写域分析与脑暴基线：**14 M + 20 ??（派发单写 6 ?? 已过期）；越界项 1 个（common/speculative.cpp）**

**结论**：HEAD = `727fa5c43d0cdc61c3ff0ef0862d1201f976e213`（2026-11-09 16:47:52, "docs(blueprints): record S2d reasoning channel"）。`git status --porcelain` 实测 **34 项 = 14 M + 20 ??**（派发单 §0 写"6 ??"已过期；此前对话里口误的"25 ??"一并更正为 20）。`git diff --stat`：**14 files changed, 488 insertions(+), 46 deletions(-)**，最大 `tests/tir-api/test_prefill.c` +258。

**14 个 M（逐项）**：

| 文件 | 域判定（对照 L1 §5 `L1-interactive-runtime.md:77-79`） |
|---|---|
| `build/build-tir-api.bat` | 派生构建脚本，非 §5 白名单——保留原状，本次不碰 |
| `docs/blueprints/L1-interactive-runtime.md` | 文档，保留原状 |
| `src/llama.cpp-fork/common/speculative.cpp` | **越界**：`common/` 在 §5:78 只读清单。7 行 diff：新增 `spec_draft_simple` 判定 + `cparams.n_rs_seq` 由恒 0 改为 `spec_draft_simple ? draft.n_max : 0`（draft-simple 实验遗留，`test/mtp-plugin-report.md` 同批未跟踪） |
| `src/tir-api/tir.h` | **合规**：diff 仅 `tir_stats` 末尾追加 9 字段（`tir.h:87-96`，注释 `append-only C0 perf fields; old callers pass a smaller struct_size`），符合 L1:42「C0 允许末尾追加」 |
| `src/tir-api/tir_internal.h` / `tir_generate.cpp` / `tir_mtp.cpp` / `tir_core.cpp` / `CMakeLists.txt` | §5:77 可写域（A1–A5 累积），保留原状 |
| `tests/tir-api/test_mtp.c` / `test_prefill.c` | §5:77 `tests/tir-api/**` 可写，保留原状 |
| `test/g2-model-catalog.json` / `mtp-plugin-report.md` / `mtp-stability.mjs` | 门禁/插件实验产物，保留原状 |

**20 个 ??（逐项）**：8 个 L2 蓝图 `docs/blueprints/L2-{A3,A4,A5,C0,C2a,C2e,C3,TP1}-*.md`；`src/llama.cpp-fork/test/bench-dsr1-4k.txt`；`test/` 下 11 项 `bench-ceiling.ps1`、`bench-dsr1-4k.txt`、`bench-power.ps1`、`ceiling/`、`gpu-ceiling-report.md`、`mtp-bench.ps1`、`mtp-plugin/`、`mtp-quality.mjs`、`mtp-test.ps1`、`power-record.txt`、`power/`。

**本次脑暴采用的写域基线**：只以 L1 §5 白名单为准（可写 = `tir_internal.h/tir_generate.cpp/tir_mtp.cpp/tir_core.cpp(仅 session 状态与生命周期)/tests/tir-api/**/build/run-p1-gate.bat`；只读 = `tir.h、llama.cpp/ggml/common、ABI.md`）。**上述 14 M + 20 ?? 全部视为他人/前任务的未提交改动，不计入本次基线、不修改、不回滚**；本次唯一写入 = `docs/brainstorm/2026-11-10-next-steps.md`。

### 0.4 论文附录 E 与工程现状的不同步项：**附录 E 各条仍成立；不同步集中在正文**

| 附录 E 条目（`99-appendix.md:70-77`） | 裁决 | 证据 |
|---|---|---|
| E:71 30 min 热稳态未测 | **仍成立（未测）** | 全盘无 `*steady*/ *therm*/ *30min*` 结果文件；`build/logs/tp1-gpu-load-2026-11-10.txt` 仅 15 行（09:55–09:56 空闲采样），非稳态测试 |
| E:75 C3 执行记录未回填 | **仍成立** | `docs/blueprints/L2-C3-energy-power.md:6` = `- 状态：待执行`；结果文件 `test/power/results.jsonl` mtime 2026-11-09 19:49:45 |
| E:70 / E:73 白名单外 arch 零覆盖 | **仍成立（未测）** | 无新增测试模型；策略函数 `prefill_batch_for_arch` 为 static、依赖已加载模型（`tir_generate.cpp:27-36`）；A5 蓝图 `:70/:105` 同口径 |
| E:76 ROOT 漂移未修 | **仍成立**，见裁决 0.2 | `run-p0-gate.bat:6` |
| E:77 9B/8B 100 tok/s 未达 | **仍成立** | 9B w2 84.24（`paper.md:1060`）、8B 物理账 17.2 ms/token（封顶 1） |
| E:74 env 回落 5-token 区分力不足 | **仍成立** | `paper.md:639`：1B 6 token `gain=1.28x cross=FAIL`、8B 5 token `gain=2.25x cross=FAIL` |
| （派发单转述）"附录 E 写 A5 未完成" | **转述有误**：附录 E 未列 A5 状态；附录 D `:66` 写"全部完成"；写"未完成"的是正文 | `paper.md:315/:353/:427` vs `99-appendix.md:66`；mtime：paper.md 13:03:08 / paper.docx 13:12:26 / 99-appendix.md 13:02:53 |

**本步净结论**：A5 不用重跑（附录 D 正确、正文过期）；验收链根（ROOT）与写域基线是脏的，须在派发任何 L2 前清账（见 §6）。

---

## 1. 候选表（8 列）

| 编号 | 一句话交付物（可验收） | 打在哪条杠杆 | 物理或数值依据 | 预期收益 | 破不破 fork 只读边界 | 风险 | 能否拆成 L2 |
|---|---|---|---|---|---|---|---|
| **K1** | 9B 两条生成路径同批策略 prefill（plain 默认批 2→512 + MTP prompt 分块），64-token 一致性门在新批下重验；521-token TTFT 实测 ≤500 ms | 杠杆 3 每请求读取次数 + 杠杆 5 一致性预算（D1 工程化、A2 残余） | 显式 `TIR_PREFILL_BATCH=512` 下 9B 521 token `9178.5→266.0 ms, gain=34.51x`（`paper.md:718` → `build/logs/a4-full-9b.raw:12306`）；现状默认 pb=2 TTFT 4799 ms（`paper.md:966`）；pb=2 存在的唯一理由是 plain/MTP 逐位一致（`tir_generate.cpp:23-26`）；MTP 路径 prompt 逐 token prefill（`tir_mtp.cpp:254-269`） | 9B 每请求 TTFT **−4.3 s 以上**（4799→≤500 ms，521 token 口径）；白名单同条件 0.15–0.25 s | 否（`tir_generate.cpp`+`tir_mtp.cpp`+tests 全在 §5:77 写域；不碰 kernel） | **高**：64-token parity 可能从第 2 token 分叉（`tir_generate.cpp:24-26` 预言）；近 tie 翻转有先例（Q4_0 第 38 token，`paper.md:1076`） | **部分**：观测片 K1-a（0 源文件）✓；默认切换片 K1-b（2 源文件但 GPU 验收 >30 min）→ 须完整 L2 蓝图，**不伪装成即时切片** |
| **K2** | `tir_generate_mtp` 补填 `tir_stats` 追加字段 + `bench.c` 打印，把 9B w2 的 27.7 ms/step 分解为 target eval / draft / host 残差三段，并判定 4B 231 vs Nemotron 281 GB/s 缺口在 eval 内还是 eval 外 | 杠杆 4 每步固定开销（D4 的去-nsys 版） | `paper.md:1072`：27.7 = 16.7 权重 + 11 非权重；`paper.md:1003-1004/:1017`：231(76%) vs 281(93%)；**缺口现状**：`tir_mtp.cpp:475-482` 未填 `eval_ms/step_us/graph_*`，`bench.c:23-29` 不打印新字段；而 plain 路径已有全字段工具 `bench_ceiling.c:215-234`（实例 `test/ceiling/results.jsonl:1`）；判读规则 `L2-C0:61-64` | 定位 11 ms 中 host/graph/verify 占比与 50 GB/s 缺口归属；把 9B step 需降的 4 ms（27.7→23.7，`paper.md:1072`）从"猜"变"靶" | 否（`tir_mtp.cpp`+`tests/tir-api/bench.c` 均在写域；只读 `llama_perf_context` 既有 API，`L2-C0:26`） | 低；测量不可信时有 C0 停止条件兜底（`L2-C0:114`） | **✓ 能**：≤30 min、2 源文件、垂直、独立 gate |
| **K3** | env 开关下在 plain 路径逐 token 打印 greedy top1−top2 margin，实测 64-token 对照的翻转点 margin 分布，判定 0.13 位移预算能否覆盖 | 杠杆 5 数值一致性预算（D1 的 oracle） | `tir_internal.h:12-19`：3 行 verify 位移 ~0.13、1–2 行与逐 token 逐位一致；`a5-final-9b.raw:14357` `def_err=34.2 / seq_err=4505.1`（130× 分离）；64-token parity 只在一个 prompt 验过（`paper.md:1076`） | 把「parity 能不能交易」从争论变成数字；为 K1 的门提供 δ；预计 min-margin 与 0.13 的余量倍数 | 否（`tir_generate.cpp` 加 env 打印，stderr-only）；**MTP verify 侧 margin 需动 `common/sampling` → 标「破边界」研究项，不入本候选** | 中：plain 侧 margin 不能直接代表 MTP verify 的 margin | **✓ 能**：≤30 min、1 源文件（plain 侧）；MTP 侧另立研究项 |
| **K4** | 同 session 第二轮不再全量清空重灌：前缀复用省掉重复 prefill（L1-A3 / 外部分析 D3 的会话内简化版） | 杠杆 3 每请求读取次数（交易「每次 generate 必 `llama_memory_clear`」前提） | `tir_generate.cpp:137`、`tir_mtp.cpp:234` 每次 generate 清空整段 KV；A1 已证复用方向有量：cold/warm 328→204 ms（`paper.md:7`）；L1:70 预期多轮 TTFT −50% 以上 | 多轮会话每轮 TTFT −50% 量级（= 被重灌的历史 prompt 长度 × 逐 token 成本） | 否但逼近红线：hybrid SSM 回滚是 L1:70 明示风险 | 高：前缀匹配边界 + SSM 回滚 + 新门；C0 单发口径不产生该收益，须新造多轮 gate | **✗ 不能** → 标**研究项**（拆不出 ≤30 min 垂直片） |

### 1.5 必答四问

**问 1：三个前提哪个最值得先交易？——顺序：逐位 parity ≫ 每次 `llama_memory_clear` > nextn 依赖。**

1. **逐位 parity（先交易，对应 K1+K3）**：
   - 数值空间：pb=2 是被 parity 锁的（`tir_generate.cpp:23-26`），其代价实测为 9B prefill 只拿 1.92×（`a5-final-9b.raw:14357`），而四个无 nextn 白名单模型同门槛拿 30.95–32.49×——**16 倍以上的 prefill 吞吐留在桌上**；显式 pb=512 已实测 `9178.5→266.0 ms`（`a4-full-9b.raw:12306`）。
   - 安全垫（可交易的物理依据）：A5 判据 `def_err=34.2` vs `seq_err=4505.1` 分离 **130×**（`a5-final-9b.raw:14357`）；批引起的位移是 ~0.13 的固定量（`tir_internal.h:17`）、只翻近 tie；1–2 行与逐 token 逐位一致是已实测结论（`tir_internal.h:18`）。交易对象是「prefill 数值=逐 token 参照」这一布尔量，可用 margin/def_err 预算替代（K3 负责把预算测出来）。
2. **每次 generate 的 `llama_memory_clear`（第二交易，K4）**：收益只在多轮会话兑现，且单发 C0 bench 根本不产生该收益；需要 A3 全套机器（前缀匹配 + hybrid SSM 回滚，`L1:70`），侵入最大而收益尚无本仓实测 → 排第二但标研究项。
3. **nextn 依赖（绝不先交易）**：丢 MTP 即 9B 从 84.24 → plain 约 51 tok/s（`paper.md:1064`），**−39% decode**，且 w2 是 100 计划唯一在跑的主路径（`paper.md:1076`）——交易它等于关掉杠杆 2 上仅剩的战果。

**问 2：9B 521-token TTFT 4.8 s 与 84.24→100 tok/s，哪个值钱？——TTFT，按 C0 128-token 口径约值 19 倍。**

- TTFT 账：4799 ms（`paper.md:966`）→ 目标 ≤500 ms（pb=512 已实测 266.0 ms 档），**每请求省 ≈4.3 s**。
- tok/s 账：84.24→100 在 C0 128-token 口径下 `128/84.24=1519 ms → 128/100=1280 ms`，**每请求省 0.24 s**；即使按 500-token 长生成算也只省 `5936→5000 = 0.94 s`。
- 频次账：一轮对话必付一次 TTFT（10 轮会话 TTFT 共省 ≈43 s，128-token/轮 decode 共省 ≈2.4 s → **≈18–19×**）；decode 省时仅随生成长度线性增长，TTFT 是「零输出等待」，感知权重还更高。
- 侵入账：100 tok/s 需要 step 27.7→23.7 ms，即从**尚未归因的 11 ms** 里再砍 4 ms（`paper.md:1072`），触碰 verify/draft/回滚调度甚至 kernel；TTFT 只动 prefill 批策略，全在写域内。**结论：先做 TTFT（K1），decode 侧等 K2 归因出靶点。**

**问 3：拿不到 nsys，能否只动调度层定位 11 ms 与 231/281 缺口？——能，三组实验（两组 0 源文件、一组 = K2 正片），均不碰 kernel。**

- **E0（0 源文件，答 231 vs 281）**：plain 路径用现成 `tir-bench-ceiling`（已输出 `eval_ms/step_us/sampler_ms/graph_*`，`bench_ceiling.c:215-234`）：
  ```bat
  build\build-tir-api.bat
  build\tir-api\bin\tir-bench-ceiling.exe <WORKSPACE>\artifacts\qwen35-4.2b-IQ4_XS.gguf 8192 4096 128 1 3 >> build\logs\k2-e0-4bqwen.raw
  build\tir-api\bin\tir-bench-ceiling.exe <MODEL_DIR>\bionic\lmstudio-community\NVIDIA-Nemotron-3-Nano-4B-GGUF\NVIDIA-Nemotron-3-Nano-4B-Q4_K_M.gguf 8192 4096 128 1 3 >> build\logs\k2-e0-nemotron.raw
  ```
  期望输出：各一行 `{"schema":"tir.ceiling/v1",...}`，含 `eval_ms`、`step_us`、`graph_reallocs_same/diff`。判读（`L2-C0:61-64`）：`host_ms = (step_us − eval_ms*1000 − sampler_ms*1000 − detok_us − callback_us)/1000`——若两模型 host_ms 差 <1 ms/step 而 eval_ms 差约 `(11.70−10.10)×128≈205 ms`（`paper.md:1003-1004`），**缺口在 eval 内（GPU/kernel 侧），调度层无肉，如实标研究项**；若 eval 接近而 host/graph 一侧差 >2 ms/step 或一侧 `graph_reallocs_diff>0`，**缺口在调度层，K2 继续挖**。
- **E1（0 源文件，答 11 ms 的 draft 份）**：MTP draft 前向已有 env 开关（`tir_mtp.cpp:484-494`）：
  ```bat
  set TIR_SPEC_DEBUG=1
  build\tir-api\bin\tir-bench.exe <WORKSPACE>\artifacts\qwen9b-Q4_K_M.gguf 16384 1 128
  ```
  期望输出（stderr）：`tir-spec: drafted=… accepted=… steps=…` 与 `tir-spec: draft eval_ms=… n_eval=…`；draft 每步成本 = `draft eval_ms / steps`，直接与 11 ms 对照（C0 128 token、Q4_K_M、w2 环境即 84.24 口径）。
- **E2（=K2 正片，2 源文件，答 11 ms 的 target/host 份与 verify 批形状）**：给 `tir_generate_mtp` 补填 `eval_ms/prompt_eval_ms/sampler_ms/step_us/detok_us/callback_us/graph_*`（读 `llama_perf_context(s->ctx)`，与 plain `tir_generate.cpp:228-236` 同源）+ `bench.c` 打印：
  ```bat
  build\build-tir-api.bat
  build\tir-api\bin\tir-bench.exe <WORKSPACE>\artifacts\qwen9b-Q4_K_M.gguf 16384 1 128
  ```
  期望输出：每个 run 行新增 `eval_ms>0`、`step_us/1000 ≈ decode_ms`（误差 ≤5%，验收抄 `L2-C0:108`）。分解式：`step_ms = target_eval_ms + draft_ms(E1) + sampler_ms + detok + callback + host_residual`，其中 `host_residual = (step_us − eval_ms*1000 − sampler_ms*1000 − detok_us − callback_us)/1000 ≥ 0`。verify 批形状用既有 env 对照（`tir_core.cpp:50-57`）：`TIR_MTP_N_MAX=1` vs `=2` 各跑一遍，`eval_ms/step` 差 = 3 行 verify 的边际成本；`graph_reallocs_diff>0` 则 capture 范围是首嫌疑。**全程不碰 kernel、不装 nsys。**
- `prompt_eval_ms` 在 MTP 路径补填后还会顺带给出**逐 token prefill 的 TTFT 分解**（K1-a 的证据，一石二鸟）。

**问 4：哪个能拆成「≤30 min、≤2 源文件、垂直、独立 gate」的 L2？**

| 候选 | ≤30 min | ≤2 源文件 | 垂直 | 独立 gate | 裁决 |
|---|---|---|---|---|---|
| K2 | ✓ | ✓（`tir_mtp.cpp` + `bench.c`） | ✓（只加测量不改行为） | ✓（JSON 字段断言，抄 `L2-C0:107-108`） | **L2，首选派发** |
| K3 | ✓ | ✓（`tir_generate.cpp` 1 个） | ✓（stderr-only） | ✓（min-margin 报告 + 判读行） | **L2，随 K2 批** |
| K1-a 观测片 | ✓ | ✓（0 源文件，纯 env） | ✓ | ✓（TTFT 数字对基线） | **L2（测量片），先跑** |
| K1-b 默认切换 | ✗（5 模型矩阵 + 变异 >30 min） | ✓（2 源文件） | ✓ | ✓ | **须完整 L2 蓝图再派发**（L0→L1→L2 不跳级） |
| K4 | ✗ | ✗（前缀匹配+回滚+新门） | ✗ | ✗ | **研究项，不伪装成切片** |

---

## 2. 候选七项展开（按项目七项派发单）

### K1 —— 9B 双路径同批 prefill：把 TTFT 从 4.8 s 拉回亚秒

1. **交付物一句话**：9B（qwen35+nextn）在 plain 与 MTP 两条路径上用同一分块策略 prefill，默认批 2→512，521-token TTFT 实测 ≤500 ms，64-token 一致性门在新批下给出判据明确的 GREEN 或按停止条件退回。
2. **切片检查表（六行）**：
   - [ ] ≤30 分钟：K1-a 观测片是（0 源文件）；**K1-b 默认切换否**（GPU 五模型 + 变异 >30 min，须完整蓝图）
   - [ ] ≤2 源文件：K1-b = `tir_generate.cpp` + `tir_mtp.cpp`（门若需改断言再 +1 test 文件，超限则砍）
   - [ ] 垂直切片：只做「prefill 批策略 + 一致性判据」，不做采样/模板/缓存
   - [ ] 不按横向阶段切：一次交付「批策略 + 门 + 数字」三件套
   - [ ] 独立验收：`tir-test-mtp` + `tir-bench ttft_ms` 自成闭环
   - [ ] 写域不重叠：仅 §5:77 白名单两个源文件，与 K2（`bench.c`）不重叠
3. **写域逐文件白名单**：`src/llama.cpp-fork/src/tir-api/tir_generate.cpp`（prefill_batch_for_arch 默认值）、`src/llama.cpp-fork/src/tir-api/tir_mtp.cpp`（prompt prefill 循环 `:254-269` 分块化）；可选 `tests/tir-api/test_mtp.c`（判据）。K1-a 观测片**零写入**。
4. **读域与禁触**：读 `tir.h`（不改，ABI 冻结）、`llama.cpp/ggml/common`（只读）、`test/mtp-stability.mjs`（他人未提交，只读参考）；禁触 kernel、`TIR_PREFILL_BATCH` 语义保留为逃生舱（`tir_generate.cpp:42-53`）、不碰 `common/speculative.cpp` 的既有未提交改动。
5. **设计与接口契约**：不改 ABI；行为变更 = nextn 架构默认批 2→512 + MTP prompt 按同批切块（最后 token 仍留作首行，保 `tir_mtp.cpp:250-251` 的「首样本来自 id_last」不变量）；parity 语义从「prefill=逐 token 参照」改为「plain vs MTP 在 64-token 上过 A5 同款判据（match/parity/def_err≪seq_err）」；分歧必须能被 `def_err` 或 K3 的 margin 解释，否则退回 pb=2。
6. **可运行验收（≥2 命令 + 期望输出）**：
   ```bat
   rem ① RED 基线：现行代码 + env 提批，证明问题真实且门活着（见 §4 变异）
   set TIR_PREFILL_BATCH=512
   build\tir-api\bin\tir-test-mtp.exe
   rem 期望（现状）：RC=1、parity=分叉报告（tir_generate.cpp:24-26 预言的第 2 token 起不一致）
   rem ② GREEN：K1-b 实施后，不设 env
   build\tir-api\bin\tir-test-mtp.exe
   rem 期望：RC=0，plain=64 mtp=64 parity=64 或预算门 PASS 且分歧均满足 def_err 判据
   build\tir-api\bin\tir-bench.exe <MODEL_DIR>\bionic\Qwen\Qwen3.8-9B-Distill-GGUF\Qwen3.8-9B-Q5_K_M.gguf 16384 1 128
   rem 期望：JSON ttft_ms ≤ 500（基线 4799，paper.md:966）；tok_s_avg 不劣于基线 −2%
   ```
7. **停止条件与回收格式**：① 64-token 分叉无法用 def_err/margin 解释（出现「翻转点 margin ≥ 实测位移」）→ 退回默认 2 并判死该路线；② 需要改 `tir.h`、动 `common/` 或写清单外文件 → 停；③ GPU 显存/温度冲突（余量 544 MiB）→ 停；④ 任一非 9B 白名单模型回归 → 停。回收：只更新本文件 K1 状态 + `build/logs/k1-*.raw` 只追加，不产生第二份交付物。

### K2 —— MTP 遥测补齐与 11 ms 非权重归因门

1. **交付物一句话**：9B w2 一次 C0 跑出可分解的 step 账本（target eval / draft / host 三段），4B qwen vs Nemotron 的 50 GB/s 缺口给出「eval 内 / eval 外」判定，全部落成一条可回归的 JSON gate。
2. **切片检查表（六行）**：
   - [x] ≤30 分钟（只加字段填充与打印，行为零变更）
   - [x] ≤2 源文件（`tir_mtp.cpp` + `bench.c`）
   - [x] 垂直切片（一条 9B w2 的账本走到底）
   - [x] 不按横向阶段切（测量、判读、门槛一次交付）
   - [x] 独立验收（JSON 字段断言，不依赖其它候选）
   - [x] 写域不重叠（不碰 K1 的 prefill 策略段）
3. **写域逐文件白名单**：`src/llama.cpp-fork/src/tir-api/tir_mtp.cpp`（循环内 step 计时 + 结束时 `llama_perf_context(s->ctx)` 填 `tir_stats` 追加字段）；`src/llama.cpp-fork/tests/tir-api/bench.c`（`dump_stats`/stdout JSON 追加字段，`run-p0-gate.bat:65-71` 按 key 解析、追加安全）。
4. **读域与禁触**：读 `tir.h:87-96`（append-only 字段定义，不改）、`llama.h` `llama_perf_context`（`L2-C0:26`）、`L2-C0` 判读规则；禁触 `common/sampling`（draft 内部）、kernel、CUDA graph API 本体（只读计数器）、他人未提交的 `common/speculative.cpp`。
5. **设计与接口契约**：不改 ABI（复用已追加字段）；新增输出仅 stdout JSON 追加键（schema `tir.p0-gate/v1` 保持既有键不动）与 stderr `tir-spec:` 行（既有格式 `tir_mtp.cpp:485`）；判据：`step_us/1000` 与 `decode_ms` 相对差 ≤5%、`eval_ms ≤ decode_ms×1.05`、`host_residual ≥ 0`（抄 `L2-C0:108`）。
6. **可运行验收（≥2 命令 + 期望输出）**：
   ```bat
   build\build-tir-api.bat
   rem ① 9B w2 账本（84.24 / 27.7ms 同口径）
   set TIR_SPEC_DEBUG=1
   build\tir-api\bin\tir-bench.exe <WORKSPACE>\artifacts\qwen9b-Q4_K_M.gguf 16384 1 128
   rem 期望：RC=0；run 行含 eval_ms>0、step_us/1000≈decode_ms(≤5%)；stderr 含 tir-spec: draft eval_ms=…
   rem ② 4B 结构对照（231 vs 281 归属判定）
   build\tir-api\bin\tir-bench-ceiling.exe <WORKSPACE>\artifacts\qwen35-4.2b-IQ4_XS.gguf 8192 4096 128 1 3
   build\tir-api\bin\tir-bench-ceiling.exe <MODEL_DIR>\bionic\lmstudio-community\NVIDIA-Nemotron-3-Nano-4B-GGUF\NVIDIA-Nemotron-3-Nano-4B-Q4_K_M.gguf 8192 4096 128 1 3
   rem 期望：各一行合法 JSON；输出 host_ms 与 eval_ms 差值对照表（E0 判读规则），缺口归属写成一句话结论
   ```
7. **停止条件与回收格式**：① `step_us/1000` 与 `decode_ms` 差 >5% 或 `eval_ms` 恒 0 且无法用填充 bug 解释 → 停，按 `L2-C0:114` 改 CUDA event 测量（研究项）；② 需要动 `common/` 或 kernel → 标破边界另行立卡；③ 需要改 `tir.h` 字段顺序 → 停（ABI 冻结）。回收：更新本文件 K2 状态 + `build/logs/k2-*.raw` 只追加。

### K3 —— greedy margin 观测 oracle（0.13 位移预算测量）

1. **交付物一句话**：`TIR_MARGIN_DEBUG=1` 下 plain 路径逐 token 输出 top1−top2 margin，给出 128-token 实测 min-margin 与全部翻转点 margin，一句话判定 K1 的预算门 δ 可行与否。
2. **切片检查表（六行）**：
   - [x] ≤30 分钟（env 分支 + stderr 打印 + 统计行）
   - [x] ≤2 源文件（`tir_generate.cpp` 1 个）
   - [x] 垂直切片（一个数字：min margin vs 0.13）
   - [x] 不按横向阶段切
   - [x] 独立验收（输出自带判读行）
   - [x] 写域不重叠（与 K2 的 `bench.c`、K1-b 的 MTP 侧不同文件段）
3. **写域逐文件白名单**：`src/llama.cpp-fork/src/tir-api/tir_generate.cpp`（采样点取 `llama_get_logits_ith(ctx,-1)` 的 top1−top2，env 关闭时零开销零输出）。
4. **读域与禁触**：读 `llama.h` logits API（只读）；**禁触** `common/sampling.h`/`common_speculative`——MTP verify 的 margin 在只读域内取不到，该半边标「破边界」研究项，不写进本候选。
5. **设计与接口契约**：不改 ABI（stderr-only，不进 `tir_stats`；若未来要进 JSON，按 L1:42 末尾追加并先改 `ABI.md`）；输出格式固定 `tir-margin: idx=<i> m=<f> flip=<0|1>`；与 `TIR_PREFILL_BATCH` 正交组合可跑对照。
6. **可运行验收（≥2 命令 + 期望输出）**：
   ```bat
   build\build-tir-api.bat
   rem ① 基线 margin 分布（逐 token prefill 参照）
   set TIR_MARGIN_DEBUG=1
   build\tir-api\bin\tir-bench.exe <WORKSPACE>\artifacts\qwen9b-Q4_K_M.gguf 16384 0 128 2>&1 | findstr tir-margin
   rem 期望：128 行 idx=0..127，末行 tir-margin: min=<m> (0.13 参照: <倍数>x)
   rem ② 提批下的对照：翻转点定位
   set TIR_PREFILL_BATCH=512
   build\tir-api\bin\tir-bench.exe <WORKSPACE>\artifacts\qwen9b-Q4_K_M.gguf 16384 0 128 2>&1 | findstr tir-margin
   rem 期望：翻转 token（若有）的 m 值被打印；判读=全部 flip 的 m < 实测位移 → 预算可行
   ```
7. **停止条件与回收格式**：① 读 logits 需要越过写域 → 停；② MTP 侧需求出现 → 另立破边界研究项，不扩本片；③ 输出证明预算不可行 → 直接回填 K1 停止条件①。回收：更新本文件 K3 状态 + `build/logs/k3-*.raw` 只追加。

### K4 —— 会话内前缀复用（交易 `llama_memory_clear` 前提）【研究项】

1. **交付物一句话**：（研究项，不派发）先回答「同 session 第二轮若复用前缀，理论上能省多少 TTFT」——即用现有多轮测试实测第二轮全量重灌的代价上界。
2. **切片检查表（六行）**：≤30 min ✗（正确性机器：前缀匹配、SSM 回滚、多轮 gate 全缺）；≤2 源文件 ✗；垂直 ✗；不横向切 ✗；独立验收 ✗（C0 单发口径不适用）；写域不重叠 △ → **整体判研究项**。
3. **写域逐文件白名单**（若未来立项）：`tir_generate.cpp`/`tir_mtp.cpp`/`tir_core.cpp`（session 状态，§5:77）+ 新 `tests/tir-api/test_multiturn.c`。
4. **读域与禁触**：`llama_memory_*` 语义只读求证；禁触 hybrid 回滚相关 kernel 与 `common/`（除非立破边界卡）。
5. **设计与接口契约**：研究阶段不定义接口；只冻结问题——「第二轮 TTFT 能否 < 第一轮 × 50%」。
6. **可运行验收（研究探针，当前标未测）**：
   ```bat
   rem 探针：test_chat 双轮调用，若输出不含 ttft_ms 则以 tir_stats_snapshot 另取；当前未测
   build\tir-api\bin\tir-test-chat.exe
   rem 期望（研究假设，未验证）：第二轮 ttft_ms ≈ 第一轮 × prompt 比例
   ```
7. **停止条件与回收格式**：① 实测第二轮仅省 <10% → 判死；② 需动只读域 → 破边界另行立卡；③ 显存不足（7607 MiB 常驻，`99-appendix.md:72`）→ 停。回收：只在本文件 K4 行补「研究结论/判死」，不产出代码。

---

## 3. 证伪清单（什么数字出现就判死 + 最小验证命令）

| 候选 | 判死条件 | 最小验证命令 |
|---|---|---|
| K1 | 出现「pb=512 下 64-token greedy 分叉，且分叉 token 的 margin ≥ 实测位移（≈0.13，`tir_internal.h:17`）或 def_err 落到 seq_err 的 0.5 附近」→ 预算化不可行，默认批退回 2 | `set TIR_PREFILL_BATCH=512` → `build\tir-api\bin\tir-test-mtp.exe` → 读 RC 与 K3 的 `flip` 行 |
| K2 | 出现 `step_us/1000` 与 `decode_ms` 相对差 >5%，或 9B w2 补填后 `eval_ms` 仍恒 0 → 测量体系不可信，判死本方案、转 `L2-C0:114` 的 CUDA event 研究项 | `build\tir-api\bin\tir-bench.exe <WORKSPACE>\artifacts\qwen9b-Q4_K_M.gguf 16384 1 128` 读 run 行三个字段 |
| K3 | 出现「翻转点 margin ≥ 0.13」的样本，或 128-token min-margin 与 0.13 之比 <2（余量不足 2×）→ margin 预算判死，连带 K1 判据退回逐位门 | `set TIR_MARGIN_DEBUG=1` + `set TIR_PREFILL_BATCH=512` → `tir-bench … 16384 0 128 2>&1 \| findstr tir-margin` |
| K4 | 实测同 session 第二轮 TTFT 相对第一轮省 <10% → 前缀复用判死（研究项直接关） | 研究阶段：双轮 `tir-test-chat`/`tir_stats_snapshot` 对照（当前**未测**） |
| E0（K2 前置） | 4B qwen 与 Nemotron 的 `host_ms` 差 <1 ms/step 且缺口全部落在 `eval_ms` → 「调度层修 50 GB/s」判死，缺口归 kernel/结构（标破边界研究项，不许写成默认路径） | 上文 E0 两条 `tir-bench-ceiling` 命令 |

---

## 4. 排序（收益 ÷ 侵入度）与前两名变异测试

**排序**：

1. **K2**（收益=归因 11 ms + 50 GB/s 并解锁后续一切手术；侵入=2 源文件、零行为变更、有 C0 停止条件兜底 → 比值最高）
2. **K1**（收益最大且用户可感：−4.3 s/请求；但侵入=改默认行为+重定义一致性判据，必须带着 K3 的数字才许动 → 比值第二）
3. **K3**（成本极低，但单独立收益有限——它是 K1 的前置探针，随 K2 同批派发）
4. **K4**（研究项：收益上界大但无实测、机器不齐、无法 ≤30 min 垂直切）

**K2 变异测试（先 RED 后 GREEN）**：

- **RED（证明门会叫）**：临时让 `tir_mtp.cpp` 的新增填充不执行（`eval_ms` 保持 0）→ 跑验收命令① → 新 gate（断言 `eval_ms > 0 && step_us/1000 与 decode_ms 差 ≤5%`，判据抄 `L2-C0:108`）必须 **RC=1** 且输出含 `eval_ms=0`。预期日志：`build/logs/k2-mutant-noeval-9b.raw`。
- **RED 变体（防字段错位）**：让 `bench.c` 把 `step_us` 打成 `callback_us` → 断言 `step_us/1000 ≥ eval_ms` 应 **RC=1**（呼应 `run-p0-gate.bat:65-71`「按 key 解析防字段挪位」的既有教训）。
- **GREEN**：恢复后同命令 **RC=0**，9B w2 run 行 `eval_ms>0`、`step_us/1000 ≈ decode_ms`（≤5%）、`host_residual ≥ 0`，E0 两模型各产出一行合法 JSON 并写出缺口归属结论。预期日志：`build/logs/k2-final-9b.raw`、`k2-e0-*.raw`。

**K1 变异测试（先 RED 后 GREEN）**：

- **RED（证明旧门活着、问题真实）**：现行代码下 `set TIR_PREFILL_BATCH=512` → `tir-test-mtp.exe` → 期望 **RC=1、parity 分叉**（`tir_generate.cpp:24-26` 已预言「plain 提到 512 从第 2 token 起失去一致性」）。这一红证明：① 逐位门不是摆设；② K1 的风险真实存在。预期日志：`build/logs/k1-mutant-pb512-9b.raw`。
- **RED（防橡皮图章，两发）**：K1-b 新门上线后，(a) 把预算 δ 置 0（等价退回逐位）→ 同上命令应再次 **RC=1**；(b) 把新门 oracle 改成「恒判安全」→ 64-token id 对照必须仍能抓到已知翻转配置而 **RC=1**。两发任一失败 = 新门是橡皮图章，禁止 GREEN。
- **GREEN**：K1-b 实施后不设 env，`tir-test-mtp` **RC=0** + `tir-bench … 16384 1 128` 的 `ttft_ms ≤ 500`（基线 4799，`paper.md:966`）且 `tok_s_avg` 不劣于基线 −2%；`tir-test-prefill` 五模型矩阵全部 `match=OK`。预期日志：`build/logs/k1-final-9b.raw`。

---

## 5. 明确不做的方向（每条一句话原因）

1. **8B 100 tok/s**：5.03 GB/token ÷ 292 GB/s = 17.2 ms，100 需 10 ms——物理封死（封顶 1）。
2. **Q3/IQ4_XS/Q4_0 作通用低比特路径**：80.8 t/s 与 90.32 vs 90.48 证明无净收益，Q4_0 在 64-token parity 第 38 token 分叉（封顶 2）。
3. **盘当内存/显存**：5.56 GB/s 折算 1.1–2.1 t/s，4 KB 随机仅 44.8 MB/s（封顶 3）。
4. **外挂 draft 模型**：0.8B 前向 15–20 ms > target 一步 10.9 ms，61.8 vs 90.5 t/s 反劣（封顶 4）。
5. **ngram 作通用默认**：自然英文段落 −3%（封顶 5）。
6. **MTP width 3**：76.94 < w2 的 84.24（封顶 6）。
7. **多 session / 连续批处理**：9B+MTP 常驻 7607 MiB、余量 544 MiB，无第二消费者空间（封顶 7）。
8. **TIR-C 自研运行时**：已逐项账务废止（封顶 8）。
9. **白名单外 arch 猜测性优化**：该分支零测试覆盖，先补测试模型（封顶 9 + 附录 E:70/:73）。
10. **直接投 nsys 逐 kernel 归因（D4 原版）**：拿不到工具且超写域——K2/E0 是它的去工具化替代，不是放弃归因。
11. **D3 状态快照池 / D2 自投机 / D5 运行点闭环**：D3 同封顶 7；D2 在 11 ms 未归因前无法证伪收益；D5 属 C3 蓝图与 30 min 稳态欠账（`L2-C3-energy-power.md:6` 待执行），是还债不是突破候选。
12. **本文件内修正论文正文**：正文 `paper.md:315/:353/:427` 过期是裁决 0.4 的事实，但本次只交付脑暴 md，论文修改不在写域与任务内。

---

## 6. 被中断时的回收点

- **第 0 步四项裁决（§0）已完整**：中断即可回收，后文候选未完成的不补写、不猜测。
- 回收后落点（按派发单 §回收后的落点，均有本文件证据支撑）：
  1. **先修 `build/run-p0-gate.bat:6` 的 ROOT 漂移**并核对两树 `tir.dll` 哈希（裁决 0.2）——否则后续所有 gate 数字可能来自另一棵树。
  2. **固定写域基线**：处置 14 M + 20 ??（打 tag 或归档），特别是越界的 `common/speculative.cpp` 与合规追加的 `tir.h`（裁决 0.3），再派发任何 L2。
  3. **K2 + K3 写成正式 L2 蓝图**（首选，L0→L1→L2 不跳级），K1-a 观测片同步跑出 MTP 路径 521-token TTFT 基线，K1-b 待 K3 数字出来再立卡。
  4. **变异一律先 RED**；日志按 `build/logs/切片-模型-配置.raw` 只追加，不覆盖。
  5. 论文正文 A5 状态修正、30 min 稳态、C3 回填列入还账清单，不混进脑暴候选。
