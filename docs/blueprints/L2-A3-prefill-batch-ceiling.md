# L2 切片蓝图：A3 prefill 批上限放开到 512

- 所属 L0：`docs/blueprints/L0-system.md` M2
- 所属 L1：`docs/blueprints/L1-interactive-runtime.md`
- 日期：2026-11-10
- 状态：完成（上界已放开；默认值提升留给 E1 量表切片）

## 交付物

把 `TIR_PREFILL_BATCH` 的上界从 8 放到 512（= `n_ubatch`），让 plain 路径的长 prompt prefill 能一次喂一个 ubatch；保持 arch 白名单默认值（`qwen35`→2、其它→1）不变，默认值只按实测 parity 逐 arch 提升。

## 切片检查表

| 检查项 | 是 / 否 |
|---|---|
| 预计 ≤30 分钟完成？ | 是（上界是单行改动，测试复用 A2 的 prefill 夹具） |
| 修改文件 ≤2 个（测试文件不计）？ | 是：`tir_generate.cpp` + `build/build-tir-api.bat`（测试目标补登） |
| 是垂直切片？ | 是（env → prefill 批 → TTFT/parity 一条链） |
| 不按横向阶段切分？ | 是 |
| 有独立可运行验收？ | 是（`tir-test-prefill` 的 512 档） |
| 写入域与其他并行任务不重叠？ | 是（A2 已收口，无并行切片） |

## 涉及文件

- 写：
  - `src/llama.cpp-fork/src/tir-api/tir_generate.cpp`（仅上界与注释）
  - `src/llama.cpp-fork/tests/tir-api/test_prefill.c`
  - `build/build-tir-api.bat`（补 `tir-test-prefill` 目标）
  - `docs/blueprints/L2-A3-prefill-batch-ceiling.md`
- 读：`tir.h`、`tir_core.cpp`
- 禁止触碰：`tir.h` 公共 ABI、`tir_core.cpp`、`tir_mtp.cpp`、`llama.cpp`/`ggml`/`common`、`runtime/`、模型文件、master。

## 设计

1. `prefill_batch_size`：越界判定 `[1, 8]` → `[1, 512]`；512 与 `n_ubatch` 对齐，再大也只会被上下文内部再切。默认值逻辑不动。
2. `test_prefill.c` 新增 `run_high_batch_case`：约 520 token 的 prompt，warmup 一次后 pb=1/pb=512 交替 3 轮，断言：
   - 所有 run 的 token ids 与 `prompt_tokens` 和 pb=1 参考一致；
   - `seq_med / big_med >= 4`（不做假收益断言：先把失败数字打出来）。
   - 越界 env 用例从 `"99"` 改成 `"513"`（99 在新上界内会变成合法值）。
3. 默认值提升不在此切片：先用 E1 量表（1B/4B/Nemotron/8B/9B × 512 档）拿 parity + TTFT，再逐 arch 改白名单。

## 验收标准（可运行）

1. `build\build-tir-api.bat` → `BUILD_OK`。
2. 1B（`<MODEL_DIR>\blobs\sha256-b1c3bf29...`，`TIR_TEST_MODEL` 指向它）运行 `tir-test-prefill.exe` → 512 档 `gain>=4x parity=OK`，全部用例 PASS。
3. `TIR_PREFILL_BATCH` 不设时默认行为与原 A2 一致（qwen35 仍 2、llama 仍 1）。

## 停止条件

- 512 档 greedy ids 与 pb=1 不一致且无法解释 → 保持上界 8，报告 `BLOCKED`。
- 1B 上 TTFT 收益 <4× → 记录数字，不提升默认值。
- 需要改公共 ABI 或写域外文件 → 停止。

## 执行记录

| 时间 | 事件 | 证据 |
|---|---|---|
| 2026-11-10 | RED | 1B：522 token，pb=512 被 `[1,8]` 吞掉 → `big_med=1213.7` vs `seq_med=1208.3`，`gain=1.00x`，`test_prefill: FAILED`；`build/logs/a3-prefill-red.log` |
| 2026-11-10 | GREEN | 1B：`seq_med=1206.8` → `big_med=41.2`，`gain=29.32x`，parity OK；`a3-prefill-green.log` |
| 2026-11-10 | 9B 交叉验证 | qwen35 hybrid：`9112.8` → `266.7`，`gain=34.17x`，parity OK；`a3-prefill-9b.log` |
| 2026-11-10 | 回归 | 1B：abi/abi-load/generate/profile/spec 全 0；9B：mtp/chat 全 0（1B 跑这两项应按模型断言失败，非回归）；`a3-*.log` |

## 审计

- 代码改动：`tir_generate.cpp` 仅 2 行（越界上界 8→512 + 注释）；`test_prefill.c` +76/−2；`build-tir-api.bat` 目标表补 `tir-test-prefill`。
- 未触碰：`tir.h`、`tir_core.cpp`、`tir_mtp.cpp`、`llama.cpp`/`ggml`/`common`、`runtime/`、模型文件。
- 默认值未变（`qwen35`→2、其它→1），故现有调用方行为零变化；收益需显式设 `TIR_PREFILL_BATCH`。
- 回滚：把上界改回 8 并删测试函数；或运行时 `TIR_PREFILL_BATCH=1` 逐 token。
- 已知局限：只测了 1B（llama）与 9B（qwen35）；4B/Nemotron/8B 与 VRAM 峰值未测，默认值提升前必须补齐。
