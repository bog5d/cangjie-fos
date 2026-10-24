# 备份 backend/data 下 *.sqlite 到 backend/data/backup/
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$be = Join-Path $root "backend"
$data = Join-Path $be "data"
$bak = Join-Path $data "backup"
New-Item -ItemType Directory -Force -Path $bak | Out-Null
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
Get-ChildItem -Path $data -Filter "*.sqlite" -File -ErrorAction SilentlyContinue | ForEach-Object {
    $dest = Join-Path $bak ("{0}_{1}" -f $ts, $_.Name)
    Copy-Item -LiteralPath $_.FullName -Destination $dest -Force
    Write-Host "Backed up $($_.Name) -> $dest"
}
Write-Host "Done."

