# L2 切片蓝图：A5 A4 门禁加固

- 所属 L0：`docs/blueprints/L0-system.md` M2
- 所属 L1：`docs/blueprints/L1-interactive-runtime.md`
- 日期：2026-11-10
- 状态：完成（2026-11-10）
- 前置：A4（`L2-A4-prefill-default-512.md`）完成；两轴审查（Standards / Spec）发现门禁缺口

## 交付物

让 `tir-test-prefill` 的默认批用例能真正拦住「默认值从 2/512 退回逐 token」；oracle 与生产策略同义；`tir-test-abi-load` 用真实模型重跑；修正 A4 执行记录中不可复现的证据引用。生产策略（白名单 + nextn→2）不改。

## 审查输入（本切片要解决的项）

| 来源 | 问题 | 位置 |
|---|---|---|
| Standards 硬缺陷 1 / Spec (c)3 | `expect==2` 时无 gain 门禁、profile 窗口无下界，默认 2→1 全绿（9B 实测 9168.6/4799.2=1.91<2.0） | `test_prefill.c:383`、`:408` |
| Standards 硬缺陷 2 / Spec (a)2 | oracle 匹配 `"nextn":1`，生产是 `nextn>0`；meta 已有 `"mtp":true` | `test_prefill.c:311`、`tir_chat.cpp:208` |
| Spec (c)5 | A4 执行记录引用 `a4-full-*.raw` 作首轮证据，文件已被最终复跑覆盖 | `L2-A4-prefill-default-512.md:72` |
| Spec (c)6 | `abi-load` 两次都是 `SKIP (TIR_TEST_MODEL not set)`，RC=0 来自跳过 | `build/logs/a4-reg2-abi-load.raw` |
| Standards 判断项 | 注释称 MTP 头默认 2，但白名单外 arch 先 `return 1`，MTP+未知 arch 实得 1 | `tir_generate.cpp:22-33` |

## 不解决（保留为残余风险，写入 A5 审计）

- 白名单外 arch→1 无测试：本机没有 gemma4/glm4/spark2_5 模型，且策略函数是 static、依赖已加载模型；不为它改公共 ABI。
- env 回落用例在 5-token prompt 上区分力不足（4B/9B 的 pb=1 与 512 token 相同）：改成计时判据需额外长 prompt 运行，收益低于成本，记为已知缺口。
- 两个测试函数骨架重复、`512` 魔数分散在 4 处：属重构，不属本切片。
- 恒真的 `prompt_tokens` parity 检查：不阻塞，留待下次触碰该测试时清理。

## 切片检查表

| 检查项 | 是 / 否 |
|---|---|
| 预计 ≤30 分钟完成？ | 是（测试判据 + 一次矩阵 + abi-load + 文档） |
| 修改文件 ≤2 个（测试文件不计）？ | 是：`tir_generate.cpp` 仅注释；其余为测试与文档 |
| 是垂直切片？ | 是（默认值 → 测试判据 → 实际 TTFT/token 输出） |
| 有独立可运行验收？ | 是（变异 RED + 五模型 GREEN + abi-load 真实输出） |
| 写入域与其他并行任务不重叠？ | 是（GPU 独占，两波串行） |

## 涉及文件

- 写（A5a）：`src/llama.cpp-fork/tests/tir-api/test_prefill.c`、`build/logs/a5-*.raw`
- 写（A5b）：`src/llama.cpp-fork/src/tir-api/tir_generate.cpp`（仅注释）、`docs/blueprints/L2-A4-prefill-default-512.md`、`build/logs/a5-abi-load.raw`
- 写（主代理）：本文件执行记录、`docs/blueprints/L1-interactive-runtime.md` §8
- 读：`tir_generate.cpp`、`tir_chat.cpp`、`tir.h`、`tests/tir-api/test_mtp.c`、`build/logs/a4-*.raw`
- 禁止触碰：`tir.h` 公共 ABI、`tir_core.cpp`、`tir_mtp.cpp`、`llama.cpp`/`ggml`/`common`、`runtime/`、`CMakeLists.txt`、模型文件、其它测试、master 分支、push/PR

## 设计

