@echo off
setlocal
set "PATH=E:\Deepseek\tir-b\runtime\cuda-13.5\bin\x64;E:\Deepseek\tir-b\build\tir-api\bin;%PATH%"
set "TIR_BENCH_PROMPT=The capital of France is"
"E:\Deepseek\tir-b\build\tir-api\bin\tir-bench.exe" %*
echo EXIT=%ERRORLEVEL%
