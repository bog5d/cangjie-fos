# 夜间验证：预检 + pytest（日志落盘）
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$be = Join-Path $root "backend"
$log = Join-Path $root "tools\nightly_verify.log"
"=== $(Get-Date -Format o) ===" | Tee-Object -FilePath $log -Append
& (Join-Path $root "tools\preflight_local.ps1") 2>&1 | Tee-Object -FilePath $log -Append
Set-Location $be
& uv run python -m pytest tests/ -q 2>&1 | Tee-Object -FilePath $log -Append
exit $LASTEXITCODE

