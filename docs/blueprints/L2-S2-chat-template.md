# L2 切片蓝图：S2 GGUF chat template + 模型元数据

- 所属 L0：`docs/blueprints/L0-system.md` M1/M2
- 所属 L1：`docs/blueprints/L1-interactive-runtime.md`
- 日期：2026-11-09
- 状态：待执行

## 交付物

宿主可以：
1. 读取模型元数据 JSON（arch、ctx、nextn、chat_template、bos/eos）；
2. 把 OpenAI 风格 messages 用 GGUF `tokenizer.chat_template` 格式化成 prompt；
3. 用现有 `tir_session_generate` 生成对话。

不实现 HTTP/SSE server；server 是 S2b/S3。

## 切片检查表

| 检查项 | 是 / 否 |
|---|---|
| 预计 ≤30 分钟完成？ | 否：约 45 分钟（ABI + 实现 + 测试） |
| 修改文件 ≤2 个？ | 否：`tir.h`、`tir_internal.h`、`tir_chat.cpp`、CMake、测试；记录例外（新增函数/新 TU） |
| 垂直切片？ | 是：meta → chat format → generate 链路 |
| 有独立验收？ | 是 |
| 写域不重叠？ | 是（仅 ABI/chat TU/测试） |

## 涉及文件

- 写：
  - `src/llama.cpp-fork/src/tir-api/tir.h`（append-only）
  - `src/llama.cpp-fork/src/tir-api/tir_chat.cpp`（新）
  - `src/llama.cpp-fork/src/tir-api/tir_internal.h`（如需要内部声明）
  - `src/llama.cpp-fork/src/tir-api/CMakeLists.txt`
  - `src/llama.cpp-fork/tests/tir-api/test_chat.c`
  - `src/llama.cpp-fork/docs/tir-api/ABI.md`（新增函数/结构说明）
- 读：`tir_core.cpp`、`common/chat.h`、`common/speculative.h`
- 禁止：`tir_core.cpp` 的 generate 逻辑、`tir_generate.cpp`、`tir_mtp.cpp`、`llama.cpp`/`ggml`/`common` 核心、模型文件

## 设计

### 1. 公共 ABI（append-only）

```c
#include <stddef.h>

typedef struct tir_chat_message {
    uint32_t struct_size;
    uint32_t version;
    const char * role;     /* "system" | "user" | "assistant" */
    const char * content;  /* UTF-8 */
} tir_chat_message;

/* cap==0: 只写 required length 到 out_len，返回 TIR_OK */
TIR_API tir_status tir_model_meta(tir_engine * engine,
                                  char * buf, size_t cap, size_t * out_len);

TIR_API tir_status tir_chat_apply(tir_engine * engine,
                                  const tir_chat_message * msgs, size_t n_msgs,
                                  int32_t add_generation_prompt,
                                  char * out, size_t cap, size_t * out_len);
```

- 现有 11 函数/结构不变；只追加。
- 失败：`TIR_E_INVALID`（参数/缓冲区不足）、`TIR_E_MODEL`（无 chat template/未加载）。
- `out_len` 不含 NUL；实际写入 NUL 终止（cap 足够时）。

### 2. `tir_model_meta`

返回 JSON（UTF-8），字段：

```json
{
  "schema": "tir.model-meta/v1",
  "arch": "qwen35",
  "n_layer": 32,
  "n_embd": 4096,
  "n_ctx_train": 262144,
  "n_vocab": 248320,
  "nextn": 1,
  "mtp": true,
  "bos": 151643,
  "eos": 151645,
  "chat_template": "<|im_start|>...",
  "has_chat_template": true
}
```

- `arch`：`llama_model_meta_val_str(model, "general.architecture")`。
- `chat_template`：`tokenizer.chat_template` 原文；JSON 转义。
- 先写小工具 `json_escape()`；不要引入 JSON 库。
- `nextn`：`llama_model_n_layer_nextn`；`mtp`：nextn>0。
- `bos/eos`：`llama_vocab_bos/eos`。

### 3. `tir_chat_apply`

- `common_chat_templates_init(engine->model, "")`；无模板 → `TIR_E_MODEL`。
- 构造 `common_chat_templates_inputs`：
  - messages → `common_chat_msg{role,content}`；
  - `add_generation_prompt` 来自参数；
  - `use_jinja=true`；
  - `add_bos=false`, `add_eos=false`（由模板/生成器处理）。
- `common_chat_templates_apply` → `params.prompt.str()`。
- 拷贝到 out；cap 不足返回 `TIR_E_INVALID` 并写 required。
- 支持多轮 messages 顺序；空 messages → `TIR_E_INVALID`。

### 4. 测试 `test_chat.c`

- 加载 qwen9b（`TIR_TEST_MODEL`），`tir_model_meta(engine, NULL, 0, &len)` → OK，len>0；分配后读取，断言包含：
  - `"arch":"qwen35"`、`"has_chat_template":true`、`"nextn":1`。
- `tir_chat_apply` messages：system "You are helpful." + user "Hello."，cap=0 取长度；读取；断言包含 `Hello.`、`system`/`user` 标记（模板相关，用 `strstr` 至少含 "Hello." 和非空）。
- 非法参数：空 messages、cap 太小 → `TIR_E_INVALID`。
- 用 `#undef NDEBUG`；`LLAMA_DISK_STREAM_MB=0`。

## 验收标准（≥2 条）

1. `python -m unittest discover -s tools -p "test_compat.py" -v` → 22/22（无回归）。
2. `cmake --build build/tir-api --target tir-test-chat -- -j 8` → 成功。
3. `build\tir-api\bin\tir-test-chat.exe` → `test_chat: OK`，打印 meta 长度和 chat prompt 前 80 字符。
4. `build\run-p0-gate.bat` → 4/4、`P0_GATE_OK`（无回归）。

## 停止条件

- `common_chat_templates_init` 对 qwen9b 失败/模板为空 → 记录错误，不伪造；
- 需要改 `tir_core.cpp` 既有 generate 逻辑 → 停止；
- 需要改 llama.cpp/ggml/common 核心 → 停止；
- buffer/JSON 转义引入崩溃 → 修工具，不放宽测试。

## 执行记录

| 时间 | 事件 | 证据 |
|---|---|---|
| | | |
