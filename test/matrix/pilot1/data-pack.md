# 数据包（pilot1）

行数 10，模型 1。表格由 `tools/matrix/emit_report.py` 直接生成，未经手工誊写。

## 表 A 规格

| 模型 | arch | 权重 GiB | 层数 | ctx_train | KV MiB | 跑通 |
|---|---|---|---|---|---|---|
| minicpm5-1b | llama | 0.64 | 24 | 131072 | 96 | yes |

## 表 B 速率与 TTFT

| 模型 | plain tok/s | MTP tok/s | acceptance | TTFT S ms | TTFT M ms | TTFT L ms |
|---|---|---|---|---|---|---|
| minicpm5-1b | 317.4 | - | - | 23.6 | 141.6 | 678.8 |

## 表 C 能耗

| 模型 | 平均功耗 W | SM MHz | 显存 MHz | J/token | tokens/J |
|---|---|---|---|---|---|
| minicpm5-1b | 26.98 | 2125 | 12001 | 0.0883 | 11.328 |

## 表 D prefill parity

| 模型 | 5 tok | 130 tok | 520 tok | default match | 预期判定 |
|---|---|---|---|---|---|
| minicpm5-1b | OK | OK | OK | - | PASS |

## 表 E 失败与异常

无


## 口径

- 速率：128 token，1 warmup + 3 测量，取三轮均值；ctx 16384（放不下时用实测可行档）。

- TTFT：ceiling harness，目标 128/2048/8192 token，实际 token 从 JSON 读回，prefill_batch=512。

- 能耗：200 ms 轮询，仅统计 power>20 W 的样本，J/token 按 decode 窗口折算。

- parity：test_prefill 内建三档，default 列的 `match` 是引擎默认批与显式 512 的对照。

