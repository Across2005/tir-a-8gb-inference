@echo off
setlocal
call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
set "CUDA_PATH=E:\Deepseek\tir-b\runtime\cuda-13.5"
set "CUDACXX=%CUDA_PATH%\bin\nvcc.exe"
set "CUDAToolkit_ROOT=%CUDA_PATH%"
set "PATH=%CUDA_PATH%\bin;%CUDA_PATH%\bin\x64;%CUDA_PATH%\nvvm\bin\x64;%PATH%"
set "CMAKE=C:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
"%CMAKE%" --build "E:\Deepseek\tir-b\build\tir-cuda2" --target llama-app llama-bench tierspike -- -j 8 > "E:\Deepseek\tir-b\build\build-only.log" 2>&1
echo BUILD_EXIT=%ERRORLEVEL% >> "E:\Deepseek\tir-b\build\build-only.log"
