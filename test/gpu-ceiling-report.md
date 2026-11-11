# RTX 5060 Laptop 8GB 性能上限调查

- 日期：2026-11-09
- 机器：i7-14650HX / 15.7 GB RAM / RTX 5060 Laptop 8 GB / PCIe Gen5 x8 / 驱动 616.92
- 方法：nvidia-smi 遥测 + llama-bench + llama-server（b12202）对照；同一模型、同一 prompt、greedy
- 结论：**硬件接近功耗/带宽墙，但软件层仍有 1.6–2.2x 的确定性增益——MTP 投机解码。** 当前 B1 的 20 tok/s 目标已被 MTP 在 16k 下以 53–78 tok/s 超过。

---

## 1. 硬件天花板

| 项 | 实测 | 含义 |
|---|---|---|
| VRAM | 8151 MiB；空闲 6443 MiB | 8 GB 容量是模型大小的硬上限 |
| 显存总线 | 128-bit（RTX 5060 Laptop） | 带宽上限约 384–448 GB/s，取决于 24/28 Gbps |
| 功耗 | 当前上限 **94.12 W**；默认 50 W；**最大 115 W** | 满载 81–91 W，**功耗墙**；温度仅 51–56°C，不是温度墙 |
| 显存时钟 | 满载 12001 → **11001 MHz** | 功耗管理导致约 8% 带宽下降 |
| 图形时钟 | 满载 2.5–2.6 GHz；最大 3090 MHz | 受功耗限制 |
| PCIe | 槽位 Gen5 x8（空闲降到 Gen2 省电） | H2D 实测 **20.96 GB/s**（256 MiB）/ 18.80（512 MiB） |
| ReBAR | BAR1 = 8192 MiB（已开） | 对 H2D/大 BAR 有利 |
| 节流 | `SW Power Capping` / `SW Thermal Slowdown` 累计约 5269 s；`Reliability: Active` | 长时负载会被功耗/可靠性限制 |
| MTP | **原生支持**：`--spec-type draft-mtp`；qwen9b 自带 `blk.32.nextn.*` | 不需要额外 draft 模型 |

---

## 2. 实测性能

### 2.1 llama-bench（dsr1-8B Q4_K_M，4k，q8 KV，FA on）

| 指标 | 值 |
|---|---:|
| pp512 @ d4096 | 2078.26 t/s |
| tg128 @ d4096 | **51.47 t/s** |
| 满载功耗/温度 | 81–91 W / 51–56°C |
| 显存时钟 | 12001 → 11001 MHz |

### 2.2 qwen9b（Q5_K_M）MTP 对照

| 场景 | 无 MTP | MTP | 增益 |
|---|---:|---:|---:|
| 2k q8，64 token | — | **89.30 t/s** | — |
| 2k q8，256/251 token | **37.08 t/s** | **80.31 t/s** | **2.17x** |
| 16k q4，121 token | **47.90 t/s** | **53.12 / 78.05 t/s** | **1.11–1.63x** |

- MTP 草稿接受率：72.2%（2k）/ 74.8%（16k）；平均 **3.16–3.24 token/步**。
- 16k 组在 6.44 GiB 空闲显存下通过 overcommit 装下；`llama-server` 的 fit 检查被 `-ngl 99` 跳过。
- 16k MTP 结果有两次（53.12 与 78.05），差异来自运行间时钟/热/负载；保守值 **53 t/s** 仍远超 20。

---

## 3. 还能突破多少

