# TIR-A: 8 GiB 显存下的 Windows 本地推理引擎

**llama.cpp fork + 14 函数 C ABI，面向单用户、单卡、进程内调用。**

> TIR-A 是一个跑在 8 GiB 显存 Windows 笔记本上的进程内推理引擎：9B MTP 84 tok/s，非 MTP 模型 520-token 首 token 41–245 ms。仓库包含完整技术论文（46,925 汉字）、8 张实测数据图与可重建的 DOCX/PDF。

**状态：工程验证版。** 单用户、单模型常驻；不是多人并发服务，也不是“多模型热切换”产品。所有数字都来自一台固定机器上的实测，换机器不能直接外推。

---

## 1. 它是什么

- Windows x64 上的 `tir.dll`，对外 14 个 C 函数、8 个结构体；宿主用 Python `ctypes`、Node `koffi`、C# `P/Invoke` 或 C 直接调用。
- 基于 llama.cpp fork，保留 `llama.h` 与 ggml/CUDA 后端；`tir-api` 负责生命周期、会话、生成、MTP、chat template。
- 支持 1B–9B GGUF，q4 KV，CUDA 13.5，RTX 5060 Laptop 8 GiB。
- 两条生成路径：plain decode 与 MTP 投机 decode；分块 prefill 默认批 512（带 nextn 头的模型默认 2）。

## 2. 它不是什么（硬边界）

| 不是 | 原因 |
|---|---|
| 多人并发 / 多 session | 9B + MTP 峰值 7607 MiB，8 GiB 卡只剩约 544 MiB；第二个 session 放不下 |
| 多模型动态切换 | 当前一个 `tir_engine` 只常驻一个模型；切换要销毁并重建 engine/session，未实现热切换 |
| 8B 100 tok/s | 5.03 GB/token ÷ 292 GB/s ≈ 17.2 ms/token；100 tok/s 要求 10 ms，Q4 权重物理上不允许 |
| 9B 100 tok/s | 实测 84.24 tok/s；27.7 ms/step，要 100 需 ≤23.7 ms，差 4 ms 在 3-row verify 与回滚 |
| 把磁盘当显存 | E 盘直接 I/O 5.10 GB/s，只够做容量层；30B 约 0.43 tok/s |

## 3. 实测结果

固定条件：Windows 11、RTX 5060 Laptop 8 GiB（8151 MiB）、i7-14650HX、15.7 GiB DDR5、115 W 电源；q4 KV；除非注明，生成 128 token。

### 3.1 Decode

| 模型 | 配置 | tok/s | 说明 |
|---|---|---:|---|
| 1B MiniCPM5 | C0，317 prompt，64 gen | 308.3 | 受 host 与 kernel 共同限制 |
| 4B qwen3.5 | C0，322 prompt，128 gen | 81.8–85.9 | 有效读带宽 231 GB/s，约 76% |
| Nemotron 4B | C0，329 prompt，128 gen | 95.1–96.7 | 281 GB/s，约 93% |
| 8B DSR1 | C0，322 prompt，128 gen | 57.1 | 292 GB/s；功耗/显存墙 |
| 9B plain | 16k q4，128 gen | 50.84 | llama.cpp 同条件 51.81 |
| 9B MTP w1 | Q5_K_M，16k q4 | 74.8 | acceptance 0.855，mean_len 1.855 |
| 9B MTP w2 | Q4_K_M，16k q4 | **84.24** | acceptance 0.685，mean_len 2.370，64-token parity |
| 9B MTP w3 | Q4_K_M，16k q4 | 76.94 | mean_len 2.723，4-row verify 更贵 |

### 3.2 520-token 首 token（TTFT）

| 模型 | 逐 token prefill | 默认批 512/2 | 收益 |
|---|---:|---:|---:|
| 1B | 1219.7 ms | 41.5 ms | 29.36× |
| 4.2B qwen3.5 | 4943.6 ms | 158.9 ms | 31.11× |
| Nemotron 4B | 4389.3 ms | 145.3 ms | 30.21× |
| 8B DSR1 | 7788.2 ms | 245.3 ms | 31.75× |
| 9B（MTP，默认 2） | 9168.6 ms | 4799.0 ms | 1.91× |

9B 因为带 nextn 头，默认批保持 2，以保证 plain 与 MTP 的 target 数值起点一致；它的 prefill 收益因此只有 1.91×。

### 3.3 功耗与能效

