# 全量矩阵摘要（full1）

行 201，模型 20；其中 19 个测到 plain 速率。

## 速率（128 token，plain）

| 模型 | tok/s |
|---|---:|
| spark-x2.5-4b | 4.2 |
| gemma4-12b-q4_0 | 10.1 |
| glm4.6v-q4km | 45.0 |
| bonsai-27b-q1_0 | 46.1 |
| qwen9b-q5km | 47.2 |
| qwythos9b | 52.7 |
| q3.5-9b | 52.9 |
| qwen9b-q4km | 53.0 |
| qwen9b-q4_0 | 56.8 |
| dsr1-8b-q4km | 59.0 |
| qwen35-opus-4b | 84.9 |
| qwen35-4.2b-q3km | 86.2 |
| qwen35-4.2b-q4_0 | 96.7 |
| qwen35-4.2b-iq4xs | 97.0 |
| nemotron-nano-4b-q4km | 101.8 |
| nemotron-4b-q4_0 | 116.1 |
| qwen3-0.6b-q8 | 243.6 |
| qwen35-0.8b-q4km | 274.6 |
| minicpm5-1b | 313.9 |

## MTP（仅 nextn 模型）

| 模型 | tok/s | acceptance |
|---|---:|---:|
| qwen9b-q4_0 | 77.3 | 0.767 |
| qwen9b-q4km | 77.2 | 0.855 |
| qwen9b-q5km | 75.8 | 1.0 |

## 边缘与未运行

- 显存边缘（跳过长 prompt 与 test_prefill）：gemma4-12b-q4_0
- 按用户决定停止：spark-x2.5-4b, gemma4-26b-a4b
- spark-x2.5-4B：probe 4.86、plain 4.2 tok/s、TTFT(S) 4501.268 ms，随后停止
- gemma4-26B-A4B：13.43 GiB > 8.0 GiB 总显存，未运行

## 口径

- plain/MTP：ctx 16384（放不下时按实测档），q4 KV，1 warmup + 3 测量取均值。
- TTFT：ceiling harness，目标 128/2048/8192 token，实际 token 从 JSON 读回。
- 边缘判定：探针峰值 >7300 MiB 时跳过长 prompt 档。
- 数字由 tools/matrix/emit_report.py 与 master.csv 生成。