| 杠杆 | 预期增益 | 代价/前提 |
|---|---:|---|
| **MTP 投机解码** | **1.6–2.2x**（已实测） | 仅 MTP 模型（qwen9b）；插件加 `--spec-type draft-mtp` |
| VRAM 装下 / 关桌面应用 | 16k 从 host 溢出 13–24 → 全 GPU 45–78 | 需多腾 0.5–1 GB；或 Q4 权重 |
| Q5 → Q4_K_M 重量化 | +20–25%，且 16k 更易装下 | 质量损失；需 `llama-quantize` |
| 功耗 94 → 115 W | +5–15%（mclk 11→12 GHz，+9% 带宽） | **需管理员**；笔记本 vBIOS 可能锁 |
| 异步 H2D/双缓冲 | 20.96 → 25–28 GB/s（+20–30%） | B1b 正在做；只影响 tier 流式 |
| 保留融合/CUDA graph | tier 模式目前比 stock 慢约 20%（53 vs 66） | 需解决“融合节点 pin”或固定槽 graph |
| 小 draft 模型投机（dsr1 等无 MTP） | 1.3–1.8x | 需 0.5–1B draft，VRAM 紧 |
| eGPU / 桌面卡 | 数倍，取决于卡 | 硬件升级；唯一能突破 8 GB/94 W 的路径 |

### 3.1 关键洞察：MTP 同时破解“带宽墙”和“PCIe 墙”

- 无 MTP：每个 token 一次 target forward；tier 模式下 host 溢出 1.15 GB/token，21 GB/s → 55 ms → 18 t/s 上限。
- MTP：平均 3.2 token/步，target forward 次数降到约 1/3.2；host 溢出摊到 **~0.36 GB/token** → I/O 上限 ~58 t/s。
- 因此 **MTP + tier 流式** 可能让 qwen9b 16k 的 host 溢出方案从 13–24 t/s 提升到 30–50 t/s；而 prebuilt server + overcommit 已经给出 53–78 t/s。
- 对 8 GB 机器，MTP 是比“加大 arena/换盘”更有效的第一杠杆。

---

## 4. 不可突破的硬限制

- **8 GB VRAM**：不能靠软件变大；只能降量化/上下文/溢出，或换卡/eGPU。
- **128-bit GDDR7**：带宽上限固定；MTP 是减少每 token 的有效字节，不是提高带宽。
- **94 W 当前功耗上限**：115 W 是 vBIOS 最大；需管理员/厂商工具，且受散热与电源适配器限制。
- **PCIe Gen5 x8**：H2D 上限约 32 GB/s 理论，实测 21；tier 流式无法靠软件超过太多。
- **单 GPU**：无 NVLink/多卡；tensor split 不适用。

---

## 5. 建议顺序

1. **插件立即启用 MTP**：qwen9b 加 `--spec-type draft-mtp`；16k q4 KV；实测 53–78 t/s。先跑 30 分钟稳定性与不同 prompt。
2. **VRAM 装下**：关闭 Edge/微信/NVIDIA Overlay 等；或把 qwen9b 重量化到 Q4_K_M（~5.2 GB），避免 overcommit。
3. **B1 重规划**：MTP 让 tier 流式的 bytes/token 降 3 倍；B1b 的异步 H2D 仍然值得做，但 qwen9b 16k 的“20 t/s 目标”已被 prebuilt+MTP 超过。B1 应改为“MTP + tier”验证，而不是继续追求 20。
4. **功耗**：如需再榨 5–15%，由用户以管理员运行 `nvidia-smi -pl 115`（本代理不碰 UAC/提权）。
5. **eGPU**：只有在需要 >12B 或 >80 t/s 时才考虑；不是当前 8–12B 目标的必需项。

---

## 6. 证据文件

- `tir-b/test/bench-dsr1-4k.txt`
- `tir-b/test/gpu-load-dsr1.log`（dmon）
- `tir-b/runtime/llama-b12202/bench-*.response.json`、`bench-*.err.log`
- `tir-b/test/mtp-test.ps1`、`mtp-bench.ps1`
- 相关 STATUS：`DSH-HANDOFF/STATUS.md`

## 7. 限制

- MTP 测试为短时（64–251 token，单 prompt）；需 30 分钟稳定性、多 prompt、质量/分布验证。
- 16k 使用 overcommit（free 6.44 GB，模型 ~7.2 GB），生产环境需关应用或 Q4 权重。
- 功耗上限设置需管理员，未执行。
