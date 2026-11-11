param(
  [switch]$Mtp,
  [int]$C = 2048,
  [int]$N = 256,
  [string]$Kv = 'q8_0',
  [int]$Port = 18100,
  [switch]$Dmon
)
$ErrorActionPreference = 'Continue'
$dir = 'E:\Deepseek\tir-b\runtime\llama-b12202'
$model = 'E:\model\bionic\Qwen\Qwen3.8-9B-Distill-GGUF\Qwen3.8-9B-Q5_K_M.gguf'
$tag = "c${C}-n${N}-kv${Kv}-mtp$([int]$Mtp)"
$outLog = Join-Path $dir "bench-$tag.out.log"
$errLog = Join-Path $dir "bench-$tag.err.log"
Remove-Item $outLog, $errLog -ErrorAction SilentlyContinue

$args = @(
  '-m', $model, '-c', "$C", '-ngl', '99', '-fa', 'on',
  '-ctk', $Kv, '-ctv', $Kv,
  '--host', '127.0.0.1', '--port', "$Port",
  '--metrics', '--jinja', '--load-mode', 'none'
)
if ($Mtp) { $args += @('--spec-type', 'draft-mtp') }
$p = Start-Process -FilePath (Join-Path $dir 'llama-server.exe') -ArgumentList $args -WorkingDirectory $dir -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru -WindowStyle Hidden
$dmon = $null
if ($Dmon) {
  $dmonLog = Join-Path $dir "bench-$tag.dmon.log"
  $dmon = Start-Process -FilePath 'C:\Windows\System32\nvidia-smi.exe' -ArgumentList @('dmon','-s','pucvmet','-d','1','-c','90') -RedirectStandardOutput $dmonLog -PassThru -WindowStyle Hidden
}
Write-Host "PID=$($p.Id) TAG=$tag"

$ready = $false
for ($i = 0; $i -lt 150; $i++) {
  if ($p.HasExited) { break }
  try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 2
    if ($r.StatusCode -eq 200) { $ready = $true; break }
  } catch {}
  Start-Sleep -Seconds 1
}
Write-Host "READY=$ready EXITED=$($p.HasExited)"
if ($ready) {
  $body = @{
    messages = @(@{ role = 'user'; content = 'The capital of France is' })
    max_tokens = $N
    temperature = 0
    ignore_eos = $true
  } | ConvertTo-Json -Depth 6
  try {
    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/chat/completions" -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 600
    $resp | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $dir "bench-$tag.response.json") -Encoding UTF8
    if ($resp.timings) { $resp.timings | ConvertTo-Json -Depth 4 | Write-Host }
  } catch {
    Write-Host "REQUEST_ERROR=$($_.Exception.Message)"
  }
}
if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
if ($dmon -and -not $dmon.HasExited) { Stop-Process -Id $dmon.Id -Force -ErrorAction SilentlyContinue }
Write-Host '=== err tail ==='
if (Test-Path $errLog) { Get-Content $errLog -Tail 25 }
