@echo off
setlocal
call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
set "CUDA_PATH=E:\Deepseek\tir-b\runtime\cuda-13.5"
set "CUDACXX=%CUDA_PATH%\bin\nvcc.exe"
set "CUDAToolkit_ROOT=%CUDA_PATH%"
set "PATH=%CUDA_PATH%\bin;%CUDA_PATH%\bin\x64;%CUDA_PATH%\nvvm\bin\x64;%PATH%"
set "CMAKE=C:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"

"%CMAKE%" -S "E:\Deepseek\tir-b\src\llama.cpp-fork" -B "E:\Deepseek\tir-b\build\tir-cuda" -G Ninja ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DGGML_CUDA=ON ^
  -DCMAKE_CUDA_ARCHITECTURES=120 ^
  -DCMAKE_CUDA_COMPILER="%CUDACXX%" ^
  -DCUDAToolkit_ROOT="%CUDA_PATH%" ^
  -DLLAMA_BUILD_TESTS=OFF ^
  -DLLAMA_BUILD_SERVER=OFF ^
  -DLLAMA_CURL=OFF ^
  -DGGML_OPENMP=OFF ^
  -DGGML_NATIVE=OFF
if errorlevel 1 (
  echo CONFIGURE_FAILED=%ERRORLEVEL%
  exit /b 1
)

"%CMAKE%" --build "E:\Deepseek\tir-b\build\tir-cuda" --target llama-cli llama-bench tierspike -- -j 12
echo BUILD_EXIT=%ERRORLEVEL%
