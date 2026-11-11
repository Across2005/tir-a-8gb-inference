# L2 切片蓝图：S1 小模型兼容门禁

- 所属 L0：`docs/blueprints/L0-system.md` M2/M3
- 所属 L1：`docs/blueprints/L1-interactive-runtime.md`（兼容/参数）
- 日期：2026-11-09
- 状态：待执行

## 交付物

一个可重复的小模型兼容门禁：
1. `tier_gguf.py` 输出 `tir.compat/v1` 字段（tensor types、chat template、Q1_0）；
2. `compat_check.py` 纯函数判定 `PASS/WARN/REFUSE`；
3. `run_compat.py` 对 7 个本地 1.1B–9B 模型跑 128-token，写 `test/compat/results.json`；
4. `python -m unittest` 全绿。

不修改引擎热路径、不改 `tir.h`、不做 chat/server。

## 切片检查表

| 检查项 | 是 / 否 |
|---|---|
| 预计 ≤30 分钟完成？ | 否：约 45–60 分钟（4 个 Python 文件 + 测试） |
| 修改文件 ≤2 个？ | 否：`tier_gguf.py`、`compat_check.py`、`run_compat.py`、`test_compat.py`、`models.json`；按协议记录例外（均为工具/测试，不碰引擎） |
| 垂直切片？ | 是：profile → 判定 → 跑模型 → 结果 JSON |
| 有独立验收？ | 是（见下） |
| 写域不重叠？ | 是（仅 `tools/`、`test/compat/`） |

## 涉及文件

- 写：
  - `tools/tier_gguf.py`（追加字段/类型 41；不改现有字段语义）
  - `tools/compat_check.py`（新）
  - `tools/test_compat.py`（新，unittest）
  - `tools/run_compat.py`（新）
  - `test/compat/models.json`、`test/compat/results.json`（输出）
- 读：`tir.h`、`tir-test-abi-load`/`tir-bench`、本地 GGUF
- 禁止：`tir.h`、`tir_core.cpp`、`tir_generate.cpp`、`tir_mtp.cpp`、`llama.cpp`/`ggml`/`common`、模型文件、master

## 设计

### 1. `tier_gguf.py`

- `TYPE_SIZE[41] = (128, 18)`（Q1_0；与 `ggml-common.h` 对齐）。
- 每个 tensor 输出追加 `"type": <int>`；profile 顶层追加：
  - `"tensor_types": ["Q4_K", "Q6_K", ...]`（去重、按出现顺序或字典序）；
  - `"chat_template": true/false`（`tokenizer.chat_template` 是否存在且非空）；
  - `"tied_output": true/false`（无 `output.weight` 时）；
  - `"compat": "tir.compat/v1"`（标记）。
- 不改变已有字段名/语义；Q1_0 的 Bonsai 应能生成 profile。

### 2. `compat_check.py`

纯函数，不读文件：

```python
def check_compat(profile: dict, runtime: dict | None = None,
                 requested_ctx: int = 16384,
                 requested_mtp: bool = False) -> dict:
    ...
```

返回：

```json
{
  "schema": "tir.compat/v1",
  "status": "PASS|WARN|REFUSE",
  "reasons": ["..."],
  "warnings": ["..."],
  "arch": "qwen35",
  "quant": "Q5_K_M",
  "weights_mib": 6324.36,
  "kv_mib": 256.0,
  "capabilities": ["resident","mtp","chat_template"]
}
```

规则（S1）：

1. arch 不在 runtime 支持表 → REFUSE（`unsupported_arch`）。
2. tensor type 不在 CUDA 支持表 → REFUSE（`unsupported_quant`）。
3. `weights_mib + kv_mib + 512` > `vram_mib` → REFUSE（`weights_exceed_vram`）；若 `weights_mib` 在 `vram_mib`~`vram_mib+ram_mib` 之间，reason 用 `tiered_required`（仍 S1 REFUSE）。
4. `requested_ctx > ctx_train` → REFUSE（`ctx_exceeds_train`）。
5. `requested_mtp and not nextn` → WARN（`mtp_fallback`）。
6. 无 `chat_template` → WARN（`no_chat_template`）。
7. 有 vision/mmproj 但 runtime 无 mmproj → WARN（`vision_unsupported`）。
8. 否则 PASS。

