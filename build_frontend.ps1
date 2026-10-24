$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$fe = Join-Path $root "frontend"
Set-Location $fe
if (-not (Test-Path "node_modules")) {
  npm install
} else {
  npm install
}
npm run build
npm run test
Write-Host "Frontend dist -> $(Join-Path $fe 'dist')"
