<#
  CangJie FOS release zip builder. Copies packaging/* to zip root; renames .bat to click-to-start name (Unicode via char codes).
  Usage:
    .\build_release_zip.ps1 -OutDir D:\Releases -ErrorIfNoCoach
    .\build_release_zip.ps1 -OutDir D:\Releases -ZipBaseName CangJie_FOS_Release_20260422 -BuildFrontend
    # Default -Profile Release: 纯净外发（排除软著/历史交付/大数据目录等）；全量调试用 -Profile Full
#>
param(
  [string] $OutDir = ".",
  [string] $ZipBaseName = "",
  [ValidateSet("Release", "Full")]
  [string] $Profile = "Release",
  [switch] $BuildFrontend,
  [switch] $ErrorIfNoCoach,
  [switch] $WhatIf
)

$ErrorActionPreference = "Stop"
$toolDir = $PSScriptRoot
$root = Split-Path -Parent $toolDir
$parent = Split-Path $root
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

if ([string]::IsNullOrWhiteSpace($ZipBaseName)) {
  $name = "CangJie_FOS_Bundle_$stamp.zip"
} else {
  $name = if ($ZipBaseName.EndsWith(".zip")) { $ZipBaseName } else { "$ZipBaseName.zip" }
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$resolvedOutDir = (Resolve-Path -LiteralPath $OutDir).Path
$out = Join-Path $resolvedOutDir $name

$coachRoot = Join-Path $parent "AI_Pitch_Coach"
$hasCoach = (Test-Path $coachRoot) -and (Test-Path (Join-Path $coachRoot "src"))
if ($ErrorIfNoCoach -and -not $hasCoach) {
  Write-Error "AI_Pitch_Coach not found or missing src: $coachRoot"
  exit 2
}
if (-not $hasCoach) {
  Write-Warning "No coach at $coachRoot; zip will only contain CangJie_FOS."
}

if ($BuildFrontend) {
  $fe = Join-Path $root "frontend"
  if (-not (Test-Path $fe)) { throw "frontend not found: $fe" }
  Write-Host "==> npm run build in $fe"
  Push-Location $fe
  try {
    if (-not (Test-Path "node_modules")) { npm install }
    npm run build
  } finally { Pop-Location }
  if (-not (Test-Path (Join-Path $fe "dist\index.html"))) { throw "BuildFrontend: dist\index.html still missing" }
}

$dist = Join-Path $root "frontend\dist\index.html"
if (-not (Test-Path $dist)) {
  Write-Error "Missing $dist. Build frontend or use -BuildFrontend."
  exit 1
}

$items = @(
  @{ Path = $root; Name = "CangJie_FOS" }
)
if (Test-Path $coachRoot) { $items += @{ Path = $coachRoot; Name = "AI_Pitch_Coach" } }

if ($WhatIf) {
  Write-Host "WhatIf: $out  Profile=$Profile"
  $items | ForEach-Object { Write-Host "  + $($_.Name)" }
  exit 0
}

function Get-CoachReleaseExtraDirs {
  param([string] $Path)
  $set = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
  foreach ($d in @(
      "client_reports", "pages", "output", "build", "dist", "tests", "docs", "scripts",
      ".executive_memory", ".company_profiles", ".cursor", ".claude", ".drafts", ".streamlit"
    )) { [void]$set.Add($d) }
  if (-not (Test-Path -LiteralPath $Path)) { return @($set) }
  Get-ChildItem -LiteralPath $Path -Directory -ErrorAction SilentlyContinue | ForEach-Object {
    $n = $_.Name
    $drop = $false
    if ($n -match "^\d{2}_") { $drop = $true }
    if ($n -match "软著") { $drop = $true }
    if ($n -match "交付") { $drop = $true }
    if ($n -cmatch "^(?i)AI") { $drop = $true }
    if ($drop) { [void]$set.Add($n) }
  }
  return @($set)
}

$tmp = Join-Path $env:TEMP "fos_bundle_$stamp"
if (Test-Path $tmp) { Remove-Item -Recurse -Force -Path $tmp }
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

# 点击开始-仓颉FOS.bat
$startBatName = -join @(
  [char]0x70B9, [char]0x51FB, [char]0x5F00, [char]0x59CB, [char]0x2D,
  [char]0x4ED3, [char]0x9895, 'FOS.bat'
)

$coachXdExtra = @()
if ($Profile -eq "Release" -and (Test-Path -LiteralPath $coachRoot)) {
  $coachXdExtra = @(Get-CoachReleaseExtraDirs -Path $coachRoot)
  Write-Host "Profile=Release: Coach extra /XD count=$($coachXdExtra.Count)"
}

try {
  foreach ($it in $items) {
    $dest = Join-Path $tmp $it.Name
    Write-Host "Robocopy $($it.Name) Profile=$Profile (exclude) ..."
    $baseXd = @(
      "node_modules", ".venv", "venv", ".git", "__pycache__", ".mypy_cache", ".pytest_cache"
    )
    if ($it.Name -eq "AI_Pitch_Coach") {
      $xd = $baseXd + @("dist", "build", "output", ".cursor", ".claude", ".drafts", ".streamlit") + $coachXdExtra
    } else {
      $xd = $baseXd
      if ($Profile -eq "Release") {
        $xd += @("软著申请材料", "html_reports", ".pytest_cache", ".cursor")
      }
    }
    $xdArg = $xd | ForEach-Object { "/XD", $_ }
    if ($it.Name -eq "AI_Pitch_Coach") {
      $argsRobo = @($it.Path, $dest, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/R:1", "/W:1") + $xdArg + @("/XF", "*.pyc", "/XF", "*.zip", "/XF", ".env", "/XF", "debug.log", "/XF", "github_sync_status.json")
      & robocopy @argsRobo
    } else {
      $argsRobo = @($it.Path, $dest, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/R:1", "/W:1") + $xdArg + @("/XF", "*.pyc", "/XF", "*.zip", "/XF", ".env")
      & robocopy @argsRobo
    }
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed for $($it.Name) code=$LASTEXITCODE" }
  }

  $pkg = Join-Path $root "packaging"
  if (Test-Path -LiteralPath $pkg) {
    Get-ChildItem -LiteralPath $pkg -File -ErrorAction SilentlyContinue | ForEach-Object {
      $dstName = $_.Name
      if ($_.Extension -eq ".bat") { $dstName = $startBatName }
      Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $tmp $dstName) -Force
      Write-Host "  packaged: $dstName"
    }
  } else { Write-Warning "packaging directory missing" }

  $fd = Join-Path $tmp ".fos_data"
  New-Item -ItemType Directory -Force -Path $fd | Out-Null
  $readmeFos = Join-Path $fd "README.txt"
  "Bridge dir for FSS / asset_index. May be empty." | Set-Content -LiteralPath $readmeFos -Encoding UTF8

  if (Test-Path -LiteralPath $out) { Remove-Item -LiteralPath $out -Force }
  Add-Type -AssemblyName System.IO.Compression
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  Write-Host "ZipFile::CreateFromDirectory (streaming) -> $out"
  [System.IO.Compression.ZipFile]::CreateFromDirectory($tmp, $out, [System.IO.Compression.CompressionLevel]::Optimal, $false)

  if (-not (Test-Path -LiteralPath $out)) { throw "Zip not created: $out" }
  $len = (Get-Item -LiteralPath $out).Length
  Write-Host "Zip size: $len bytes"

  $h = Get-FileHash -Algorithm SHA256 -LiteralPath $out
  $hashLine = "$($h.Hash)  $([IO.Path]::GetFileName($out))"

  $shaFile = "$out.sha256"
  $hashLine | Set-Content -LiteralPath $shaFile -Encoding ascii

  $metaFile = "$out.meta.txt"
  $metaBody = @(
    "CangJie FOS release bundle"
    "Profile: $Profile"
    "Built (local): $stamp"
    "Zip: $out"
    "SizeBytes: $len"
    "SHA256: $($h.Hash)"
    "IncludesCoach: $hasCoach"
    "BuildFrontend: $BuildFrontend"
  ) -join [Environment]::NewLine
  Set-Content -LiteralPath $metaFile -Value $metaBody -Encoding UTF8

  Write-Host ""
  Write-Host "OK: $out"
  Write-Host "SHA256: $($h.Hash)"
  Write-Host "Meta:   $metaFile"
} finally {
  Remove-Item -Recurse -Force -Path $tmp -ErrorAction SilentlyContinue
}