1. **默认值判据改为最近邻**（`run_default_batch_case`）：已有 `seq_med`（pb=1）、`def_med`（不设 env）、`exp_med`（显式期望值）。新增
   `def_err = |def_med - exp_med|`、`seq_err = |def_med - seq_med|`，要求 `def_err < 0.5 * seq_err`，并打印两者。
   依据实测：通过时 `def_err/seq_err` ≈ 0.0004（1B 0.5/1178 ms、9B 0.2/4369 ms）；默认退回 1 时 `seq_err`→0，必然失败。
   保留现有 parity、`0.5 < profile < 2.0`、`expect==512` 时 `gain>=4`。
2. **oracle 改用 `"mtp":true`**（`expected_default_batch`）：覆盖 nextn≥2，与生产 `n_layer_nextn > 0` 同义；4.2B 仍 expect=512，9B 仍 expect=2。
3. **变异 RED 取证**：测试先行，先加判据；再临时把 oracle 的返回改成 1（仅测试内、模拟策略回归），在 9B 与 1B 上各跑一次，必须 RC=1 且打印「matches per-token profile」；恢复 oracle 后 RC=0。两次变异日志都保留。
4. **注释对齐**：`tir_generate.cpp` 注释改为「allowlisted 模型带 MTP 头时默认 2」，不改变代码。
5. **abi-load 真实重跑**：`TIR_TEST_MODEL` 指向 1B，期望打印 `layers=… mtp=0` 且 RC=0；替换 A4 第 78 行「abi-load RC=0」的无效引用。
6. **A4 文档修正**：第 72 行首轮证据注明「已被 09:15–09:24 最终复跑覆盖，首轮数字不可复现」；第 78 行改为带模型的 abi-load 结果。

## 验收标准（可运行）

1. `build\build-tir-api.bat` → `BUILD_OK`。
2. 9B `tir-test-prefill` 变异 RED（oracle 临时返回 1）→ RC=1 且含 `default batch matches per-token profile`；恢复后 → RC=0、`expect=2`、`profile_match=OK`、`def_err` 明显小于 `seq_err`。
3. 1B 同上变异 RED → RC=1；恢复后 → RC=0、`expect=512`、`gain>=4`、`profile_match=OK`。
4. 五模型矩阵（1B/4.2B/Nemotron/8B/9B）→ 全 RC=0；9B `expect=2`，其余 `expect=512`；520 token 的 `cross=OK det=OK`。
5. 回归：9B `tir-test-mtp` → `parity=64`；`tir-test-abi` → RC=0；1B `tir-test-generate` → RC=0；9B `tir-test-chat` → RC=0。
6. `TIR_TEST_MODEL=<1B> tir-test-abi-load.exe` → RC=0 且 stdout 含 `layers=` 行（不是 SKIP）。

## 前置条件

- [x] 依赖切片 A4 已验收（五模型 RC=0、MTP parity=64）
- [ ] 工作区干净 —— **不成立**：工作树含 A1–C2 未提交改动。以派发前 `git status --porcelain` + 目标文件 `sha256sum` 作为基线，回收后对照；不提交、不 stash。
- [x] 公共 ABI 冻结（`tir.h` 只读）

## 停止条件

- 变异 RED 无法稳定复现（同一失败 2 次）→ 停止，评估是否改为直接断言 timing 阈值；
- 需要改 `tir.h`、生产策略或写清单外文件；
- 五模型任一在新判据下 GREEN 但 `def_err/seq_err` 落在 0.5 附近（判据无余量）→ 停止并重新定阈值；
- GPU 显存不足或与其它进程冲突 → 停止并上报。

## 执行记录

