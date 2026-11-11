@echo off
setlocal
set "PATH=E:\Deepseek\tir-b\runtime\cuda-13.5\bin\x64;E:\Deepseek\tir-b\build\tir-api\bin;%PATH%"
set "TIR_BENCH_PROMPT=The capital of France is"
set "TIR_MTP_N_MAX=2"
"E:\Deepseek\tir-b\build\tir-api\bin\tir-bench.exe" E:\Deepseek\artifacts\qwen9b-Q4_0.gguf 16384 1 128
echo EXIT=%ERRORLEVEL%
