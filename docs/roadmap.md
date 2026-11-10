# Roadmap（设计，未实现）

本文件只记录下一步的设计方向，不代表仓库已包含这些实现。每条给出动机、验收方式与停止条件。

## 1. ModelTraits：把架构策略从代码移到模型元数据

**现状**：`tir_generate.cpp` 里的默认批策略是硬编码白名单：`llama/qwen3/qwen35/nemotron_h → 512`，`nextn > 0 → 2`，其它 → 1。

**动机**：新增模型要改代码、重编译；而 GGUF 里已经有 `general.architecture`、`nextn`、混合 SSM 标志、tokenizer 与模板。策略应该由数据决定，不是由一张常量表决定。

**设计**：

- 定义 `ModelTraits { arch, has_nextn, hybrid_ssm, tokenizer_kind, template_kind, default_prefill, exact_parity_batch }`。
- 启动时从 GGUF metadata 填充；未知字段走保守默认（prefill=1）。
- 白名单只保留在“已验证”名单里，用于把已知安全值提升到 512；未知架构仍然 1。
- traits 进入 `tir_model_meta` 的输出（append-only），宿主可读。

**验收**：

1. 对现有五个模型，traits 输出与当前策略一致；`tir-test-prefill` 全绿。
2. 人为构造一个未知 arch 的 GGUF metadata，默认批必须是 1。
3. 不改变公共 ABI 的既有字段。

**停止条件**：需要改 `tir.h` 或改变已冻结的函数签名。

## 2. OpenAI 兼容层（tir-server）

**现状**：仓库只有 C ABI；没有 HTTP/SSE 层。

**设计**：

- 独立进程或独立 DLL 之上的轻量服务，调用 `tir_session_generate`。
- 路由：`GET /health`、`POST /v1/chat/completions`、`POST /v1/completions`。
- 流式：SSE；`on_token` 回调写入事件队列，客户端断开触发 `tir_session_cancel`。
- 模板：用 `tir_chat_apply_ex` 渲染，不在服务层拼字符串。
- 只支持单并发；并发请求排队，不伪装多 session。

**验收**：

1. `curl /v1/chat/completions` 流式返回，首 token 与 C ABI 直调一致。
2. 客户端断开后，`tir_session_generate` 在 1 个 token 内返回 `TIR_E_CANCELLED`。
3. 错误码映射：`TIR_E_INVALID → 400`、`TIR_E_OOM → 503`、其余 `500`。

**停止条件**：需要多 session 才能满足并发；那属于另一个容量问题，不在本项。

## 3. 多轮 KV / 前缀复用

**现状**：每次 `tir_session_generate` 都 `llama_memory_clear`，多轮聊天会把整段历史重新 prefill。

**动机**：520 token 的重复 prefill 是 0.15–0.25 s；4k 上下文是秒级。这是交互体验里剩下最大的一块，而且不撞 HBM 墙。

**设计**：

- session 内保存上一轮 token 序列与位置。
- 新一轮先算公共前缀，trim 到公共前缀后再 prefill 增量；混合 SSM 模型需要验证回滚语义。
- 前缀不匹配或模型不支持时，回退到全量 prefill；默认行为不变。

**验收**：

1. 同一 session 连续两轮，第二轮 TTFT 明显低于首轮。
2. 增量 prefill 与全量 prefill 的 greedy token 完全一致。
3. 前缀完全不匹配时，结果与全量路径一致。

**停止条件**：hybrid SSM 回滚无法保证一致，或需要改公共 ABI。

## 4. 9B 3-row verify 优化

**现状**：9B MTP w2 是 27.7 ms/step；100 tok/s 需要 ≤23.7 ms。

**设计**：先做逐 kernel 计时，确认 3-row verify、attention、回滚各占多少；再决定是融合、换 kernel 还是减少回滚。没有测量前不改代码。

**验收**：step ≤24 ms 且 64-token parity 不变；否则回退。

**停止条件**：优化后 parity 失败，或收益 <5%。

## 非目标

- **多模型热切换**：8 GiB 显存下，9B + MTP 峰值 7607 MiB；切换必须先完整卸载再加载，当前没有验证过的卸载/重载路径，也不在路线图内。
- 多人并发、多 session 服务。
- 8B 100 tok/s、9B 100 tok/s 的硬承诺。
- 把磁盘当显存（只作容量层）。
