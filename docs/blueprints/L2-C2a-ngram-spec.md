# L2 切片蓝图：C2a ngram 自投机（env-gated spike）

- 日期：2026-11-09
- 状态：已执行；结论见 `<WORKSPACE>\docs\reports\2026-11-09-ngram-spec.md`
- 上游：C0 报告；用户选择“4B ngram 投机”
- 目标：验证 ngram 自投机能否在 **不增加显存、不改 token 语义** 的前提下，把 4B 的 tok/s 拉高

## 假设

- 一次 target forward 读 2.7 GB 权重；如果 ngram 能提供 1 个高接受率 draft，target verify 2 行可多产 1 个 token。
- qwen3.5 hybrid 的 3+ 行 verify 会移动 logits，因此 **n_max 固定 1**，保持 2 行 verify 与顺序 decode 逐位一致。
- ngram 不需要 draft 模型/额外 VRAM；只复用 target context。

## 实现

新增 `TIR_SPEC_TYPE=ngram`（默认无此变量 = 原 MTP 路径）：

1. `tir_core.cpp`：
   - 读取 `TIR_SPEC_TYPE`；ngram 时 `mp.load_mtp=false`，且无 nextn 不把 `engine->mtp` 重置为 0；
   - `cp.n_rs_seq` 仍为 1（需要回滚 1 个 draft）。
2. `tir_mtp.cpp`：
   - `mtp_params`：ngram 时 `types={NGRAM_SIMPLE}`，`ngram_simple={size_n=12,size_m=48,min_hits=1}`；
   - `ensure_mtp_state`：允许 `init->context()==nullptr`（ngram 不需要 draft context）；仍创建 `common_speculative`；
   - `tir_generate_mtp`：ngram 无 nextn 不报错；所有 `ctx_dft` 访问加 null guard；
   - `n_draft_max` 统一 `min(..., TIR_MTP_N_MAX)`，防止 ngram 一次提 48 个 draft。
3. 未设置 `TIR_SPEC_TYPE` 时，MTP 行为逐字节不变。

## 测试

新增 `tests/tir-api/test_spec.c`：

- `opt.mtp=1`；生成 64 token 两次，比较 token id；
- `TIR_SPEC_TYPE=ngram` 时用 4B；无变量时可用于有 nextn 的模型；
- 断言 `mean_len >= 1.0`、`gen_tokens > 0`、两次 token 完全一致；
- 输出 `test_spec: OK tokens=... mean_len=... acceptance=...`。

基准：

- `TIR_SPEC_TYPE=ngram build\run-ceiling.bat <4B> 4096 128 128 1 3 64` vs plain；
- 记录 `mean_len`、`acceptance`、tok/s；
- prompt 用重复段落（ngram 更容易命中），另用自然 prompt 对照。

## 验收

1. `build\build-tir-api.bat` → `BUILD_OK`。
2. `TIR_SPEC_TYPE=ngram test_spec` → 两次 64 token 完全一致，`mean_len >= 1.0`。
3. 4B ngram vs plain：tok/s 增益 >5% 且 mean_len >1.1 → 值得集成；否则记录“无收益”并关闭。
4. 默认（无 env）`test_generate`/`test_profile` 不回归。

## 停止条件

- 任何 token 不一致 → 停止，n_max 退回 1 仍不一致则放弃；
- ngram `mean_len < 1.05` → 判定对该 prompt 分布无收益，不做生产集成；
- 崩溃/上下文回滚错误 → 停止，不改 MTP 默认路径。

## 写入域

- `src/llama.cpp-fork/src/tir-api/tir_core.cpp`
- `src/llama.cpp-fork/src/tir-api/tir_mtp.cpp`
- `src/llama.cpp-fork/tests/tir-api/test_spec.c`（新）
- `src/llama.cpp-fork/src/tir-api/CMakeLists.txt`
- `build/build-tir-api.bat`（加 target）
- `<WORKSPACE>\docs\reports\2026-11-09-ngram-spec.md`（结果）

## 读取域

- `common/speculative.cpp` 的 ngram 实现
- `common/common.h` 的 ngram 参数
- `tir_internal.h`、`test_mtp.c`

## 禁止

- 改默认 MTP 路径的语义；
- 改 `TIR_MTP_N_MAX`；
- 为 ngram 加载 draft 模型；
- 提交/推送。

## 执行记录

| 时间 | 事件 | 证据 |
|---|---|---|
| 2026-11-09 | `size_n=12,size_m=1`：`drafted=0`；根因 `copy_max < n_draft_min` | `common/ngram-map.cpp` |
| 2026-11-09 | 改 `size_n=1,size_m=1`：重复 prompt `drafted=32/accepted=32`，144.3 t/s | `test_spec: OK ... mean_len=2.000 acceptance=1.000` |
| 2026-11-09 | 自然段落：78.9 t/s、mean_len 1.267、acceptance 0.474，净 −3% | `run-ceiling-ngram.bat` JSON |
| 2026-11-09 | 结论：默认关闭，仅重复/代码文本可选 | `2026-11-09-ngram-spec.md` |
