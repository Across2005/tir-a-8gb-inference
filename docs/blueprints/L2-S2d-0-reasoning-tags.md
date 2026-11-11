# L2 切片蓝图：S2d-0 暴露 reasoning tags

- 所属 L0：`docs/blueprints/L0-system.md` M1/M2
- 所属 L1：`docs/blueprints/L1-interactive-runtime.md`
- 日期：2026-11-09
- 状态：待执行

## 交付物

`tir_model_meta` JSON 追加 reasoning 相关字段：

- `thinking_start_tag`（如 `<think>`）
- `thinking_end_tags`（数组，如 `["</think>"]`）
- `additional_stops`（数组）
- `supports_thinking`（bool）

宿主/后续 `tir-server` 不再硬编码 `<think>`，而是从 meta 读取。

## 切片检查表

| 检查项 | 是 / 否 |
|---|---|
| 预计 ≤30 分钟？ | 是（约 20 分钟） |
| 修改文件 ≤2 个（测试不计）？ | 是：`tir_chat.cpp` + `ABI.md`（测试 `test_chat.c` 不计） |
| 垂直切片？ | 是：meta → JSON → host 可读 |
| 独立验收？ | 是 |
| 写域不重叠？ | 是 |

## 涉及文件

- 写：
  - `src/llama.cpp-fork/src/tir-api/tir_chat.cpp`
  - `src/llama.cpp-fork/tests/tir-api/test_chat.c`
  - `src/llama.cpp-fork/docs/tir-api/ABI.md`
- 读：`common/chat.h`（`common_chat_params.thinking_start_tag/thinking_end_tags/additional_stops`）
- 禁止：`tir.h` 公共结构、`tir_core.cpp`、`tir_generate.cpp`、`tir_mtp.cpp`、`llama.cpp`/`ggml`/`common` 核心、模型文件

## 设计

1. `tir_model_meta` 已有 `common_chat_templates_ptr tmpls`；在 `has_chat_template` 分支内：
   - 构造一个最小 `common_chat_templates_inputs`（1 条 user `"x"`，`enable_thinking=true`，`use_jinja=true`）；
   - 调 `common_chat_templates_apply` 得到 `common_chat_params`；
   - 读 `params.thinking_start_tag`、`params.thinking_end_tags`、`params.additional_stops`、`supports_thinking`。
2. JSON 追加：
   - `"thinking_start_tag":"<think>"`（空串也输出）
   - `"thinking_end_tags":["</think>"]`
   - `"additional_stops":[...]`
   - `"supports_thinking":true/false`
   - 用现有 `json_escape`。
3. 无模板/解析失败：四个字段为空/false，不改变已有字段。
4. `test_chat.c` 断言 qwen9b：
   - meta 含 `"thinking_start_tag":"<think>"`；
   - `"thinking_end_tags"` 含 `"</think>"`；
   - `"supports_thinking":true`；
   - 若实际模板不同，按实际值断言并记录，不硬编码错误值。

## 验收

1. `build\build-tir-api.bat` → `BUILD_OK`。
2. `tir-test-chat.exe` → `test_chat: OK`，打印 start/end tags。
3. `python -m unittest discover -s tools -p "test_compat.py" -v` → 22/22。
4. `build\run-p0-gate.bat` → 4/4、`P0_GATE_OK`。

## 停止条件

- `common_chat_templates_apply` 在 meta 场景失败/需要真实消息 → 只输出空字段，记录；
- 需要改 `tir.h` 结构 → 停止；
- 同一次失败连续 2 次 → 停止。

## 执行记录

| 时间 | 事件 | 证据 |
|---|---|---|
| | | |
