@echo off
setlocal
set "PATH=E:\Deepseek\tir-b\runtime\cuda-13.5\bin\x64;E:\Deepseek\tir-b\build\tir-api\bin;%PATH%"
set "TIR_TEST_MODEL=E:\model\blobs\sha256-b1c3bf2995e96cb792a0031e4e1497a500e9244c68ba17c24a7e6edf1fc59019"
"E:\Deepseek\tir-b\build\tir-api\bin\tir-test-profile.exe"
echo EXIT=%ERRORLEVEL%
