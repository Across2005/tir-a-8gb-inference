# L2 切片蓝图：S2c 思考开关（enable_thinking）

- 所属 L0：`docs/blueprints/L0-system.md` M1/M2
- 所属 L1：`docs/blueprints/L1-interactive-runtime.md`
- 日期：2026-11-09
- 状态：完成（`3c4d615` 实现 + `docs(tir-api): clarify enable_thinking is render-only` 评审修复）

## 交付物

`tir_chat_apply_ex` 支持 `enable_thinking = 1/0/-1`，宿主可以控制 GGUF chat template 是否插入 `<think>`；原 `tir_chat_apply` 行为不变。

## 切片检查表

| 检查项 | 是 / 否 |
|---|---|
| 预计 ≤30 分钟？ | 是（约 25 分钟） |
| 修改文件 ≤2 个？ | 否：`tir.h`、`tir_chat.cpp`、`test_chat.c`、ABI.md；记录例外（ABI + 实现 + 测试） |
| 垂直切片？ | 是：options → template → prompt 断言 |
| 有独立验收？ | 是 |
| 写域不重叠？ | 是 |

## 涉及文件

- 写：
  - `src/llama.cpp-fork/src/tir-api/tir.h`
  - `src/llama.cpp-fork/src/tir-api/tir_chat.cpp`
  - `src/llama.cpp-fork/tests/tir-api/test_chat.c`
  - `src/llama.cpp-fork/docs/tir-api/ABI.md`
- 读：`common/chat.h`（`common_chat_templates_inputs.enable_thinking`）
- 禁止：`tir_generate.cpp`、`tir_mtp.cpp`、`tir_core.cpp`、`llama.cpp`/`ggml`/`common` 核心、模型文件

## 设计

### ABI（append-only）

```c
typedef struct tir_chat_options {
    uint32_t struct_size;
    uint32_t version;
    int32_t add_generation_prompt; /* 1/0 */
    int32_t enable_thinking;       /* 1 on, 0 off, -1 template default */
} tir_chat_options;

TIR_API tir_status tir_chat_apply_ex(tir_engine * engine,
                                     const tir_chat_message * msgs, size_t n_msgs,
                                     const tir_chat_options * opt,
                                     char * out, size_t cap, size_t * out_len);
```

- `opt == NULL`：`add_generation_prompt=1`、`enable_thinking=-1`。
- 校验 `struct_size/version`；`enable_thinking` 只允许 -1/0/1；`add_generation_prompt` 0/1。
- 原 `tir_chat_apply` 内部转调 `_ex`，默认行为不变。
- `common_chat_templates_inputs.enable_thinking = (opt.enable_thinking >= 0 ? opt.enable_thinking != 0 : true)`。
- 其余 buffer/错误语义不变。

## 验收

1. `build\build-tir-api.bat` → `BUILD_OK`。
2. `tir-test-chat.exe` → `test_chat: OK`，并打印：
   - `think_on` prompt 含 `<think>`；
   - `think_off` 在 qwen9b 上是 **closed empty** `<think>\n\n</think>\n\n` 块（121 B，比 on 的 110 B 更长）；测试按真实模板形状断言，不要求“无 think/更短”；
   - `default`（原 `tir_chat_apply`）与 `enable_thinking=1` 字节一致；
   - `opt` struct_size/version/enable_thinking 非法 → `TIR_E_INVALID`。
3. `python -m unittest discover -s tools -p "test_compat.py" -v` → 22/22。
4. `build\run-p0-gate.bat` → 4/4、`P0_GATE_OK`。

## 停止条件

- qwen9b 模板不认 `enable_thinking`，两种模式无差异 → 记录，S2c 只做“透传字段”，不硬改模板；
- 需要改 `common_chat` 核心 → 停止；
- 同一次失败连续 2 次 → 停止。

## 执行记录

| 时间 | 事件 | 证据 |
|---|---|---|
| 2026-11-09 | RED | 先加 `test_chat.c` 断言再构建：`BUILD_FAILED=2`，`test_chat.c(269): error C2224: 左操作数不是结构/联合体`、`error C2065: 'bado': 未声明的标识符`（`tir_chat_options` / `tir_chat_apply_ex` 尚未声明，同一组错误沿 269-295 行） |
| 2026-11-09 | GREEN | `build-tir-api.bat` → `BUILD_OK`；`tir-test-chat.exe` EXIT=0，`prompt len=110`、`default_len=110`、`think_on_len=110`、`think_off_len=121`，`test_chat: OK ... think_switch abi_negatives` |
| 2026-11-09 | 模板实测 | qwen3.8 模板不删 `<think>`：on 尾部 `<\|im_start\|>assistant\n<think>\n`（打开块，110 字节），off 尾部 `...<think>\n\n</think>\n\n`（预闭合空块，121 字节），差异恰为 11 字节；断言按真实不变量写，不按任务原假设写 |
| 2026-11-09 | 验收 | `test_compat.py` → `Ran 22 tests ... OK`（22/22）；`run-p0-gate.bat` EXIT=0，4/4（tir-test-abi / tir-test-abi-load / tir-test-generate / tir-test-mtp），`P0_GATE_OK tok_s_avg=70.55 target=45` |
| 2026-11-09 | 评审修复 | ABI.md：`enable_thinking` 改为「只改渲染 prompt，不保证生成侧不再产生推理」，分离/隐藏推理归 S2d parser；非法 options 计数 3 → 4（struct_size / version / enable_thinking / add_generation_prompt）。test_chat.c：`enable_thinking=1` 增加与 `tir_chat_apply` 的逐字节 `strcmp`，新增 `struct_size = sizeof+4` 正向用例（前向兼容更大的结构体） |
| 2026-11-09 | 验收（修复后） | `BUILD_OK`；`test_chat: OK ... think_switch opt_forward abi_negatives`，`think_on_len=110`、`think_off_len=121`、`opt struct_size=20 (sizeof+4) accepted`；compat 22/22；`run-p0-gate.bat` 4/4、`P0_GATE_OK tok_s_avg=74.60 target=45` |
