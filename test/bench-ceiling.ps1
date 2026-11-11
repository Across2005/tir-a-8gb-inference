param(
    [Parameter(Mandatory = $true)][string]$Model,
    [int]$Ctx = 8192,
    [int]$PromptTokens = 2048,
    [int]$NPredict = 128,
    [int]$KvQ4 = 1,
    [int]$Runs = 3,
    [string]$Out = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$env:PATH = "E:\Deepseek\tir-b\runtime\cuda-13.5\bin\x64;$env:PATH"
$exe = Join-Path $root "build\tir-api\bin\tir-bench-ceiling.exe"
if (-not (Test-Path $exe)) {
    throw "missing $exe; run build\build-tir-api.bat first"
}
if ([string]::IsNullOrWhiteSpace($Out)) {
    $Out = Join-Path $PSScriptRoot "ceiling\results.jsonl"
}

function Get-GpuTelemetry {
    $line = & nvidia-smi --query-gpu=clocks.sm,clocks.mem,power.draw,temperature.gpu,memory.used,memory.total --format=csv,noheader,nounits 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($line)) {
        return "unavailable"
    }
    return ($line | Select-Object -First 1).Trim()
}

$before = Get-GpuTelemetry
$oldPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$lines = & $exe $Model $Ctx $PromptTokens $NPredict $KvQ4 $Runs 2>&1
$code = $LASTEXITCODE
$ErrorActionPreference = $oldPreference
if ($code -ne 0) {
    throw "tir-bench-ceiling failed ($code): $lines"
}
$after = Get-GpuTelemetry

$jsonLine = $lines | Where-Object { "$_" -match '^\s*\{' } | Select-Object -Last 1
if (-not $jsonLine) {
    throw "no JSON line from tir-bench-ceiling: $lines"
}

$record = $jsonLine | ConvertFrom-Json
$record | Add-Member -NotePropertyName timestamp -NotePropertyValue (Get-Date).ToString("o")
$record | Add-Member -NotePropertyName gpu_before -NotePropertyValue $before
$record | Add-Member -NotePropertyName gpu_after -NotePropertyValue $after

$dir = Split-Path -Parent $Out
if (-not (Test-Path $dir)) {
    New-Item -ItemType Directory -Path $dir | Out-Null
}
($record | ConvertTo-Json -Compress) | Add-Content -Encoding UTF8 -Path $Out
Write-Output ($record | ConvertTo-Json -Compress)
