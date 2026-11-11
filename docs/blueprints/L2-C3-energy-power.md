# L2 切片蓝图：C3 功耗/时钟与 tokens/J

- 所属 L0：`docs/blueprints/L0-system.md`
- 所属 L1：`docs/blueprints/L1-interactive-runtime.md`
- 日期：2026-11-09
- 状态：待执行
- 上游：C0 报告 `<WORKSPACE>\docs\reports\2026-11-09-ceiling-calibration.md`；E 盘可行性 `<WORKSPACE>\docs\reports\2026-11-09-e-drive-feasibility.md`

## 目标

回答“怎样用更少的能量换更多 token”，而不是只看 tok/s：

1. 解码过程中采样 SM/mem clock、power、temp、VRAM；
2. 计算 `J/token` 与 `tokens/J`；
3. 对比默认功耗/时钟与用户设置的低功耗/锁频档；
4. 给出 4B/8B 的效率最优点与温度。

不改模型、不改引擎、不改 token 语义。

## 方法

`test/bench-power.ps1`：

- 用 `Start-Process` 启动 `tir-bench-ceiling.exe`；
- 每 200 ms 读 `nvidia-smi --query-gpu=clocks.sm,clocks.mem,power.draw,temperature.gpu,memory.used`；
- 进程退出后解析 JSON，过滤 `power > 20 W` 的样本；
- 输出：
  - `avg_power_w`、`avg_sm_mhz`、`avg_mem_mhz`、`max_temp_c`；
  - `decode_s`、`gen_tokens`、`j_per_token`、`tokens_per_j`；
  - `label`（default / pl90 / lgc2000 等）。
- 结果追加到 `test/power/results.jsonl`。

运行矩阵：

| 模型 | prompt | gen | 目的 |
|---|---:|---:|---|
| 4B qwen | 128 | 512 | 默认；解码占比高，功耗稳定 |
| 8B DSR1 | 128 | 512 | 默认；看 11001 MHz 降频 |

用户设置档（需要用户手动执行，不由代理提权）：

- 厂商软件的性能/平衡/静音模式；
- 或管理员执行 `nvidia-smi -lgc <MHz>` / `nvidia-smi -pl <W>`（若支持）；
- 每次设置后用 `-Label` 记录。

## 接口契约

- 只读 `tir-bench-ceiling` 的 JSON；不改 ABI；
- `test.power/v1` JSON 字段固定，后续只追加；
- 脚本不修改 GPU 设置，只记录。

## 验收

1. `powershell -File test/bench-power.ps1 -Model <4B> -Ctx 4096 -PromptTokens 128 -NPredict 512 -KvQ4 1 -Runs 1 -Label default` → 一行合法 JSON，`tokens_per_j > 0`、`avg_power_w > 0`、`max_temp_c > 0`。
2. 8B 同样跑一次；`mem_mhz` 与 C0 的 11001 一致或解释差异。
3. `test/power/results.jsonl` 至少 2 行。
4. 报告 `<WORKSPACE>\docs\reports\2026-11-09-energy-power.md` 给出 4B/8B 的 J/token、tokens/J、温度与建议。

## 停止条件

- 采样导致 tok/s 相对 C0 下降 >2% → 采样间隔改 500 ms 或 1 s；
- `nvidia-smi` 在运行中返回 N/A → 记录并用前后采样，标注局限；
- 用户无法设置功耗/时钟 → 只交默认档，明确不外推。

## 写入域

- `test/bench-power.ps1`（新）
- `test/power/results.jsonl`（新）
- `<WORKSPACE>\docs\reports\2026-11-09-energy-power.md`（新）

## 读取域

- `test/bench-ceiling.ps1`
- `test/ceiling/results.jsonl`
- `<WORKSPACE>\docs\reports\2026-11-09-ceiling-calibration.md`
- `nvidia-smi` 查询字段

## 禁止

- 改引擎/模型/量化；
- 代理执行 UAC/管理员命令；
- 改 GPU 设置后不记录；
- 提交/推送。
