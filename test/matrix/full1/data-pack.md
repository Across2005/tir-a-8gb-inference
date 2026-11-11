# 数据包（full1）

行数 201，模型 20。表格由 `tools/matrix/emit_report.py` 直接生成，未经手工誊写。

## 表 A 规格

| 模型 | arch | 权重 GiB | 层数 | ctx_train | KV MiB | 跑通 |
|---|---|---|---|---|---|---|
| bonsai-27b-q1_0 | qwen35 | 3.53 | 64 | 262144 | 256 | yes |
| dsr1-8b-q4km | qwen3 | 4.68 | 36 | 131072 | 576 | yes |
| gemma4-12b-q4_0 | gemma4 | 6.48 | 48 | 262144 | 144 | yes |
| gemma4-26b-a4b | gemma4 | 13.43 | 30 | 262144 | - | no |
| glm4.6v-q4km | glm4 | 5.73 | 40 | 131072 | 160 | yes |
| minicpm5-1b | llama | 0.64 | 24 | 131072 | 96 | yes |
| nemotron-4b-q4_0 | nemotron_h | 2.28 | 42 | 1048576 | 64 | yes |
| nemotron-nano-4b-q4km | nemotron_h | 2.63 | 42 | 1048576 | 64 | yes |
| q3.5-9b | qwen35 | 5.23 | 32 | 262144 | 128 | yes |
| qwen3-0.6b-q8 | qwen3 | 0.59 | 28 | 40960 | 448 | yes |
| qwen35-0.8b-q4km | qwen35 | 0.49 | 24 | 262144 | 48 | yes |
| qwen35-4.2b-iq4xs | qwen35 | 2.35 | 32 | 262144 | 128 | yes |
| qwen35-4.2b-q3km | qwen35 | 2.10 | 32 | 262144 | 128 | yes |
| qwen35-4.2b-q4_0 | qwen35 | 2.36 | 32 | 262144 | 128 | yes |
| qwen35-opus-4b | qwen35 | 2.51 | 32 | 262144 | 128 | yes |
| qwen9b-q4_0 | qwen35 | 5.07 | 33 | 262144 | 128 | yes |
| qwen9b-q4km | qwen35 | 5.37 | 33 | 262144 | 128 | yes |
| qwen9b-q5km | qwen35 | 6.18 | 33 | 262144 | 128 | yes |
| qwythos9b | qwen35 | 5.23 | 32 | 1048576 | 128 | yes |
| spark-x2.5-4b | spark2_5 | 7.66 | 36 | 1048576 | 576 | yes |

## 表 B 速率与 TTFT

| 模型 | plain tok/s | MTP tok/s | acceptance | TTFT S ms | TTFT M ms | TTFT L ms |
|---|---|---|---|---|---|---|
| bonsai-27b-q1_0 | 46.1 | - | - | 424.0 | 2720.3 | 10723.9 |
| dsr1-8b-q4km | 59.0 | - | - | 153.0 | 951.4 | 4147.2 |
| gemma4-12b-q4_0 | 10.1 | - | - | 5214.0 | 49089.4 | - |
| gemma4-26b-a4b | - | - | - | - | - | - |
| glm4.6v-q4km | 45.0 | - | - | 167.2 | 1051.3 | 4515.1 |
| minicpm5-1b | 313.9 | - | - | 23.3 | 142.7 | 685.0 |
| nemotron-4b-q4_0 | 116.1 | - | - | 83.7 | 522.1 | 2194.2 |
| nemotron-nano-4b-q4km | 101.8 | - | - | 90.0 | 553.9 | 2271.5 |
| q3.5-9b | 52.9 | - | - | 161.6 | 972.2 | 3768.5 |
| qwen3-0.6b-q8 | 243.6 | - | - | 20.8 | 131.3 | 692.8 |
| qwen35-0.8b-q4km | 274.6 | - | - | 25.4 | 148.2 | 585.1 |
| qwen35-4.2b-iq4xs | 97.0 | - | - | 88.1 | 543.9 | 2201.3 |
| qwen35-4.2b-q3km | 86.2 | - | - | 101.0 | 639.5 | 2564.9 |
| qwen35-4.2b-q4_0 | 96.7 | - | - | 85.0 | 528.9 | 2152.9 |
| qwen35-opus-4b | 84.9 | - | - | 96.2 | 593.1 | 2360.6 |
| qwen9b-q4_0 | 56.8 | 77.3 | 0.767 | 141.1 | 858.7 | 3401.7 |
| qwen9b-q4km | 53.0 | 77.2 | 0.855 | 162.9 | 968.9 | 3771.7 |
| qwen9b-q5km | 47.2 | 75.8 | 1.000 | 169.0 | 1001.5 | 3878.0 |
| qwythos9b | 52.7 | - | - | 162.6 | 969.8 | 3763.5 |
| spark-x2.5-4b | 4.2 | - | - | 4501.3 | - | - |

