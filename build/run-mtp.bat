@echo off
setlocal
set "PATH=E:\Deepseek\tir-b\runtime\cuda-13.5\bin\x64;E:\Deepseek\tir-b\build\tir-api\bin;%PATH%"
set "TIR_TEST_MODEL=E:\model\bionic\Qwen\Qwen3.8-9B-Distill-GGUF\Qwen3.8-9B-Q5_K_M.gguf"
"E:\Deepseek\tir-b\build\tir-api\bin\tir-test-mtp.exe"
echo EXIT=%ERRORLEVEL%
