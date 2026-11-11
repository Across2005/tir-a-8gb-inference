# TIR-B build helper for the CUDA 13.5 / sm_120 spike tree.
# Configure + build the requested targets with the VS18 toolchain.

param(
    [string] $Source    = (Join-Path $PSScriptRoot '..\src\llama.cpp-fork'),
    [string] $BuildDir  = (Join-Path $PSScriptRoot 'tir-cuda'),
    [string[]] $Targets = @('llama-cli', 'llama-bench', 'tierspike'),
    [switch] $Reconfigure,
    [switch] $AllowUnsupportedCompiler
)

$ErrorActionPreference = 'Stop'

$vcvars = 'C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat'
if (-not (Test-Path $vcvars)) {
    throw "vcvars64.bat not found: $vcvars"
}

$Source   = (Resolve-Path $Source).Path
$BuildDir = [System.IO.Path]::GetFullPath($BuildDir)

$cudaFlags = ''
if ($AllowUnsupportedCompiler) {
    $cudaFlags = ' -DCMAKE_CUDA_FLAGS="-allow-unsupported-compiler"'
}

$configCmd = 'cmake -S "' + $Source + '" -B "' + $BuildDir + '" -G Ninja ' +
             '-DCMAKE_BUILD_TYPE=Release ' +
             '-DGGML_CUDA=ON ' +
             '-DCMAKE_CUDA_ARCHITECTURES=120 ' +
             '-DGGML_CUDA_FORCE_MMQ=OFF ' +
             '-DLLAMA_BUILD_TESTS=OFF ' +
             '-DLLAMA_BUILD_SERVER=ON ' +
             '-DLLAMA_CURL=OFF ' +
             '-DGGML_OPENMP=OFF ' +
             '-DGGML_NATIVE=OFF ' +
             '-DBUILD_SHARED_LIBS=OFF' + $cudaFlags

$buildCmd = 'cmake --build "' + $BuildDir + '" --target ' + ($Targets -join ' ')

$logDir = Join-Path $BuildDir 'logs'
New-Item -ItemType Directory -Force $logDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

function Invoke-Cmd {
    param([string] $Cmd, [string] $LogName)
    $log = Join-Path $logDir $LogName
    Write-Host ">> $Cmd"
    cmd /c ('call "' + $vcvars + '" >nul 2>&1 && ' + $Cmd + ' 2>&1') | Tee-Object -FilePath $log
    if ($LASTEXITCODE -ne 0) {
        throw "command failed (exit $LASTEXITCODE): $Cmd (log: $log)"
    }
}

if ($Reconfigure -or -not (Test-Path (Join-Path $BuildDir 'CMakeCache.txt'))) {
    Invoke-Cmd $configCmd ("configure-$stamp.log")
}

Invoke-Cmd $buildCmd ("build-$stamp.log")

Write-Host "built targets: $($Targets -join ', ') -> $(Join-Path $BuildDir 'bin')"
