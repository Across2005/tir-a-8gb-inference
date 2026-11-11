$ErrorActionPreference = 'Continue'
$dir = 'E:\Deepseek\tir-b\runtime\llama-b12202'
$model = 'E:\model\bionic\Qwen\Qwen3.8-9B-Distill-GGUF\Qwen3.8-9B-Q5_K_M.gguf'
$outLog = Join-Path $dir 'mtp.out.log'
$errLog = Join-Path $dir 'mtp.err.log'
Remove-Item $outLog, $errLog -ErrorAction SilentlyContinue

$args = @(
  '-m', $model,
  '-c', '2048',
  '-ngl', '99',
  '-fa', 'on',
  '-ctk', 'q8_0',
  '-ctv', 'q8_0',
  '--host', '127.0.0.1',
  '--port', '18099',
  '--spec-type', 'draft-mtp',
  '--metrics',
  '--jinja',
  '--load-mode', 'none'
)
$p = Start-Process -FilePath (Join-Path $dir 'llama-server.exe') -ArgumentList $args -WorkingDirectory $dir -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru -WindowStyle Hidden
$p.Id | Set-Content (Join-Path $dir 'mtp.pid')
Write-Host "PID=$($p.Id)"

$ready = $false
for ($i = 0; $i -lt 150; $i++) {
  if ($p.HasExited) { break }
  try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:18099/health' -UseBasicParsing -TimeoutSec 2
    if ($r.StatusCode -eq 200) { $ready = $true; break }
  } catch {}
  Start-Sleep -Seconds 1
}
Write-Host "READY=$ready EXITED=$($p.HasExited)"
if ($ready) {
  $body = @{
    messages = @(@{ role = 'user'; content = 'The capital of France is' })
    max_tokens = 64
    temperature = 0
  } | ConvertTo-Json -Depth 6
  try {
    $resp = Invoke-RestMethod -Uri 'http://127.0.0.1:18099/v1/chat/completions' -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 300
    $resp | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $dir 'mtp.response.json') -Encoding UTF8
    if ($resp.timings) {
      $resp.timings | ConvertTo-Json -Depth 4 | Write-Host
    } else {
      Write-Host 'NO_TIMINGS'
      $resp | ConvertTo-Json -Depth 8 | Write-Host
    }
  } catch {
    Write-Host "REQUEST_ERROR=$($_.Exception.Message)"
  }
}
if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
Write-Host '=== err tail ==='
if (Test-Path $errLog) { Get-Content $errLog -Tail 40 }
Write-Host '=== out tail ==='
if (Test-Path $outLog) { Get-Content $outLog -Tail 20 }
