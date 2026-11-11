# B0 CUDA spike 报告

- 日期：2026-11-08 / 2026-11-09
- 执行：Qoder（DSH 被 UAC 安全桌面阻塞后，按用户“全权代理”代执行）
- 代码：DSH 的 `ggml_cuda_set_node_residency_cb` + `examples/tierspike`（Qoder 仅补 `LLAMA_API` 导出与构建脚本）
- 模型：`DeepSeek-R1-0528-Qwen3-8B-Q4_K_M.gguf`（4.79 GiB 权重，36 层，全 attention）
- 上下文：4096；greedy；prompt `The capital of France is`；生成 32 token
- 构建：VS18 / MSVC 14.51 / CMake 4.3 / Ninja / CUDA 13.5.37（便携解压，sm_120a）
- 结论：**GO（有条件）**——回调 + H2D 换入机制成立；但关闭融合/graph 后，tier 模式与 stock 模式在第 17 个 token 分叉，B1 必须采用 tier 模式基线或先解决融合问题。

---

## 1. 结果

| 用例 | tok/s | ms/token | 相对 tier 基线 | token ids | 备注 |
|---|---:|---:|---:|---|---|
| stock 基线（graph/融合默认） | 66.31 | 15.08 | — | A（32/32） | 参考 |
| tier 基线（回调计数，graph/融合关） | 53.08 | 18.84 | — | B（32/32） | 关闭 graph/融合代价 ≈3.76 ms/token |
| zero-copy（27.00 MiB） | 40.61 | 24.63 | +5.79 ms | B（32/32） | `pointer_type=1`（mapped host 被接受） |
| H2D（`output.weight` 486.86 MiB） | 30.68 | 32.60 | +13.76 ms（限 28.53） | B（32/32） | 拷贝 23.06 ms/token，部分与计算重叠 |

- 回调计数：`cb_false = cb_true = 30,756`，一致；无 pin 泄漏迹象。
- H2D 带宽：64 MiB 11.99 GB/s；256 MiB **20.96 GB/s**；512 MiB **18.80 GB/s**。256/512 过 15 GB/s；64 MiB 受固定开销影响低于 15。
- 零拷贝 27 MiB 只增加 5.79 ms/token，但大张量（486 MiB）走零拷贝会显著更慢；B1 默认 H2D，零拷贝仅作小张量选项。

### 1.1 Token id 对比

- stock A：`[264,4185,3110,1483,311,40368,279,7286,315,264,6722,6524,13,4354,11,279,1196,...]`
- tier B：`[264,4185,3110,1483,311,40368,279,7286,315,264,6722,6524,13,4354,11,279,3409,...]`
- 前 16 个 token 完全一致，**第 17 个 token 分叉**（1196 vs 3409）。
- zero-copy 与 H2D 的 token ids 与 **tier B 完全一致**（32/32）。

### 1.2 分叉原因

- 安装回调时强制关闭 CUDA 融合与 graph capture（`ggml-cuda.cu` 的 `g_node_residency_cb` 检查）。
- stock 基线启用了 `RMS_NORM + MUL` 融合与 CUDA graph；tier 模式没有。
- 这是**数值路径差异**，不是换入数据错误：zero-copy/H2D 与 tier 基线逐 token 相同，说明张量换入本身正确。
- 原 CPU diskinfer 也关闭融合；其报告称流式/原生 token 一致，但那是另一模型/另一路径，不能直接外推到 CUDA。

---

## 2. 判定

### 2.1 通过项

- CUDA 13.5 便携工具链可编译 sm_120a；`tierspike.exe` 链接并运行。
- 回调每节点触发；`cb_false == cb_true`。
- 一个 27 MiB / 486.86 MiB 张量从 host 换入 VRAM，token 与 tier 基线一致。
- H2D 增量 13.76 ms < 按 46.6 ms/795.7 MiB 折算后的 28.53 ms（486.86 MiB 当量）。
- 256/512 MiB H2D 带宽 ≥15 GB/s。

### 2.2 未通过 / 需裁决

- **stock 与 tier 的 token id 不一致**（第 17 个 token）。原计划的门要求“与全 GPU 基线一致”；严格按 stock 基线判，则 **未通过**。
- 64 MiB H2D 带宽 11.99 GB/s < 15；属小传输固定开销，但按字面门未过。
- 未测 NVMe 冷读（B2 前置），未测 30 分钟稳定/热降频，未测 qwen9b（显存不足，改用 dsr1-8b）。

### 2.3 建议

- **B0 记为 GO（机制）**：回调 + H2D 数据路径已证明。
- **B1 的正确性基线改为“tier 模式全 GPU 基线（融合/graph 关）”**，而不是 stock 基线；或者先做一个小切片，尝试“保留融合但把融合节点的全部 src 也 pin 住”，以恢复 stock 等价。
- 在未裁决前，不进入 B1 的性能验收；G2 插件可独立推进。
- 若产品要求与 stock 逐 token 等价，则当前实现不满足，需按上一条解决融合，或接受数值差异并改用 perplexity/容忍度判据。

---

## 3. 环境与复现

```powershell
# 便携 CUDA（无需管理员）
<TIR_ROOT>\runtime\cuda-13.5\bin\nvcc.exe --version
# CUDA 13.5 / V13.5.37

# 构建
build\build-only.bat
# 产物：build\tir-cuda2\bin\tierspike.exe、llama-bench.exe

# 测试
test\spike\b0\run-b0.bat
python test\spike\b0\summarize.py
```

- `build\tir-cuda2\bin\llama.exe` 未链接成功：配置为 `LLAMA_BUILD_SERVER=OFF`，但 `llama-app` 依赖 `llama-server-impl.lib`；B0 不需要它。
- `tierspike.cpp` 通过 `LLAMA_API` 导出 `llama_internal_get_tensor_map` 才能从 `llama.dll` 链接；这是 Qoder 为 spike 做的最小补丁。

## 4. 限制

- 单模型、单 GPU、单次运行、32 token；未做重复测量与 p95。
- H2D 使用同步 `cudaMemcpy`，不是最终 B1 的异步双缓冲；13.76 ms 是保守上界。
- UAC 安全桌面仍在等待用户点击；DSH 的 UI 被阻塞，B0 由 Qoder 通过 shell 代执行。
- `tierspike.cpp:281` 显式设置 `LLAMA_DISK_STREAM_MB=0`；四个 B0 日志中 `llama-disk:` 出现 0 次，确认走全 GPU，不是 CPU 磁盘流式。
