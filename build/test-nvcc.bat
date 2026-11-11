@echo off
call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
set "CUDA_PATH=E:\Deepseek\tir-b\runtime\cuda-13.5"
set "PATH=%CUDA_PATH%\bin;%CUDA_PATH%\bin\x64;%CUDA_PATH%\nvvm\bin\x64;%PATH%"
"%CUDA_PATH%\bin\nvcc.exe" -arch=sm_120 -c "E:\Deepseek\tir-b\test-nvcc.cu" -o "E:\Deepseek\tir-b\test-nvcc.obj"
echo NVCC_EXIT=%ERRORLEVEL%
