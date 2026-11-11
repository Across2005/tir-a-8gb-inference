# L2 切片蓝图：A4 prefill 默认批按实测提升到 512

- 所属 L0：`docs/blueprints/L0-system.md` M2
- 所属 L1：`docs/blueprints/L1-interactive-runtime.md`
- 日期：2026-11-10
- 状态：完成（2026-11-10）
- 前置：A3（上界放开 512）完成

## 交付物

把 `qwen35 → 2` 的白名单默认值，按 E1 实测扩展为 `llama / qwen3 / qwen35 / nemotron_h → 512`；带 MTP 头（nextn>0）的模型因 plain↔MTP 一致性要求仍默认 2；其它或未知 arch 仍走逐 token。收益不再依赖环境变量。

## 实测补充：MTP 头例外

E1 矩阵完成后，`tir-test-mtp`（9B，64 token）在默认 512 下 RED：`mismatch at 2: plain=1061 mtp=198`；`TIR_PREFILL_BATCH=2` 下 GREEN：`parity=64`。原因见 `tir_mtp.cpp:250-253`：MTP 路径刻意逐 token prefill 以对齐 plain，512 的 plain 路径打破该等式。因此 `prefill_batch_for_arch` 增加一条：`llama_model_n_layer_nextn(model) > 0 → 2`，其余白名单 512；4.2B（无 nextn）仍走 512。

## E1 实测（`tir-test-prefill`，16K ctx，kv q4，磁盘流式关闭）

| 模型 | arch | prompt | pb=1 | pb=512 | 收益 | parity | 峰值显存 |
|---|---|---|---:|---:|---:|---|---:|
| MiniCPM5 1B | llama | 522 | 1206.8 ms | 41.2 ms | 29.3× | OK | — |
| qwen3.5-opus 4.2B | qwen35 | 521 | 4705.2 ms | 149.8 ms | 31.4× | OK | 4357 MiB |
| Nemotron-3-Nano 4B | nemotron_h | 522 | 4368.8 ms | 143.3 ms | 30.5× | OK | 4029 MiB |
| DeepSeek-R1 8B | qwen3 | 521 | 7721.8 ms | 242.7 ms | 31.8× | OK | 6475 MiB |
| Qwen3.8 9B | qwen35 | 521 | 9112.8 ms | 266.7 ms | 34.2× | OK | — |

表内 9B 的 pb=512 现在是显式 env 行为：该模型有 MTP 头，默认走 2（521 token 4769 ms，1.91×），见下文 MTP 例外。

## 切片检查表

| 检查项 | 是 / 否 |
|---|---|
| 预计 ≤30 分钟完成？ | 是（白名单一行 + 测试一条默认值用例） |
| 修改文件 ≤2 个（测试文件不计）？ | 是：`tir_generate.cpp` |
| 是垂直切片？ | 是（默认值 → prefill 批 → TTFT/parity） |
| 有独立可运行验收？ | 是（不设 env 时 520 token 的 TTFT 与 pb=1 的比值） |
| 写入域与其他并行任务不重叠？ | 是 |

## 涉及文件

- 写：`src/llama.cpp-fork/src/tir-api/tir_generate.cpp`、`tests/tir-api/test_prefill.c`
- 禁止触碰：`tir.h` 公共 ABI、`tir_core.cpp`、`tir_mtp.cpp`、`llama.cpp`/`ggml`/`common`、`runtime/`、模型文件。

## 设计

1. `prefill_batch_for_arch`：`{llama, qwen3, qwen35, nemotron_h}` → 512；其中 `nextn > 0`（有 MTP 头）→ 2；其余 → 1。保留白名单形态：未实测的 arch（gemma4/glm4/spark2_5）不静默走批。
2. 测试新增 `run_default_batch_case`：清空 `TIR_PREFILL_BATCH` 后跑 3 轮，与显式 pb=1 对照；并额外跑显式 `pb=<expect>`（512 或 2）对比 TTFT 剖面（`0.5 < def/exp < 2.0`）。要求 token parity 成立；`expect=512` 时 `seq_med / def_med >= 4`。A3 的 `gain>=4` 门禁保留作为显式 env 的回归。
3. `expect` 由 `tir_model_meta` 的 `"nextn":1` 决定（2 或 512），在测试里独立写出，不复用生产函数。
4. `env=0/513/x` 用例改为与"未设 env 的默认路径"对照：A4 后它们回落的目标从 1 变成白名单默认值，仍要求与默认路径逐 token 一致（同一个默认值被走两遍）。`TIR_PREFILL_BATCH=2` 是精确对齐 pb=1 的逃生舱。
5. 数值口径（实现中实测得出）：prefill 行数 >2 会让 CUDA 后端换用不同的 matmul / flash-attention kernel（MMVQ ↔ MMQ），末 token logits 差几 ulp；top-2 接近时 greedy id 会翻转。故门禁拆两条：
   - `det`：同一配置多轮输出一致，所有档位必须 OK（强不变量）；
   - `cross`：pb=512 与 pb=1 跨形状一致，只在已实测的 ~520 token 档强制（5 个白名单 arch 全通过）；5 / 130 token 档只打印、不拦。

