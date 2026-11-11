@echo off
rem TIR-A P0 gate: run the C ABI tests and the 16k q4 + MTP benchmark against
rem build\tir-api\bin\tir.dll. A slow bench does not fail the gate, the controller
rem rules on the numbers. A failing test or a missing json does fail it.
setlocal
set "ROOT=E:\Deepseek\tir-b"
set "BIN=%ROOT%\build\tir-api\bin"
set "CUDA_ROOT=E:\Deepseek\tir-b\runtime\cuda-13.5"
set "OUT=%ROOT%\test\tir-api"
set "LOGS=%ROOT%\build\logs"
set "MODEL=E:\model\bionic\Qwen\Qwen3.8-9B-Distill-GGUF\Qwen3.8-9B-Q5_K_M.gguf"
set "GATE_CTX=16384"
set "TARGET_TOK_S=45"

rem tir.dll needs the CUDA runtime and the ggml/llama DLLs from these directories
set "PATH=%CUDA_ROOT%\bin\x64;%CUDA_ROOT%\bin;%BIN%;%PATH%"

rem this fork streams weights from disk by default but its residency hook is CPU-only,
rem so disk streaming plus CUDA offload is unsupported: force the stock mmap load
set "LLAMA_DISK_STREAM_MB=0"

if "%TIR_TEST_MODEL%"=="" set "TIR_TEST_MODEL=%MODEL%"

if not exist "%OUT%" mkdir "%OUT%"
if not exist "%LOGS%" mkdir "%LOGS%"

if not exist "%BIN%\tir.dll" (
  echo P0_GATE_FAILED reason=no_dll path=%BIN%\tir.dll
  echo run build\build-tir-api.bat first
  exit /b 1
)
if not exist "%BIN%\tir-bench.exe" (
  echo P0_GATE_FAILED reason=no_bench path=%BIN%\tir-bench.exe
  echo run build\build-tir-api.bat first
  exit /b 1
)

echo TIR_TEST_MODEL=%TIR_TEST_MODEL%
echo LLAMA_DISK_STREAM_MB=%LLAMA_DISK_STREAM_MB%
echo TIR_BENCH_MODEL=%MODEL%
echo TIR_BENCH_CTX=%GATE_CTX%

call :run tir-test-abi
if errorlevel 1 exit /b 1
call :run tir-test-abi-load
if errorlevel 1 exit /b 1
call :run tir-test-generate
if errorlevel 1 exit /b 1
call :run tir-test-mtp
if errorlevel 1 exit /b 1

rem P0 measurement: 16k ctx, q4 KV, MTP on, 128 tokens, 1 warmup + 3 measured runs
call :bench 1 "%OUT%\p0-gate.json"
if errorlevel 1 exit /b 1

rem same settings with MTP off, for comparison
call :bench 0 "%OUT%\p0-gate-plain.json"
if errorlevel 1 exit /b 1

echo --- p0-gate.json ---
type "%OUT%\p0-gate.json"
echo --- p0-gate-plain.json ---
type "%OUT%\p0-gate-plain.json"

rem parse tok_s_avg by key, so a changed field order in bench.c cannot pick another number
set "TOK_AVG="
for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "(Get-Content -Raw '%OUT%\p0-gate.json' | ConvertFrom-Json).tok_s_avg"`) do set "TOK_AVG=%%A"
if not defined TOK_AVG (
  rem no powershell or unreadable json: fall back to field 8 of the one-line json
  echo WARNING powershell_json_parse_failed, falling back to field 8 of %OUT%\p0-gate.json
  for /f "usebackq tokens=8 delims=,:" %%A in ("%OUT%\p0-gate.json") do set "TOK_AVG=%%A"
)
if not defined TOK_AVG (
  echo P0_GATE_FAILED reason=no_tok_s json=%OUT%\p0-gate.json
  exit /b 1
)
set "TOK_INT=%TOK_AVG%"
for /f "tokens=1 delims=." %%A in ("%TOK_AVG%") do set "TOK_INT=%%A"
rem a non-numeric value would turn the compare below into a string compare that can pass
for /f "delims=0123456789" %%A in ("%TOK_INT%") do (
  echo P0_GATE_FAILED reason=bad_tok_s tok_s_avg=%TOK_AVG% json=%OUT%\p0-gate.json
  exit /b 1
)

if %TOK_INT% GEQ %TARGET_TOK_S% (
  echo P0_GATE_OK tok_s_avg=%TOK_AVG% target=%TARGET_TOK_S%
) else (
  echo P0_GATE_BELOW_TARGET tok_s_avg=%TOK_AVG% target=%TARGET_TOK_S%
)
exit /b 0

:run
echo === %~1 ===
"%BIN%\%~1.exe"
if errorlevel 1 (
  echo P0_GATE_FAILED test=%~1 exit=%ERRORLEVEL%
  exit /b 1
)
rem errorlevel 1 is false for negative codes (0xC0000005 is -1073741819), so a crash would pass
if not errorlevel 0 (
  echo P0_GATE_FAILED test=%~1 exit=%ERRORLEVEL%
  exit /b 1
)
exit /b 0

:bench
rem %1 = mtp 0|1, %2 = json output path
echo === tir-bench ctx=%GATE_CTX% mtp=%~1 ===
"%BIN%\tir-bench.exe" "%MODEL%" %GATE_CTX% %~1 > "%~2" 2>>"%LOGS%\p0-gate-bench.log"
if errorlevel 1 (
  echo P0_GATE_FAILED bench=%~2 exit=%ERRORLEVEL%
  exit /b 1
)
rem errorlevel 1 is false for negative codes, a crashed bench must not be read as a result
if not errorlevel 0 (
  echo P0_GATE_FAILED bench=%~2 exit=%ERRORLEVEL%
  exit /b 1
)
exit /b 0
