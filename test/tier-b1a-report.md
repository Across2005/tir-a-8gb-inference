# B1a 交付报告：Tier 内存管理（T0/T1 booking）

- 日期：2026-11-09
- 范围：B1a（`src/tier-memory.{h,cpp}` + 单测 + 真实 CUDA 分配 smoke）
- 状态：**通过**；8/8 单测 PASS，真实 CUDA 1 GiB T0 + 2 GiB T1 分配/释放 PASS。

## 1. 代码

- `src/tier-memory.h`：`tier::Config/Stats/Slot/Arena/TierMemory/Backend`。
- `src/tier-memory.cpp`：
  - `Arena`：2 MiB 可配对齐、首次适配、切分、free 时相邻块合并、LRU victim（跳过 pinned）。
  - `TierMemory`：张量注册（key=ggml_tensor* 可）、`ensure`（T0 命中→pins++；否则换出/分配/可选 H2D）、`unpin`、粘性失败（`fail` + `fail_reason`，禁止继续）、`tier_stats` 计数（t0/t1 bytes、h2d_bytes/us、hits、evictions、fail）。
  - 不直接调用 CUDA：通过 `Backend` 抽象，booking 逻辑可无 GPU 单测；CUDA 实现在 B1d 接入。
- 测试：
  - `test/tier-memory/tier-memory-test.cpp`（fake backend，8 用例）。
  - `test/tier-memory/tier-memory-cuda-smoke.cpp`（真实 `cudaMalloc`/`cudaHostAlloc`/`cudaMemcpy`）。

## 2. 验收证据（2026-11-09 09:2x）

构建（VS18 + cl）：

```
cl /nologo /std:c++17 /EHsc /O2 /I src src\tier-memory.cpp test\tier-memory\tier-memory-test.cpp /Fe:tier-memory-test.exe
```

运行：

```
tier-memory tests: 8/8 PASS
```

覆盖：对齐/切分、pin 阻止换出、free 合并、H2D 字节统计与数据一致、T0 装不下→显式失败、未注册张量→失败、LRU 顺序、1 GiB/2 GiB 容量记账。

真实 CUDA（同一 booking 层 + CudaBackend）：

```
cuda free before = 7043 MiB / total 8123 MiB
cuda free after  = 7043 MiB (delta 0 MiB)
tier-memory cuda smoke: PASS
```

即：T0 = 1 GiB VRAM、T1 = 2 GiB pinned host 分配成功；注册 64 MiB 张量并 H2D 后 `h2d_bytes` 正确；`shutdown()` 后显存完全释放（delta 0）。

## 3. 未纳入本切片（B1b/B1d）

- `ensure` 从 T1 暂存换入（当前 host_ptr 直接指向源）/ T2 读盘。
- 异步 copy stream + event 回收、双缓冲、层包预取（B1b）。
- CUDA backend 从测试文件移入 `src/tier-memory-cuda.cpp` 并接入 llama 构建（B1d）。
- 与 `TierPlan` 的 `commit()`（B1d）。

## 4. 下一步

B1b：异步 H2D（2 copy stream、每槽 event、compute 流 wait）、预取；用 B0 的 32/256 MiB 数字复测事件回收与半拷贝正确性。
