<#
  CangJie FOS — PR / 发版前质量门禁（本机可重复）
  顺序：backend 关键 pytest 子集 -> frontend production build
  用法：在 CangJie_FOS 根目录或 tools 下
    .\tools\ci_check.ps1
  失败：非零 exit code
#>
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$root = Split-Path -Parent $here
$be = Join-Path $root "backend"
$fe = Join-Path $root "frontend"

if (-not (Test-Path $be)) { Write-Error "backend not found: $be"; exit 1 }
if (-not (Test-Path $fe)) { Write-Error "frontend not found: $fe"; exit 1 }

$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Error "uv not on PATH. Install: https://astral.sh/uv or add USERPROFILE\.local\bin to PATH"
  exit 1
}

$tests = @(
  "tests/test_report_post_process.py"
  "tests/test_assets_api.py"
  "tests/test_pitch_job_db.py"
  "tests/test_p0_review_endpoints.py"
  "tests/test_smoke_probes.py"
  "tests/test_readiness_hardening.py"
)

Write-Host "==> ci_check: backend pytest (subset)" -ForegroundColor Cyan
Push-Location $be
try {
  $args = @("run", "pytest", "-q", "--tb=short") + $tests
  & uv @args
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally { Pop-Location }

Write-Host "==> ci_check: frontend npm run build" -ForegroundColor Cyan
Push-Location $fe
try {
  if (-not (Test-Path "node_modules")) { npm install }
  npm run build
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally { Pop-Location }

Write-Host "ci_check: OK" -ForegroundColor Green
exit 0