Runtime 支持表（S1）：

```python
SUPPORTED_ARCH = {"llama","qwen3","qwen35","gemma4","nemotron_h","glm4","spark2_5"}
SUPPORTED_QUANT = {"F32","F16","BF16","Q4_0","Q4_K","Q5_0","Q5_K","Q6_K","Q8_0","Q1_0"}
```

`Q5_0` 的取证：`nemotron4b`（`NVIDIA-Nemotron-3-Nano-4B-Q4_K_M.gguf`，arch `nemotron_h`）的 263 个 tensor 中 **49 个是 `Q5_0`**（`token_embd.weight` 与每层 `ssm_in`/`ffn_up`；全量分布 `F32` 169、`Q5_0` 49、`Q4_K` 33、`Q6_K` 9、`Q8_0` 3）；该模型在 `9ec16f8` 下 128-token 实测 **100.27 t/s**（复核轮 100.75）。故 `Q5_0` 是 S1 实测路径，不是推断。

`Q4_1`/`Q5_1`/`Q2_K`/`Q3_K`/`Q8_K`/`IQ*` 仍未取证（本地 7 模型中没有张量级样本，也没有 128-token 实测），**不得**加入本表；新增任何类型必须先有 bench 证据再改 L2 与 `SUPPORTED_QUANT`。

### 3. `test_compat.py`（TDD）

至少 8 个用例：

- qwen9b profile（arch qwen35, Q5_K, 6324 MiB, nextn, chat template）→ PASS
- unknown arch → REFUSE
- Q2_0/unsupported quant → REFUSE
- Spark BF16 8229 MiB → REFUSE `weights_exceed_vram`
- gemma26 13755 MiB → REFUSE `tiered_required`
- requested_ctx > ctx_train → REFUSE
- requested_mtp + no nextn → WARN `mtp_fallback`
- no chat_template → WARN `no_chat_template`
- Q1_0 type 41 `tensor_nbytes(41, [128]) == 18`（tier_gguf 单元测试）
- 真实 qwen9b `tier_gguf.py --compat` 包含 `tensor_types/chat_template`（存在模型才跑）

### 4. `run_compat.py`

- 读 `test/compat/models.json`（7 个模型，字段：name/path/arch/quant/mtp）。
- 对每个模型：
  1. 运行 `tier_gguf.py <path> --ctx 16384 --kv q4_0` → profile；
  2. `compat_check.check_compat(profile, vram_mib=8000, requested_mtp=mtp)`；
  3. 若 status != REFUSE，运行 `tir-bench.exe <path> 16384 <mtp>`（128 token，1 warmup + 3 measured）；
  4. 解析最后一行 JSON；写 `test/compat/results.json`。
- 结果字段：name/arch/quant/status/reasons/warnings/weights_mib/kv_mib/tok_s_avg/tok_s_best/acceptance/mean_len。
- 任一非 REFUSE 模型 bench 失败 → 结果 `status=FAIL`，脚本 exit 1；REFUSE 不算失败（记录原因）。

## 验收标准（≥2 条，可运行）

1. `python -m unittest discover -s tools -p "test_compat.py" -v` → 全部 PASS（红→绿）。
2. `python tools/tier_gguf.py <qwen9b> --compat` → JSON 含 `tensor_types`、`chat_template`。
3. `python tools/run_compat.py` → `test/compat/results.json` 有 7 个模型；7/7 `status=OK`；qwen9b MTP `tok_s_avg ≥65`。
4. `python tools/tier_gguf.py <Bonsai> --compat` → 不再因 type 41 失败。

## 停止条件

- 测试无法先红（模块已存在或测试无效）→ 停止，重写测试。
- `tier_gguf` 改字段导致现有 `tier_plan.py` 失败 → 回退，保持向后兼容。
- 某模型 128-token OOM/崩溃 → 记录 FAIL，不伪造；先修兼容门禁。
- 需要改引擎/ABI → 停止，留给 S1b。

## 执行记录

| 时间 | 事件 | 证据 |
|---|---|---|
| | | |
