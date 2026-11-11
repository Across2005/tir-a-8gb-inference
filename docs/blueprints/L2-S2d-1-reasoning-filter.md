# L2 切片蓝图：S2d-1 纯流式 reasoning/content 过滤器

- 所属 L0：`docs/blueprints/L0-system.md` M1/M2
- 所属 L1：`docs/blueprints/L1-interactive-runtime.md`
- 日期：2026-11-09
- 状态：已执行（`56d51f8`）；S2d1-FIX 修订了跨 chunk 与 content/tool_call 语义，见「语义」与「执行记录」

## 交付物

一个不依赖 GPU/网络的 C++ `ReasoningFilter`：把模型增量文本切成 `reasoning` / `content` / `tool_call` / `stop` 事件，支持跨 chunk 的 tag 与 stop 匹配。

不实现 HTTP/SSE；S2d-2 再包 server。

## 切片检查表

| 检查项 | 是 / 否 |
|---|---|
| 预计 ≤30 分钟？ | 是（约 25 分钟） |
| 修改文件 ≤2 个（测试不计）？ | 是：`src/tir-server/stream.h` + `stream.cpp`（+ CMake） |
| 垂直切片？ | 是：输入 chunk → 事件 → 单测 |
| 独立验收？ | 是 |
| 写域不重叠？ | 是（新目录 `src/tir-server/`、`tests/tir-server/`） |

## 涉及文件

- 写：
  - `src/tir-server/stream.h`
  - `src/tir-server/stream.cpp`
  - `src/tir-server/CMakeLists.txt`
  - `tests/tir-server/test_stream.cpp`
  - `src/llama.cpp-fork/CMakeLists.txt`（仅 `add_subdirectory(src/tir-server)`，受 `TIR_BUILD_API` 控制）
- 读：`docs/tir-api/ABI.md`（S2d-0 tag 语义）
- 禁止：`tir.h`、`tir_core.cpp`、`tir_chat.cpp`、`tir_generate.cpp`、`tir_mtp.cpp`、`llama.cpp`/`ggml`/`common` 核心、模型文件

## 接口

```cpp
namespace tir::stream {

enum class Kind { Reasoning, Content, ToolCall, Stop, Done };

struct Event {
    Kind kind;
    std::string text;       // payload; Stop: matched stop; ToolCall: matched opener
    std::string reason;     // Stop: "stop" | "length" | "tool_call" | ""
};

class ReasoningFilter {
public:
    ReasoningFilter(std::string start_tag,
                    std::vector<std::string> end_tags,
                    std::vector<std::string> stops,
                    bool starts_in_reasoning = true);

    // Feed one token piece. final=true flushes pending text.
    std::vector<Event> feed(std::string_view piece, bool final = false);

    bool stopped() const;
};

}
```

## 语义（按 ABI.md）

- `starts_in_reasoning=true`：生成从 reasoning 开始（prompt 已包含 `<think>`）。
- 每个段有一组活动模式：
  - reasoning 段：`end_tags` + `<tool_call>`（列表里没有也补上）+ `stops`；
  - content 段：`stops` + `<tool_call>`。
- 最早匹配优先；同位置按列表顺序（`"\n</think>"` 会先于 `"</think>"`，`stops` 先于 opener）。
- reasoning 段内的 `end_tags`：
  - 匹配的 terminator 本身不进入 reasoning 文本；`"\n</think>"` 连前导换行一起消费；
  - 匹配后切到 content；
  - `"<tool_call>"` 是工具调用入口：发 `ToolCall`，流结束。
- `stops`（= `additional_stops`）是生成级 stop，两段都扫：匹配前文本按当前段发出，然后
  `Stop{reason="stop"}`，丢弃剩余（含之后的 chunk）。
- content 段内的 `"<tool_call>"` opener 同样发 `ToolCall` 并结束流：`starts_in_reasoning=false`
  的 run、或模型先发 `</think>` 再发 opener 时，opener 和它后面的 tool JSON 都不能作为 Content。
- `end_tags` 只在 reasoning 段扫描：切到 content 之后模型再发 `</think>` 属于普通 Content 文本
  （不忽略、不二次切换），是否清洗由 S2d-2 决定。
