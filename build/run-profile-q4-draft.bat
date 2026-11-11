@echo off
setlocal
set "PATH=E:\Deepseek\tir-b\runtime\cuda-13.5\bin\x64;E:\Deepseek\tir-b\build\tir-api\bin;%PATH%"
set "TIR_TEST_MODEL=E:\Deepseek\artifacts\qwen35-4.2b-Q4_0.gguf"
set "TIR_DRAFT_MODEL=E:\Deepseek\artifacts\Qwen3.5-0.8B-Q4_K_M.gguf"
"E:\Deepseek\tir-b\build\tir-api\bin\tir-test-profile.exe"
echo EXIT=%ERRORLEVEL%