| 模型 | 平均功耗 | 温度峰值 | decode 能效 |
|---|---:|---:|---:|
| 4B qwen | 85.3 W | 69 °C | 0.9295 tokens/J |
| 8B DSR1 | 95.78 W | 74 °C | 0.5736 tokens/J |
| 9B llama-bench | 104.65 W | 74 °C | — |
| 9B tir-bench MTP | 98.24 W | 64 °C | — |

功耗上限 115 W；实测峰值 109.28 W，余量约 5%。这不是温度墙，是功耗/带宽墙。

## 4. 为什么这些数字可信

1. **同轮校准**：C0 用同一构建、同一轮次、真实上下文、带 GPU 遥测重测了 1B/4B/8B，推翻了早期串行跑出的“92/64”。
2. **五模型矩阵**：1B、4.2B、Nemotron 4B、8B、9B 都跑 520 token，指标固定为 token parity、TTFT 收益、默认值画像。
3. **门禁会失败**：A5 用变异测试证明旧断言在“默认批 2 退回 1”时会全绿；新判据 `def_err < 0.5 * seq_err` 会红（`def_err=34.2` 对 `seq_err=4505.1`）。一个不会失败的测试等于没有测试。
4. **失败照实写**：ngram 只在重复文本有效、draft-simple 前向太贵、Q3/IQ4_XS 无收益、Q4_0 在 9B 上 token 38 parity 失败、TIR-C 自研运行时废止。

## 5. 仓库结构

```
.
├── README.md
├── LICENSE                     # MIT
├── CITATION.cff
├── paper/
│   ├── paper.md                # 论文主稿（46,925 汉字）
│   ├── paper.pdf               # 115 页
│   ├── paper.docx              # 含目录，可在 Word 中更新
│   ├── figures/                # 8 张 SVG + PNG，数据可追溯
│   └── build_docx.py           # Markdown → DOCX
└── docs/
    ├── roadmap.md              # 后续设计（标注：未实现）
    └── evidence-index.md       # 论文引用路径与来源说明
```

论文中的本机绝对路径已替换为 `<MODEL_DIR>`、`<TIR_ROOT>`、`<WORKSPACE>`；原始日志与模型清单不随仓库发布。

## 6. 重建论文

```bash
cd paper
python build_docx.py paper.md paper.docx
# DOCX 目录域在 Word 中打开时更新；PDF 可用 LibreOffice/Word 导出
python figures/gen_figures.py   # 重新生成 8 张 SVG（纯标准库）
```

依赖：Python 3.10+、`python-docx`；图表只用标准库。PDF 由 DOCX 导出。

## 7. 路线图

见 [docs/roadmap.md](docs/roadmap.md)。四条都标注了“设计，未实现”：

1. `ModelTraits`：把架构白名单从代码常量改成 GGUF metadata 驱动。
2. OpenAI 兼容层：`/v1/chat/completions` + SSE，包装 `tir_session_generate`。
3. 多轮 KV/前缀复用：trim 到公共前缀，只 prefill 增量（当前每次 generate 都清空 memory）。
4. 9B 3-row verify 优化：把 step 从 27.7 ms 压到 24 ms 以下。

多模型热切换不在当前路线图内：8 GiB 显存下，9B + MTP 已占 7607 MiB，切换必须先完整卸载再加载，代价与风险都未验证。

## 8. 引用与许可

- 引用信息：[CITATION.cff](CITATION.cff)
- 许可证：MIT，Copyright (c) 2026 TIR-A contributors

---

## English abstract

TIR-A is an in-process local inference engine for a single Windows laptop with an 8 GiB RTX 5060 Laptop GPU. It exposes a 14-function C ABI over a llama.cpp fork, supports 1B–9B GGUF models with q4 KV, and combines MTP speculative decoding with chunked prefill. Measured results: 9B Q4_K_M + MTP width 2 reaches 84.24 tok/s with 64-token parity; 4B runs at 82–86 tok/s, Nemotron 4B at 95–97, 8B at 57.1, and 1B at 308. For a 520-token prompt, TTFT drops to 41–245 ms on non-MTP models via a default prefill batch of 512, while MTP models keep a batch of 2 to preserve numerical parity. The report also documents the hardware limits: an 8B model cannot reach 100 tok/s at Q4 under 292 GB/s effective bandwidth, 9B tops out near 84 tok/s, and multi-session serving does not fit in 8 GiB. All numbers come from one fixed machine and include the failed paths, not just the wins.