- 跨 chunk：发安全前缀。有完整匹配时发匹配前文本并处理 terminator/stop；没有完整匹配且非 final
  时，取 pending buffer 中「最长同时是某个活动模式真前缀的后缀」，它之前的部分按当前段发出，只留
  这个后缀；`final=true` 时把 pending 全部按当前段发出。因此 `feed("abc\n</thi")` 发
  `Reasoning("abc")` 并只留 `"\n</thi"`。
- 空白规则：terminator 之后紧跟的连续 `\n` 全部消费（模板用换行关闭块，用例 2 的 `"\n\n"` 一并
  消费）；仅此一处，reasoning/content 段首的空白一律保留。
- 没有 tag/stop：reasoning 段发 Reasoning，content 段发 Content。
- 空 chunk：不产生事件（除非 final 有待发文本）。
- 文本按字节处理，UTF-8 码点允许在 chunk 边界被切开；事件文本拼接后与输入一致。
- 事件文本是副本，调用者拥有。

## 测试（`test_stream.cpp`，无 GPU）

0. 空 chunk（含 final）不产生事件。
1. `starts_in_reasoning=true`，`"I think"` → Reasoning。
2. `"abc\n</think>\n\nHello"` → Reasoning("abc") + Content("Hello")；换行不被留下。
3. 跨 chunk：`"abc\n</thi"` → Reasoning("abc")（安全前缀立刻发，只留 `"\n</thi"`），
   `"nk>Hi"` → Content("Hi")。
4. `"abc<tool_call>{\"x\":1}"` → Reasoning("abc") + ToolCall("<tool_call>")；之后不再 Content。
5. stop 跨 chunk：`"Hello ST"` → Content("Hello ")，`"OP world"` → Stop("STOP")；`stopped()==true`。
5b. stop 在 offset 0：`"STOP rest"` → 只有 Stop，无空 Content 事件。
6. 无 tag：`starts_in_reasoning=false`，`"plain"` → Content("plain")。
7. `final=true` 且有未决前缀：`"abc<thi"` → Reasoning("abc<thi")；`"abc<tool"` → Reasoning("abc")，
   final → Reasoning("<tool")（不是丢弃）。
8. 空 end_tags/stops：全部按当前段输出。
9. `<tool_call>` 跨 chunk（reasoning 段）：`"abc<tool_"` → Reasoning("abc")，
   `"call>{\"x\":1}"` → ToolCall；之后无事件。
10. content 段 opener：`starts_in_reasoning=false`，`"abc<tool_"` + `"call>{\"x\":1}"` →
    Content("abc") + ToolCall；opener 之后的 tool JSON 不出现。
10b. 同段先 `</think>` 再 opener：stray closer 作 Content，opener 仍是 ToolCall。
11. terminator 在 offset 0：`"</think>Hello"` → Content("Hello")，无空 Reasoning。
12. content 段里再出现 `</think>` → Content（end_tags 只在 reasoning 段扫描），显式行为。
13. `stops` 在 reasoning 段也生效：`"think ST"` → Reasoning("think ")，`"OP rest"` → Stop。
14. UTF-8 码点按字节拆开喂入（reasoning 与 content 各一组）：事件文本拼接后等于原文本。

## 验收

1. `cmake --build build/tir-api --target tir-test-stream -- -j 8` → 成功。
2. `build\tir-api\bin\tir-test-stream.exe` → `test_stream: OK`，上述全部用例（原 8 项 + 5b、9-14）全过。
3. `build\run-p0-gate.bat` → 4/4 `P0_GATE_OK`（无回归）。
4. `python -m unittest discover -s tools -p "test_compat.py" -v` → 22/22。

## 停止条件

- tag 匹配语义与 ABI.md 冲突 → 停止，按 ABI.md 为准；
- 需要修改 DLL/引擎 → 停止；
- 跨 chunk 测试无法稳定 → 先简化（buffer-all）并记录；
- 同一失败连续 2 次 → 停止。

## 执行记录

| 时间 | 事件 | 证据 |
|---|---|---|
| 2026-11-09 | S2d-1 实现、单测、验收 | `56d51f8`；`test_stream: OK`；兼容 22/22；`P0_GATE_OK` |
| 2026-11-09 | S2d1-FIX：content 段识别 `<tool_call>`、reasoning 段扫 `stops`、改安全前缀切分、补跨 chunk/UTF-8 用例 | `test_stream: OK`；兼容 22/22；`P0_GATE_OK tok_s_avg=77.80` |
| | | |
