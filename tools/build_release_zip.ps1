<#
  CangJie FOS release zip builder (clean external distribution).

  Output always goes to D:\Releases\ (fixed, easy to find).
  Usage:
    .\build_release_zip.ps1
    .\build_release_zip.ps1 -BuildFrontend
    .\build_release_zip.ps1 -OutDir D:\MyOtherDir   (override only when needed)

  What's in the zip (minimal, colleague-safe):
    CangJie_FOS/        backend + frontend/dist (no tests, no docs, no node_modules)
    AI_Pitch_Coach/     evaluation engine
    .fos_data/          placeholder bridge dir
    ROOT FILES (from packaging/):
      点击开始-仓颉FOS.bat        <- one double-click to start
      00_先看这一行.txt           <- 3-line quick start
      仓颉FOS-使用指引...md       <- onboarding guide
      本次更新说明.md             <- per-release: what changed / how to test

  What's excluded:
    docs/ tests/ .github/ .cursor/  (internal dev files)
    AGENTS.md CLAUDE.md TODO_LIST_*.md  (AI-internal)
    node_modules .venv .git __pycache__  (runtime artifacts)
    *.pyc *.zip .env  (credentials must never ship)
#>
param(
  [string] $OutDir = "D:\Releases",
  [string] $ZipBaseName = "",
  [switch] $BuildFrontend,
  [switch] $ErrorIfNoCoach,
  [switch] $WhatIf
)

$ErrorActionPreference = "Stop"
$toolDir = $PSScriptRoot
$root    = Split-Path -Parent $toolDir
$parent  = Split-Path $root
$stamp   = Get-Date -Format "yyyyMMdd_HHmmss"

