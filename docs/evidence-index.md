# 证据索引

论文中的 `docs/reports/...`、`build/logs/...`、`test/...` 引用来自原项目工作区。为避免公开本机路径与完整模型清单，本仓库不包含原始日志与报告；本文件给出引用与来源文件的对应关系，便于判断每个数字的出处类型。

## 报告

| 论文中的引用 | 原文件（未随仓库发布） | 内容 |
|---|---|---|
| `docs/reports/2026-11-09-hardware-ceiling-probe.md` | 同左 | HBM/PCIe/CPU/NVMe 带宽、功耗、温度、kernel launch |
| `docs/reports/2026-11-09-key-nodes-roofline.md` | 同左 | 屋顶线与关键节点 |
| `docs/reports/2026-11-09-ceiling-calibration.md` | 同左 | C0：1B/4B/8B 真实上下文校准 |
| `docs/reports/2026-11-09-tir-a-speed-history.md` | 同左 | P0/A1/A2/S1 阶段速率与隔离复测 |
| `docs/reports/2026-11-09-tir-a-p0-p1-technical-report.md` | 同左 | P0/P1 技术报告 |
| `docs/reports/2026-11-09-tir-a-stage-technical-report.md` | 同左 | 阶段技术报告 |
| `docs/reports/2026-11-09-tir-a-s1-small-model-report.md` | 同左 | 7 模型兼容矩阵 |
| `docs/reports/2026-11-09-qwen9b-q4-mtp-w2.md` | 同左 | 9B Q4_K_M + MTP w1/w2/w3 |
| `docs/reports/2026-11-09-ngram-spec.md` | 同左 | ngram 自投机边界 |
| `docs/reports/2026-11-09-draft-simple.md` | 同左 | draft-simple 成本 |
| `docs/reports/2026-11-09-4b-quant-ab.md` | 同左 | Q4_0/Q3 量化 A/B |
| `docs/reports/2026-11-09-iq4xs-memory.md` | 同左 | IQ4_XS 与加内存评估 |
| `docs/reports/2026-11-09-nemotron-119-retrospective.md` | 同左 | 119 tok/s 的口径复盘 |
| `docs/reports/2026-11-09-e-drive-feasibility.md` | 同左 | E 盘带宽与容量层结论 |
| `docs/reports/2026-11-09-gemma26-expert-profile.md` | 同左 | gemma26 专家流式可行性 |
| `docs/reports/2026-11-09-tir-c-gpu-first-correction.md` | 同左 | TIR-C 方向修正与废止 |
| `docs/reports/2026-11-09-engine-design-audit.md` | 同左 | 设计缺陷审计（测量污染等） |
| `docs/reports/2026-11-09-local-model-inventory.md` | 同左 | 模型库存与显存预算 |
| `docs/superpowers/specs/2026-11-09-local-inference-engine-design.md` | 同左 | 引擎设计权威文档 |
| `docs/superpowers/plans/2026-11-09-tir-a-p0-resident-dense.md` | 同左 | P0 实施计划 |

## 蓝图

| 论文中的引用 | 原文件（未随仓库发布） | 内容 |
|---|---|---|
| `docs/blueprints/L0-system.md` | 同左 | 系统模块与契约 |
| `docs/blueprints/L1-interactive-runtime.md` | 同左 | 交互运行时切片记录 |
| `docs/blueprints/L2-A1...A5` | 同左 | MTP 缓存、prefill、默认批、门禁加固 |
| `docs/blueprints/L2-S1/S2/S2c/S2d` | 同左 | 小模型兼容、模板、思考开关、流式过滤 |
| `docs/blueprints/L2-C0/C2a/C2e/C3` | 同左 | 上限校准、ngram、9B MTP w2、功耗 |

## 日志与测试

| 论文中的引用 | 原文件（未随仓库发布） | 说明 |
|---|---|---|
| `build/logs/a4-full-*.raw` | 同左 | A4 五模型默认批结果 |
| `build/logs/a5-final-*.raw` | 同左 | A5 五模型 GREEN |
| `build/logs/a5-mutant-*.raw` | 同左 | A5 变异 RED |
| `build/logs/a5-reg-*.raw` | 同左 | MTP/chat/generate 回归 |
| `build/logs/a5-abi-load.raw` | 同左 | 1B 真实加载 |
| `test/power/results.jsonl` | 同左 | C3 功耗与 tokens/J |
| `test/ceiling/results.jsonl` | 同左 | C0 遥测 |
| `test/compat/results.json` | 同左 | 兼容矩阵 |
| `test/tir-api/p0-gate*.json` | 同左 | P0 门禁输出 |

## 如何复核

1. 论文中的每个数字都带 `（证据：<路径> §<节>）` 或 `（证据：<文件>:<行>）`。
2. 本仓库发布的是论文与图；原始 `.raw`/JSON 体积大且含本机模型路径，未上传。
3. 需要复核某个具体数字时，可按上表定位原文件；复现条件写在论文对应节的“方法/条件”段落里。
