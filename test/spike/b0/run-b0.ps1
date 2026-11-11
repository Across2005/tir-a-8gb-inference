# B0 spike driver: runs B0a-B0e, keeps every raw log, writes results.json.
# Writes only under test/spike/b0/results (and the 1 GiB NVMe probe file, deleted after use).

param(
    [string] $Model   = 'E:\model\bionic\Qwen\Qwen3.8-9B-Distill-GGUF\Qwen3.8-9B-Q5_K_M.gguf',
    [string] $OutDir  = (Join-Path $PSScriptRoot 'results'),
    [int]    $Ctx     = 4096,
    [int]    $NGen    = 32,
    [int]    $NCallbacks = 8,
    [switch] $SkipB0d256
)

$ErrorActionPreference = 'Continue'

$bin  = 'E:\Deepseek\tir-b\build\tir-cuda\bin'
$cuda = 'E:\Deepseek\tir-b\cuda-13.5'
$env:PATH = "$cuda\bin;$cuda\bin\x64;$bin;" + $env:PATH
# the fork streams weights from disk by default; B0 must exercise the normal CUDA path
$env:LLAMA_DISK_STREAM_MB = '0'

New-Item -ItemType Directory -Force $OutDir | Out-Null

$results = [ordered]@{
    date = (Get-Date -Format o)
    model = $Model
    ctx = $Ctx
    steps = [ordered]@{}
}

function Save-Text([string]$path, [string[]]$lines) {
    $lines | Set-Content -Path $path -Encoding UTF8
}

function Get-FreeVram {
    $v = & nvidia-smi --query-gpu=memory.total,memory.used,memory.free --format=csv,noheader
    return $v.Trim()
}

function Run-Tierspike {
    param([string]$Name, [hashtable]$Env, [int]$N, [string]$Extra = '')
    $json = Join-Path $OutDir "$Name.jsonl"
    $out  = Join-Path $OutDir "$Name.stdout.txt"
    $err  = Join-Path $OutDir "$Name.stderr.txt"
    foreach ($k in @('TIR_SPIKE', 'TIR_SPIKE_TENSOR', 'TIR_SPIKE_MB')) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
    foreach ($k in $Env.Keys) { Set-Item -Path "Env:$k" -Value $Env[$k] }
    $args = @('-m', $Model, '-c', "$Ctx", '-n', "$N")
    if ($Extra) { $args += $Extra.Split(' ', [StringSplitOptions]::RemoveEmptyEntries) }
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    & "$bin\tierspike.exe" @args 1> $out 2> $json
    $sw.Stop()
    $raw = Get-Content $json -ErrorAction SilentlyContinue
    $line = $raw | Where-Object { $_.TrimStart().StartsWith('{') } | Select-Object -Last 1
    $obj = $null
    if ($line) { try { $obj = $line | ConvertFrom-Json } catch {} }
    $step = [ordered]@{
        exit = $LASTEXITCODE
        wall_s = [math]::Round($sw.Elapsed.TotalSeconds, 3)
        json = $obj
        log_jsonl = $json
    }
    $results.steps[$Name] = $step
    return $step
}

# ---------------- B0a: baseline (no callback) + llama-bench ----------------
$results.steps.free_vram_before = (Get-FreeVram)
Save-Text (Join-Path $OutDir 'nvidia-before.txt') @(& nvidia-smi 2>&1)
Save-Text (Join-Path $OutDir 'llama-cli-version.txt') @(& "$bin\llama-cli.exe" --version 2>&1)

Run-Tierspike -Name 'b0a-baseline' -Env @{} -N $NGen | Out-Null
$bench = & "$bin\llama-bench.exe" -m $Model -ngl 99 -p 128 -n 32 -r 3 2>&1
Save-Text (Join-Path $OutDir 'b0a-llama-bench.txt') @($bench)
$results.steps['b0a-llama-bench'] = [ordered]@{ exit = $LASTEXITCODE; lines = @($bench | Select-Object -Last 6) }

# ---------------- B0b: callback count ----------------
Run-Tierspike -Name 'b0b-callback-count' -Env @{ TIR_SPIKE = 'callback-count' } -N $NCallbacks | Out-Null
$baseMs = 0.0
if ($results.steps['b0b-callback-count'].json) {
    $baseMs = [double]$results.steps['b0b-callback-count'].json.ms_per_token
}

# ---------------- B0c: zero copy, 32 MB class tensor ----------------
Run-Tierspike -Name 'b0c-zero-copy-32' -Env @{ TIR_SPIKE = 'zero-copy'; TIR_SPIKE_TENSOR = 'blk.20.ffn_down.weight'; TIR_SPIKE_MB = '32'; TIR_SPIKE_BASELINE_MS = "$baseMs" } -N $NGen | Out-Null

# ---------------- B0d: H2D staging, 32 MB and 256 MB class tensors ----------------
Run-Tierspike -Name 'b0d-h2d-32' -Env @{ TIR_SPIKE = 'h2d'; TIR_SPIKE_TENSOR = 'blk.20.ffn_down.weight'; TIR_SPIKE_MB = '32'; TIR_SPIKE_BASELINE_MS = "$baseMs" } -N $NGen | Out-Null
if (-not $SkipB0d256) {
    Run-Tierspike -Name 'b0d-h2d-256' -Env @{ TIR_SPIKE = 'h2d'; TIR_SPIKE_TENSOR = 'output.weight'; TIR_SPIKE_MB = '256'; TIR_SPIKE_BASELINE_MS = "$baseMs" } -N $NGen | Out-Null
}

# ---------------- B0e: H2D bandwidth + NVMe sequential read ----------------
$benchH2d = & "$bin\tierspike.exe" --bench-h2d 64,256,512 2>&1
Save-Text (Join-Path $OutDir 'b0e-h2d.jsonl') @($benchH2d)
$results.steps['b0e-h2d'] = [ordered]@{ exit = $LASTEXITCODE; json = @($benchH2d | Where-Object { $_.TrimStart().StartsWith('{') } | ForEach-Object { $_ | ConvertFrom-Json }) }

$probe = Join-Path $OutDir 'nvme-probe.bin'
$chunk = 1MB
$fs = [System.IO.File]::Create($probe)
$buf = New-Object byte[] (4MB)
[System.Random]::new(42).NextBytes($buf)
for ($i = 0; $i -lt 256; $i++) { $fs.Write($buf, 0, $buf.Length) }
$fs.Close()
$fs = [System.IO.File]::OpenRead($probe)
$buf = New-Object byte[] (4MB)
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$total = 0L
while (($n = $fs.Read($buf, 0, $buf.Length)) -gt 0) { $total += $n }
$sw.Stop()
$fs.Close()
$nvmeGbps = [math]::Round(($total / 1GB) / $sw.Elapsed.TotalSeconds, 2)
Remove-Item $probe -Force
$results.steps['b0e-nvme'] = [ordered]@{ bytes = $total; s = [math]::Round($sw.Elapsed.TotalSeconds, 3); gbps = $nvmeGbps }

$results.steps.free_vram_after = (Get-FreeVram)
Save-Text (Join-Path $OutDir 'nvidia-after.txt') @(& nvidia-smi 2>&1)

($results | ConvertTo-Json -Depth 12) | Set-Content -Path (Join-Path $OutDir 'results.json') -Encoding UTF8
Write-Host "wrote $(Join-Path $OutDir 'results.json')"
