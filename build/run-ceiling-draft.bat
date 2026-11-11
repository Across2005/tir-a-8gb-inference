@echo off
setlocal
set "TIR_DRAFT_MODEL=E:\Deepseek\artifacts\Qwen3.5-0.8B-Q4_K_M.gguf"
set "TIR_SPEC_DEBUG=1"
call "%~dp0run-ceiling.bat" %*
