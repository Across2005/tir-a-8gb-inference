param(
    [Parameter(Mandatory = $true)][string]$Model,
    [int]$Ctx = 4096,
    [int]$PromptTokens = 128,
    [int]$NPredict = 512,
    [int]$KvQ4 = 1,
    [int]$Runs = 1,
    [string]$Label = "default",
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
    $Out = Join-Path $PSScriptRoot "power\results.jsonl"
}
$dir = Split-Path -Parent $Out
if (-not (Test-Path $dir)) {
    New-Item -ItemType Directory -Path $dir | Out-Null
}

$stdout = Join-Path $env:TEMP ("tir-power-out-" + [guid]::NewGuid().ToString("N") + ".jsonl")
$stderr = Join-Path $env:TEMP ("tir-power-err-" + [guid]::NewGuid().ToString("N") + ".log")
$args = @($Model, $Ctx, $PromptTokens, $NPredict, $KvQ4, $Runs)
$started = Get-Date
$p = Start-Process -FilePath $exe -ArgumentList $args -NoNewWindow -PassThru `
    -WorkingDirectory $root -RedirectStandardOutput $stdout -RedirectStandardError $stderr

$samples = New-Object System.Collections.Generic.List[object]
while (-not $p.HasExited) {
    $line = & nvidia-smi --query-gpu=clocks.sm,clocks.mem,power.draw,temperature.gpu,memory.used --format=csv,noheader,nounits 2>$null
    if (-not [string]::IsNullOrWhiteSpace($line)) {
        $v = ($line | Select-Object -First 1) -split ','
        if ($v.Count -ge 5) {
            $sm = 0.0; $mem = 0.0; $power = 0.0; $temp = 0.0; $vram = 0.0
            [void][double]::TryParse($v[0].Trim(), [ref]$sm)
            [void][double]::TryParse($v[1].Trim(), [ref]$mem)
            [void][double]::TryParse($v[2].Trim(), [ref]$power)
            [void][double]::TryParse($v[3].Trim(), [ref]$temp)
            [void][double]::TryParse($v[4].Trim(), [ref]$vram)
            if ($power -gt 20.0) {
                $samples.Add([pscustomobject]@{ sm = $sm; mem = $mem; power = $power; temp = $temp; vram = $vram })
            }
        }
    }
    Start-Sleep -Milliseconds 200
    $p.Refresh()
}
$p.WaitForExit()
$elapsed = ((Get-Date) - $started).TotalSeconds
if ($null -ne $p.ExitCode -and $p.ExitCode -ne 0) {
    throw "tir-bench-ceiling failed ($($p.ExitCode)); see $stderr"
}

$jsonLine = Get-Content $stdout | Where-Object { "$_" -match '^\s*\{' } | Select-Object -Last 1
if (-not $jsonLine) {
    throw "no JSON line; see $stdout"
}
$record = $jsonLine | ConvertFrom-Json

$avgPower = ($samples | Measure-Object -Property power -Average).Average
$avgSm = ($samples | Measure-Object -Property sm -Average).Average
$avgMem = ($samples | Measure-Object -Property mem -Average).Average
$minMem = ($samples | Measure-Object -Property mem -Minimum).Minimum
$maxTemp = ($samples | Measure-Object -Property temp -Maximum).Maximum
$decodeS = [double]$record.decode_ms / 1000.0
$gen = [double]$record.gen_tokens
$jProcess = if ($gen -gt 0) { $avgPower * $elapsed / $gen } else { 0.0 }
$jDecode = if ($gen -gt 0) { $avgPower * $decodeS / $gen } else { 0.0 }
$tokensPerJ = if ($jDecode -gt 0) { 1.0 / $jDecode } else { 0.0 }

$outRecord = [ordered]@{
    schema = "tir.power/v1"
    label = $Label
    model = $Model
    n_ctx = $Ctx
    prompt_tokens = $record.prompt_tokens
    gen_tokens = $record.gen_tokens
    tok_s = $record.tok_s_p50
    avg_power_w = [math]::Round($avgPower, 2)
    avg_sm_mhz = [math]::Round($avgSm, 0)
    avg_mem_mhz = [math]::Round($avgMem, 0)
    min_mem_mhz = [math]::Round($minMem, 0)
    max_temp_c = [math]::Round($maxTemp, 1)
    process_s = [math]::Round($elapsed, 3)
    decode_s = [math]::Round($decodeS, 3)
    j_per_token_process = [math]::Round($jProcess, 4)
    j_per_token_decode = [math]::Round($jDecode, 4)
    tokens_per_j_decode = [math]::Round($tokensPerJ, 4)
    samples = $samples.Count
    timestamp = (Get-Date).ToString("o")
}
($outRecord | ConvertTo-Json -Compress) | Add-Content -Encoding UTF8 -Path $Out
($outRecord | ConvertTo-Json -Compress)
