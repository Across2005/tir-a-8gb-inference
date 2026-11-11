@echo off
setlocal
set "BIN=E:\Deepseek\tir-b\build\tir-cuda2\bin"
set "MODEL=E:\model\bionic\lmstudio-community\DeepSeek-R1-0528-Qwen3-8B-GGUF\DeepSeek-R1-0528-Qwen3-8B-Q4_K_M.gguf"
set "OUT=E:\Deepseek\tir-b\test\spike\b0"
if not exist "%OUT%" mkdir "%OUT%"
set "PATH=E:\Deepseek\tir-b\runtime\cuda-13.5\bin;E:\Deepseek\tir-b\runtime\cuda-13.5\bin\x64;E:\Deepseek\tir-b\runtime\cuda-13.5\nvvm\bin\x64;%PATH%"

echo === B0a baseline ===
set TIR_SPIKE=
set TIR_SPIKE_TENSOR=
"%BIN%\tierspike.exe" -m "%MODEL%" -c 4096 -n 32 > "%OUT%\b0a-stdout.txt" 2> "%OUT%\b0a.json"

echo === B0e h2d bench ===
"%BIN%\tierspike.exe" --bench-h2d 64,256,512 > "%OUT%\b0e-stdout.txt" 2> "%OUT%\b0e.json"

echo === B0b callback count ===
set TIR_SPIKE=callback-count
"%BIN%\tierspike.exe" -m "%MODEL%" -c 4096 -n 32 > "%OUT%\b0b-stdout.txt" 2> "%OUT%\b0b.json"

echo === B0c zero-copy ===
set TIR_SPIKE=zero-copy
set TIR_SPIKE_TENSOR=blk.20.ffn_down.weight
"%BIN%\tierspike.exe" -m "%MODEL%" -c 4096 -n 32 > "%OUT%\b0c-stdout.txt" 2> "%OUT%\b0c.json"

echo === B0d h2d staging ===
set TIR_SPIKE=h2d
set TIR_SPIKE_TENSOR=output.weight
"%BIN%\tierspike.exe" -m "%MODEL%" -c 4096 -n 32 > "%OUT%\b0d-stdout.txt" 2> "%OUT%\b0d.json"

echo B0_DONE
