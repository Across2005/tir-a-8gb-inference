# 派发单 W4：第二章收尾（20 模型全量矩阵）

- 挂载蓝图：`docs/blueprints/L2-TP2-final-report.md`

## 1. 写入域

只写 `<WORKSPACE>\docs\reports\2026-11-11-tir-a-final\02c-matrix.md`。其它文件一律只读。

## 2. 读取域与事实包

必读：
- 契约 `<WORKSPACE>\docs\reports\2026-11-11-tir-a-final\00-contract-v2.md`（§2 可读性、§4 证据、§5 结构、§7 分块写入、§8 验收）
- 数据包 `<TIR_ROOT>\test\matrix\full1\data-pack.md`（表 A–E，由 `tools/matrix/emit_report.py` 生成，不经手工誊写）
- 选读原始行：`test\matrix\full1\master.csv`、`raw\<model>\<step>.stdout.log`、`run.json`
- 背景报告：`tir-b\docs\reports\2026-11-11-engine-perf-stability-check.md` §8.3（五模型矩阵先例）、`2026-11-11-stage-technical-report.md` §5（主流对标）

已排除：
- 不要引用 `build/probe/`（一次性产物已删）
- 不要把 `test_prefill` 的 FAIL 一律当模型故障；先看 `prefill_parity_*` 与 `expected_default_verdict` 列
- `spark-x2.5-4b`、`gemma4-26b-a4b` 预期加载失败，失败也是结果

## 3. 接口契约

- 写 `## 2.10 20 模型全量矩阵` 与 `## 2.11 失败、回退与放弃`，文件以 `# 第二部分 开发与实测（续）` 开头（与 02b 续接）。
- 节内不放 `## 数据索引`（索引已在 02a/02b 各自章末；本章如确需，放一个 8 行以上的表即可）。
- 图锚点：§2.10 中放 `<!-- FIG:fig4 -->`、`<!-- FIG:fig5 -->`、`<!-- FIG:fig6 -->`；§2.11 末放 `<!-- FIG:fig8 -->`（图 8 已在 02c 重复出现时删掉 02b 的锚点，由主代理统一处理，不要改 02b）。
- 正文不出现内部步骤代号（S0–S12 只在表格"条件"列出现）。

## 4. 验收标准

- 汉字 ≥ 4000；四段式 grep 为 0；禁词 grep 无输出；`grep -c MORE` 为 0
- 行内 `（证据：` ≤ 4；表格 ≤ 3
- 全部数字来自 data-pack.md 或 master.csv，禁止另行估算
- 至少写清：哪些模型跑通、哪些失败及失败阶段、哪些参数被夹（ctx/prompt 档降级）、TTFT 随长度的趋势、能耗与 roofline 的关系
- 失败要写"到哪一步、什么签名、显存多少"，不要只写"失败"

## 5. 停止条件

- data-pack 与 master.csv 数字不一致 → 停，报告冲突，不猜
- 需要新跑 GPU → 写"未测"
- 越界写入 → 停

## 6. 回收格式

契约 §10 六项：任务标识、状态、产出路径、验收命令与输出、未解决问题、是否越界。

## 7. 蓝图挂载点

回收后由主代理回填 `L2-TP2-final-report.md` 执行记录，并抽查 10 个数字回源。