| 时间 | 事件 | 证据 |
|---|---|---|
| 09:37 | 写 A5 蓝图；记录工作树与目标文件基线（工作区不干净，以 hash 对照代替） | `build/logs/a5-baseline.sha256`、`a5-baseline.status`（33 项） |
| 09:40 | 派发 A5a（后台，test_prefill.c + 全部 GPU 运行）；A5b 阻塞至 A5a 回收 | 本文件；task #18/#19 |
| 09:45 | A5a 变异 1：旧断言 + 默认批强制 `"1"`，9B 跑通 | `a5-mutant-old-9b.raw:14357` `expect=2 profile=1.91 profile_match=OK`，`:16415` `test_prefill: OK` |
| 09:50 | A5a 变异 2：新判据 + 同一回归，9B 失败 | `a5-mutant-new-9b.raw:14357` `def_err=4507.2 seq_err=1.9 match=FAIL`；`:14360` 报 `matches per-token profile, not pb=2` |
| 09:54 | 复跑确认判据稳定 | `a5-mutant-new2-9b.raw:14357` `def_err=4156.4 seq_err=91.3 match=FAIL` |
| 09:55 | A5a 被宿主中断（非测试失败）：`SessionTranscriptWriter is closed`；9B 进程退出，GPU 回到 49–50 °C / 1.1 GB | task #18 → pending；`nvidia-smi` 无 tir 计算进程 |
| 09:56 | 主代理恢复变异：`gen(..., "", ids_def, ...)`；oracle 改 `"mtp":true`。设计与实施偏差：变异施加在**默认路径 env**（等价于策略回归），未改 oracle 返回值——后者会先触发既有 `profile<0.5` 分支，无法隔离新判据 | `test_prefill.c` sha256 `3570d264…`（基线 `6ebb20d3…`），`tir_generate.cpp` 仍 `9b2588…` |
| 09:57 | CPU 侧复建（无 GPU）：增量编译 `test_prefill.c`，链接通过；无模型测试通过 | `BUILD_OK`；`tir-test-abi: OK` RC=0；无 `TIR_TEST_MODEL` 时 prefill `SKIP` RC=0 |
| 12:45 | GPU 空闲确认（45 °C / 1.16 GB），重建 `BUILD_OK`（ninja no work） | `nvidia-smi` |
| 12:46 | 1B GREEN：`expect=512 gain=30.95x profile=0.98 def_err=1.0 seq_err=1209.4 match=OK parity=OK` | `build/logs/a5-final-1b.raw` |
| 12:47 | 4.2B GREEN：`expect=512 gain=32.12x def_err=6.0 seq_err=4920.7 match=OK` | `a5-final-4b.raw` |
| 12:47 | Nemotron 4B GREEN：`expect=512 gain=31.14x def_err=4.3 seq_err=4383.9 match=OK` | `a5-final-nemotron.raw` |
| 12:48 | 8B GREEN：`expect=512 gain=32.49x def_err=3.4 seq_err=7700.5 match=OK` | `a5-final-8b.raw` |
| 12:50 | 9B GREEN（关键）：`expect=2 gain=1.92x profile=0.99 def_err=34.2 seq_err=4505.1 match=OK parity=OK` | `a5-final-9b.raw` |
| 12:51 | MTP 回归：`plain=64 mtp=64 parity=64` | `a5-reg-mtp-9b.raw` |
| 12:52 | chat/generate/abi-load/abi 回归全 RC=0；abi-load 真实输出 `layers=24 embd=1536 ctx_train=131072 vocab=130560 mtp=0` | `a5-reg-chat-9b.raw`、`a5-reg-generate-1b.raw`、`a5-abi-load.raw`、`a5-abi.raw` |
| 12:55 | A5b：`tir_generate.cpp` 注释改为“allowlisted 模型带 MTP 头才默认 2；未列 arch 仍 1”；重建 `BUILD_OK`，`tir-test-abi: OK` | `tir_generate.cpp` sha256 `d67f37f5…`（原 `9b2588…`，仅注释）；`test_prefill.c` 仍 `3570d264…` |
| 12:56 | 写入审计：相对 09:37 基线，源码仅 `test_prefill.c` 与 `tir_generate.cpp`（注释）变化；新增 `L2-TP1` 蓝图属另一任务 | `git status --porcelain` 对照 `a5-baseline.status` |

实施偏差（记录在案）：验收标准 3 的“1B 变异 RED”未单跑。原因与 09:56 记录的相同——把默认路径改成 `1` 时，1B 会先触发既有的 `profile < 0.5` 分支，无法隔离新判据；能隔离 `expect==2` 漏洞的用例只有 9B，RED 已在 `a5-mutant-new-9b.raw`、`a5-mutant-new2-9b.raw` 取证。1B 以 GREEN（`gain=30.95x`）覆盖回归。GPU 跑分使用的是注释修改前的 `tir_generate.cpp 9b2588…`；注释改动不改变行为，重建后仅做 CPU 侧 `tir-test-abi` 复核。
