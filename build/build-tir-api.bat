@echo off
rem TIR-A P0: configure and build the C ABI shared library plus its test targets.
setlocal
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "SRC=%ROOT%\src\llama.cpp-fork"
set "BUILD=%ROOT%\build\tir-api"
set "CUDA_PATH=E:\Deepseek\tir-b\runtime\cuda-13.5"
set "CUDACXX=%CUDA_PATH%\bin\nvcc.exe"
set "CUDAToolkit_ROOT=%CUDA_PATH%"
set "CMAKE=C:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"

call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 (
  echo VCVARS_FAILED
  exit /b 1
)

set "PATH=%CUDA_PATH%\bin;%CUDA_PATH%\bin\x64;%CUDA_PATH%\nvvm\bin\x64;%PATH%"
if "%TIR_JOBS%"=="" set "TIR_JOBS=8"

"%CMAKE%" -S "%SRC%" -B "%BUILD%" -G Ninja ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DCMAKE_C_COMPILER=cl ^
  -DCMAKE_CXX_COMPILER=cl ^
  -DCMAKE_CUDA_HOST_COMPILER=cl ^
  -DBUILD_SHARED_LIBS=ON ^
  -DTIR_BUILD_API=ON ^
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

"%CMAKE%" --build "%BUILD%" --target tir tir-test-abi tir-test-abi-load tir-test-generate tir-test-profile tir-test-spec tir-test-draft-compat tir-test-mtp tir-test-chat tir-test-prefill tir-bench tir-bench-ceiling llama-quantize -- -j %TIR_JOBS%
if errorlevel 1 (
  echo BUILD_FAILED=%ERRORLEVEL%
  exit /b 1
)
echo BUILD_OK