## 验收标准（可运行）

1. `build\build-tir-api.bat` → `BUILD_OK`。
2. 五个白名单模型跑 `tir-test-prefill.exe` → RC=0：~520 档 `cross=OK det=OK`；`default_batch ... parity=OK profile_match=OK`，`expect=512` 的四个模型 `gain>=4x`，9B `expect=2`（`gain≈1.9x`）；env 回落 `0/513/x` 全部 OK。
3. 9B 跑 `tir-test-mtp.exe` → RC=0，`parity=64`（默认路径，不设 env）。
4. 同一产物最后再跑一次 1B，作为最终证据集。

## 停止条件

- 任一 arch 在默认 512 下 parity 失败 → 仅回退该 arch 到 2 或 1，记录并报告。
- 8B 默认路径峰值显存超过 7.4 GB → 停止提升，报告。

结果：9B（qwen35 + MTP 头）在 `tir-test-mtp` 上触发第一条 → 该模型默认回退到 2；同 arch 的 4.2B（无 nextn）保留 512。8B 峰值沿用 E1 的 6475 MiB（< 7.4 GB）。

## 执行记录

| 时间 | 事件 | 证据 |
|---|---|---|
| 08:53–09:01 | 首轮五模型（默认 512）：`test_prefill` 全 RC=0；9B 默认 34× 与 E1 一致 | `build/logs/a4-full-*.raw`（同名文件已被 09:15–09:24 最终复跑覆盖，首轮数字不可复现） |
| 09:03 | `tir-test-mtp` 9B 默认路径 RED：`mismatch at 2: plain=1061 mtp=198`；`TIR_PREFILL_BATCH=2` 下 `parity=64` | `a4-reg-mtp-9b.raw`、`a4-reg-mtp-9b-pb2.raw` |
| 09:10 | 测试先行 RED：9B 默认仍是 512，与期望的 pb=2 不符 | `a4-red-9b-default.raw`：`expect=2 profile=0.06 profile_match=FAIL` |
| 09:14 | 实现 `nextn>0 → 2`；9B 默认路径 GREEN | `a4-green-9b-default.raw`：`def_med=4769.2 exp_med=4764.1 profile=1.00 parity=OK` |
| 09:14 | 9B MTP 回归恢复 GREEN | `a4-reg-mtp-9b-final.raw`：`parity=64` |
| 09:15–09:24 | 最终产物五模型复跑，全 RC=0 | 1B `29.36×`；4.2B `31.11×`；Nemotron `30.21×`；8B `31.75×`（`profile≈1.00`）；9B `expect=2 1.91×`；`a4-full-*.raw` |
| 09:24 | ABI 回归 | `tir-test-abi` / `generate`(1B) / `chat`(9B) 全 RC=0；`abi-load` 当时未设 `TIR_TEST_MODEL`，输出 SKIP、RC=0 来自跳过。A5 于 12:49 用 1B 重跑，`layers=24 embd=1536 ctx_train=131072 vocab=130560 mtp=0`、RC=0（`build/logs/a5-abi-load.raw`） | `a4-reg2-*.raw`、`a5-abi-load.raw` |

## 审计

- 写清单：`tir_generate.cpp`（`prefill_batch_for_arch` + 注释）、`test_prefill.c`（`expected_default_batch`、`run_default_batch_case`、env 回落对照），以及本蓝图与 L1 执行记录。
- 未触碰：`tir.h`、`tir_core.cpp`、`tir_mtp.cpp`、`llama.cpp`/`ggml`/`common`、`runtime/`、模型文件；`git status --porcelain` 中其余 M/?? 为前置切片产物。
- 回滚：运行时设 `TIR_PREFILL_BATCH=2` 即恢复精确 parity；或把 `prefill_batch_for_arch` 改回 1/2 并重建。
- 残留风险：非 MTP 白名单 arch 的短 prompt（top-2 接近）偶发 greedy 翻转（实测 1B 5/7、8B 4/7、Nemotron 1/6）；≥520 token 档 5/5 通过。MTP 头模型默认 2，plain↔MTP `parity=64`。
