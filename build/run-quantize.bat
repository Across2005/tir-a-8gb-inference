@echo off
setlocal
set "PATH=E:\Deepseek\tir-b\runtime\cuda-13.5\bin\x64;E:\Deepseek\tir-b\build\tir-api\bin;%PATH%"
"E:\Deepseek\tir-b\build\tir-api\bin\llama-quantize.exe" %*
echo EXIT=%ERRORLEVEL%
