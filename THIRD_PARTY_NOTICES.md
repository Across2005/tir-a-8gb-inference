# 第三方组件与许可证 / Third-Party Notices

本仓库再分发的第三方代码按各自许可证提供。清单如下；对应许可证原文保留在所列路径。

## 代码基座

| 组件 | 许可证 | 版权 | 路径 |
|---|---|---|---|
| llama.cpp / ggml | MIT | Copyright (c) 2023-2026 The ggml authors | `src/llama.cpp-fork/LICENSE` |
| diskinfer-windows | Apache-2.0 | 上游未填写具体版权人；见上游仓库 | `LICENSE-APACHE-2.0`、`NOTICE`；派生文件见 NOTICE |

## vendor 依赖（随 fork 保留上游原样）

| 组件 | 许可证 | 版权 / 说明 | 路径 |
|---|---|---|---|
| cpp-httplib | MIT | Copyright (c) 2017 yhirose | `src/llama.cpp-fork/vendor/cpp-httplib/LICENSE` |
| nlohmann/json 3.12.0 | MIT | Copyright (c) 2013-2025 Niels Lohmann | `src/llama.cpp-fork/vendor/nlohmann/json.hpp`（SPDX 头） |
| stb_image 2.30 | Public domain / MIT | 双许可，见文件头 | `src/llama.cpp-fork/vendor/stb/stb_image.h` |
| miniaudio 0.11.25 | Public domain / MIT-0 | 双许可，见文件头 | `src/llama.cpp-fork/vendor/miniaudio/miniaudio.h` |
| sheredom/subprocess.h | Public domain（Unlicense 式声明） | 见文件头 | `src/llama.cpp-fork/vendor/sheredom/subprocess.h` |
| xxHash | BSD-2-Clause | Copyright (c) 2012-2021 Yann Collet | `src/llama.cpp-fork/vendor/hash/xxhash/LICENSE` |
| sha256 | Public domain | 2010-06-11 Igor Pavlov | `src/llama.cpp-fork/vendor/hash/sha256/LICENSE` |
| rotate-bits | MIT | Copyright (c) 2021 William Casarin | `src/llama.cpp-fork/vendor/hash/rotate-bits/LICENSE.md` |
| json.hpp（单文件版） | MIT | 见许可证文件 | `src/llama.cpp-fork/licenses/LICENSE-jsonhpp` |

## 工具与脚本依赖

| 组件 | 许可证 | 路径 |
|---|---|---|
| gguf-py | MIT | `src/llama.cpp-fork/gguf-py/LICENSE` |
| big-integer（Web UI） | MIT | `src/llama.cpp-fork/tools/ui/src/lib/vendors/big-integer/LICENSE` |
| nerdamer-prime（Web UI） | MIT | `src/llama.cpp-fork/tools/ui/src/lib/vendors/nerdamer-prime/LICENSE` |

## 构建期依赖（不再分发）

- CUDA Toolkit 13.5：构建与运行依赖，按 NVIDIA 许可使用；本仓库不包含其二进制。
- 本地模型权重：不随仓库分发。

## 仅作策略参考、未包含源码的项目

Strata、KTransformers、Swiftlet、FlexLLMGen、AirLLM、PowerInfer 仅用于设计调研，本仓库不包含其源码副本；归属说明见 README「许可证与血统」。
