@echo off
setlocal
set "PATH=E:\Deepseek\tir-b\runtime\cuda-13.5\bin\x64;E:\Deepseek\tir-b\build\tir-api\bin;%PATH%"
set "TIR_TEST_MODEL=E:\Deepseek\artifacts\qwen9b-Q4_0.gguf"
set "TIR_MTP_N_MAX=2"
"E:\Deepseek\tir-b\build\tir-api\bin\tir-test-mtp.exe"
echo EXIT=%ERRORLEVEL%
