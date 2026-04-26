# 解压后于 CangJie_FOS 根目录运行：预检 + 启动 uvicorn（本机单用户）
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$be = Join-Path $root "backend"
Set-Location $be
& (Join-Path $root "tools\preflight_local.ps1")
if ($LASTEXITCODE -ne 0) {
  Write-Warning "预检有缺项，仍可尝试启动；请阅读 docs/RELEASE_CHECKLIST.md"
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Host "Installing uv..."
  powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  $env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
}
$hostLine = "127.0.0.1"
Write-Host "Starting http://${hostLine}:8000/ (按 Ctrl+C 停止)"
& uv run uvicorn cangjie_fos.main:app --host $hostLine --port 8000
