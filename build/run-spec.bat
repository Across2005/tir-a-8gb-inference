@echo off
setlocal
set "PATH=E:\Deepseek\tir-b\runtime\cuda-13.5\bin\x64;E:\Deepseek\tir-b\build\tir-api\bin;%PATH%"
set "TIR_TEST_MODEL=E:\model\blobs\sha256-de8cf2454c46ec34e6b991dc11f5dd42d543926272d8a59d36ceb5a2eaf7962a"
set "TIR_SPEC_TYPE=ngram"
set "TIR_SPEC_DEBUG=1"
"E:\Deepseek\tir-b\build\tir-api\bin\tir-test-spec.exe"
echo EXIT=%ERRORLEVEL%