if ([string]::IsNullOrWhiteSpace($ZipBaseName)) {
  $zipName = "CangJie_FOS_Release_$stamp.zip"
} else {
  $zipName = if ($ZipBaseName.EndsWith(".zip")) { $ZipBaseName } else { "$ZipBaseName.zip" }
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$resolvedOutDir = (Resolve-Path -LiteralPath $OutDir).Path
$out = Join-Path $resolvedOutDir $zipName

# Coach detection
$coachRoot = Join-Path $parent "AI_Pitch_Coach"
$hasCoach  = (Test-Path $coachRoot) -and (Test-Path (Join-Path $coachRoot "src"))
if ($ErrorIfNoCoach -and -not $hasCoach) {
  Write-Error "AI_Pitch_Coach not found: $coachRoot"
  exit 2
}
if (-not $hasCoach) {
  Write-Warning "AI_Pitch_Coach not found; bundle will only contain CangJie_FOS"
}

# Optional frontend build
if ($BuildFrontend) {
  $fe = Join-Path $root "frontend"
  Write-Host "==> npm run build in $fe"
  Push-Location $fe
  try {
    if (-not (Test-Path "node_modules")) { npm install }
    npm run build
  } finally { Pop-Location }
}

$dist = Join-Path $root "frontend\dist\index.html"
if (-not (Test-Path $dist)) {
  Write-Error "Frontend not built: $dist missing. Run npm run build or pass -BuildFrontend."
  exit 1
}

Write-Host "==> Output: $out"
if ($WhatIf) { Write-Host "WhatIf mode, exiting"; exit 0 }

# Temp staging dir
$tmp = Join-Path $env:TEMP "fos_bundle_$stamp"
if (Test-Path $tmp) { Remove-Item -Recurse -Force -Path $tmp }
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

# Click-to-start bat filename (Unicode)
$startBatName = -join @(
  [char]0x70B9,[char]0x51FB,[char]0x5F00,[char]0x59CB,[char]0x2D,
  [char]0x4ED3,[char]0x9895,'FOS.bat'
)

try {
  # === CangJie_FOS ===
  $fosDest = Join-Path $tmp "CangJie_FOS"

  $xdDirs = @(
    "node_modules", ".venv", "venv", ".git", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "docs",
    "releases",
    "tests",
    ".github",
    ".cursor",
    ".claude",
    "html_reports",
    "audio",
    (Join-Path $root "soft_copyright_materials")
  )
  # Add absolute path for the Chinese-named copyright dir
  $copyrightDir = Join-Path $root ([char]0x8F6F + [char]0x8457 + [char]0x7533 + [char]0x8BF7 + [char]0x6750 + [char]0x6599)
  if (Test-Path -LiteralPath $copyrightDir) {
    $xdDirs += $copyrightDir
  }

  $xfFiles = @(
    "*.pyc",
    "*.zip",
    ".env",
    "AGENTS.md",
    "CLAUDE.md",
    "TODO_LIST_PHASE*.md",
    "TODO_LIST_PHASE2.md",
    "TODO_LIST_PHASE3.md",
    "TODO_LIST_PHASE4.md",
    "TODO_LIST_PHASE5.md",
    "TODO_LIST_PHASE6.md",
    "*.sha256",
    "*.meta.txt",
    "github_sync_status.json",
    "debug.log",
    "docker-compose.yml",
    "Dockerfile",
    ".dockerignore",
    "run_dev.ps1",
    "build_frontend.ps1",
    "start.sh"
  )

  $xdArg = $xdDirs  | ForEach-Object { "/XD", $_ }
  $xfArg = $xfFiles | ForEach-Object { "/XF", $_ }

  $roboArgs = @($root, $fosDest, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/R:1", "/W:1") + $xdArg + $xfArg
  Write-Host "Robocopy CangJie_FOS ..."
  & robocopy @roboArgs
  if ($LASTEXITCODE -ge 8) { throw "robocopy failed code=$LASTEXITCODE" }

  # === AI_Pitch_Coach ===
  if ($hasCoach) {
    $coachDest = Join-Path $tmp "AI_Pitch_Coach"
    $coachXdDirs = @(
      "node_modules", ".venv", "venv", ".git", "__pycache__",
      ".mypy_cache", ".pytest_cache", ".ruff_cache",
      "dist", "build", "output", "client_reports", "pages",
      "tests", "docs", "scripts",
      ".cursor", ".claude", ".drafts", ".streamlit",
      ".executive_memory", ".company_profiles"
    )
    Get-ChildItem -LiteralPath $coachRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object {
      $n = $_.Name
      if ($n -match "^\d{2}_" -or $n -match "AI") { $coachXdDirs += $n }
    }
    $cXdArg = $coachXdDirs | ForEach-Object { "/XD", $_ }
    $cXfArg = @("/XF","*.pyc","/XF","*.zip","/XF",".env","/XF","debug.log","/XF","github_sync_status.json","/XF","AGENTS.md","/XF","CLAUDE.md")
    $coachRoboArgs = @($coachRoot, $coachDest, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/R:1", "/W:1") + $cXdArg + $cXfArg
    Write-Host "Robocopy AI_Pitch_Coach ..."
    & robocopy @coachRoboArgs
    if ($LASTEXITCODE -ge 8) { throw "robocopy Coach failed code=$LASTEXITCODE" }
  }

  # === packaging/ -> zip root ===
  $pkg = Join-Path $root "packaging"
  if (Test-Path -LiteralPath $pkg) {
    Get-ChildItem -LiteralPath $pkg -File -ErrorAction SilentlyContinue | ForEach-Object {
      $dstName = $_.Name
      if ($_.Extension -eq ".bat") { $dstName = $startBatName }
      Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $tmp $dstName) -Force
      Write-Host "  root: $dstName"
    }
  } else { Write-Warning "packaging/ directory missing" }

  # === .fos_data placeholder ===
  $fdDir = Join-Path $tmp ".fos_data"
  New-Item -ItemType Directory -Force -Path $fdDir | Out-Null
  "Bridge dir for FSS / asset_index. May be empty on first run." | Set-Content -LiteralPath (Join-Path $fdDir "README.txt") -Encoding UTF8

  # === Create zip ===
  if (Test-Path -LiteralPath $out) { Remove-Item -LiteralPath $out -Force }
  Add-Type -AssemblyName System.IO.Compression
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  Write-Host "Compressing -> $out"
  [System.IO.Compression.ZipFile]::CreateFromDirectory($tmp, $out, [System.IO.Compression.CompressionLevel]::Optimal, $false)

  $len  = (Get-Item -LiteralPath $out).Length
  $h    = Get-FileHash -Algorithm SHA256 -LiteralPath $out
  "$($h.Hash)  $([IO.Path]::GetFileName($out))" | Set-Content -LiteralPath "$out.sha256" -Encoding ascii

  @(
    "CangJie FOS release bundle",
    "Built: $stamp",
    "SizeBytes: $len",
    "SHA256: $($h.Hash)",
    "IncludesCoach: $hasCoach",
    "BuildFrontend: $BuildFrontend",
    "ZipPath: $out"
  ) -join [Environment]::NewLine | Set-Content -LiteralPath "$out.meta.txt" -Encoding UTF8

  Write-Host ""
  Write-Host "==== Release OK ===="
  Write-Host "File: $out"
  Write-Host "Size: $([math]::Round($len/1MB,1)) MB"
  Write-Host "SHA256: $($h.Hash)"

} finally {
  Remove-Item -Recurse -Force -Path $tmp -ErrorAction SilentlyContinue
}