## 表 C 能耗

| 模型 | 平均功耗 W | SM MHz | 显存 MHz | J/token | tokens/J |
|---|---|---|---|---|---|
| bonsai-27b-q1_0 | 93.54 | 2631 | 10276 | 2.0535 | 0.487 |
| dsr1-8b-q4km | 85.42 | 2556 | 11501 | 1.4781 | 0.676 |
| gemma4-12b-q4_0 | 46.42 | 2780 | 11992 | 7.5516 | 0.132 |
| gemma4-26b-a4b | - | - | - | - | - |
| glm4.6v-q4km | 96.25 | 2668 | 11210 | 2.0630 | 0.485 |
| minicpm5-1b | 26.92 | 1705 | 12001 | 0.0910 | 10.986 |
| nemotron-4b-q4_0 | 62.31 | 2383 | 12001 | 0.5395 | 1.853 |
| nemotron-nano-4b-q4km | 71.30 | 2495 | 12001 | 0.6955 | 1.438 |
| q3.5-9b | 88.44 | 2603 | 11478 | 1.6740 | 0.597 |
| qwen3-0.6b-q8 | 45.92 | 2288 | 12001 | 0.1718 | 5.820 |
| qwen35-0.8b-q4km | 44.59 | 2176 | 12001 | 0.1636 | 6.112 |
| qwen35-4.2b-iq4xs | 81.50 | 2573 | 11732 | 0.8597 | 1.163 |
| qwen35-4.2b-q3km | 81.53 | 2627 | 11751 | 0.9505 | 1.052 |
| qwen35-4.2b-q4_0 | 53.50 | 2362 | 12001 | 0.5536 | 1.806 |
| qwen35-opus-4b | 86.27 | 2633 | 11680 | 1.0185 | 0.982 |
| qwen9b-q4_0 | 90.69 | 2673 | 11204 | 1.6202 | 0.617 |
| qwen9b-q4km | 96.19 | 2654 | 11272 | 1.8488 | 0.541 |
| qwen9b-q5km | 95.21 | 2604 | 11260 | 2.0307 | 0.492 |
| qwythos9b | 89.52 | 2635 | 11433 | 1.7174 | 0.582 |
| spark-x2.5-4b | - | - | - | - | - |

## 表 D prefill parity

| 模型 | 5 tok | 130 tok | 520 tok | default match | 预期判定 |
|---|---|---|---|---|---|
| bonsai-27b-q1_0 | OK | OK | OK | - | PASS |
| dsr1-8b-q4km | OK | OK | OK | - | PASS |
| gemma4-12b-q4_0 | - | - | - | - | - |
| gemma4-26b-a4b | - | - | - | - | - |
| glm4.6v-q4km | OK | OK | OK | - | FAIL(policy_mismatch) |
| minicpm5-1b | OK | OK | OK | - | PASS |
| nemotron-4b-q4_0 | OK | OK | OK | - | PASS |
| nemotron-nano-4b-q4km | OK | OK | OK | - | PASS |
| q3.5-9b | OK | OK | OK | - | PASS |
| qwen3-0.6b-q8 | OK | OK | OK | - | PASS |
| qwen35-0.8b-q4km | OK | OK | OK | - | PASS |
| qwen35-4.2b-iq4xs | OK | OK | OK | - | PASS |
| qwen35-4.2b-q3km | OK | OK | OK | - | PASS |
| qwen35-4.2b-q4_0 | OK | OK | OK | - | PASS |
| qwen35-opus-4b | OK | OK | OK | - | PASS |
| qwen9b-q4_0 | OK | OK | OK | - | PASS |
| qwen9b-q4km | OK | OK | OK | - | PASS |
| qwen9b-q5km | OK | OK | OK | - | PASS |
| qwythos9b | OK | OK | OK | - | PASS |
| spark-x2.5-4b | - | - | - | - | - |

## 表 E 失败与异常

| 模型 | 步骤 | 状态 | 签名 | 错误码 |
|---|---|---|---|---|
| glm4.6v-q4km | test_prefill | fail | None | - |
| qwen35-0.8b-q4km | test_prefill | fail | None | - |

## 口径

- 速率：128 token，1 warmup + 3 测量，取三轮均值；ctx 16384（放不下时用实测可行档）。

- TTFT：ceiling harness，目标 128/2048/8192 token，实际 token 从 JSON 读回，prefill_batch=512。

- 能耗：200 ms 轮询，仅统计 power>20 W 的样本，J/token 按 decode 窗口折算。

- parity：test_prefill 内建三档，default 列的 `match` 是引擎默认批与显式 512 的对照。

