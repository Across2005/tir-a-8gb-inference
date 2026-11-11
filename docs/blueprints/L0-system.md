# L0 系统蓝图：TIR-A 本地推理引擎

- 日期：2026-11-09
- 状态：P0 已完成（`tir-a-p0`，c9a5043..9a70d1d）；P1 迭代中（`tir-a-p1`）
- 设计权威：`<WORKSPACE>\docs\superpowers\specs\2026-11-09-local-inference-engine-design.md`
- 实施计划：`<WORKSPACE>\docs\superpowers\plans\2026-11-09-tir-a-p0-resident-dense.md`

## 1. 产品目标（一句话可验收）

在 Windows x64 + 单张消费级 GPU 上，提供一个可被任意 harness 以进程内 C ABI 接入的 GGUF 推理 DLL：单用户交互场景下，同模型/量化/上下文相对官方 llama.cpp 的 decode tok/s 提升 30%，TTFT 不退化，8–14B 可交互、26B MoE 可运行。

P0 已完成前半句的机制验证与正确性：

- 11 函数 C ABI，`tir.dll` + `tir.h`；
- qwen9b 16k q4 + MTP：avg 56.93 / best 60.33 t/s，acceptance 0.882，plain/MTP greedy token 一致；
- 16k q4 plain：avg 48.74 t/s；
- 6 语言宿主 smoke；gate 脚本可复现。

## 2. 模块划分（冻结）

| 模块 | 职责 | 写入域 | 对外契约 |
|---|---|---|---|
| **M1 ABI/Core** | 生命周期、错误、模型加载、info、stats | `src/llama.cpp-fork/src/tir-api/tir.h`、`tir_core.cpp`、`tir_internal.h` | `tir.h`（冻结）；`docs/tir-api/ABI.md` |
| **M2 Generation** | plain/MTP、session 状态、prefill/decode、采样 | `tir_generate.cpp`、`tir_mtp.cpp`、`tir_internal.h` | `tir_generate_*` 内部签名；`tir.stats/v1` |
| **M3 Planner** | GGUF 分析、tier plan、模型能力标记 | `tools/tier_gguf.py`、`tools/tier_plan.py` | `tir.plan/v2`（设计） |
| **M4 Tier Runtime** | T0/T1/T2、region、固定槽、superblock | 未来 `src/tier-*` | `tier.plan/v1`、`tier.stats/v1` |
| **M5 Backend** | CUDA 后端、kernel 注册、graph | 未来 `src/backend-*` | backend ABI（设计） |
| **M6 Hosts/Bench** | Python/Node/C# hosts、bench、gate | `tests/tir-api/**`、`build/*.bat`、`test/tir-api/**` | 无冻结契约 |

**模块边界**：M1/M2 不直接操作 llama.cpp 图内部；M4/M5 未实现前，M2 只允许 RESIDENT 路径。跨模块改动必须先改 L0/L1 并记录。

## 3. 目录结构（冻结）

```
tir-b-p0/
  src/llama.cpp-fork/
    src/tir-api/        # M1/M2：ABI + 生成
    tests/tir-api/      # M6：C 测试 + hosts + bench
    docs/tir-api/       # M1：ABI.md
  build/                # 构建与 gate 脚本（gitignored 输出）
  test/tir-api/         # gate JSON 证据
  docs/blueprints/      # 本蓝图
```

## 4. 跨模块契约索引

| 契约 | 位置 | 状态 |
|---|---|---|
| 公共 C ABI | `src/llama.cpp-fork/src/tir-api/tir.h` | **冻结**（P0） |
| ABI 行为/所有权/线程 | `src/llama.cpp-fork/docs/tir-api/ABI.md` | 生效 |
| 统计字段 | `tir_stats`（`tir.h`） | 只追加，不重排 |
| Tier plan | `<WORKSPACE>\docs\superpowers\specs\...` §5.7 | 设计，未实现 |
| 后端 ABI | 同上 §4.3 | 设计，未实现 |

## 5. 全局验收命令（P0）

```bat
build\build-tir-api.bat
build\run-p0-gate.bat
```

期望：`BUILD_OK`、4 个测试通过、`P0_GATE_OK tok_s_avg>=45`，`test/tir-api/p0-gate.json` 存在。

P1 追加：

```bat
build\run-p1-gate.bat
```

期望：A1 的 warm/cold TTFT 断言 + 所有 P0 测试通过（P1 实现后创建）。

## 6. 不做什么（非目标）

- 训练/微调、多 GPU、多机、Linux/macOS、移动/Web、多人并发服务；
- 任意模型代码插件；
- P1 阶段不做 TIERED/MoE/KV head 分段；
- 不改 tokenizer 语义、不静默改变 greedy 输出。

## 7. 变更记录

| 日期 | 变更 | 理由 |
|---|---|---|
| 2026-11-09 | L0 建立；P0 完成 | P1 迭代需要正式模块/契约基线 |
| 2026-11-09 | P1 选择「交互延迟包」 | MTP 上下文重建、重复 prefill、无 KV 复用是当前交互瓶颈 |
