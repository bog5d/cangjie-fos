# 本地预检：目录、Python、Coach、dist、.env（退出码 0=通过）
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$fail = 0

function Step($name) { Write-Host "`n=== $name ===" }

Step "Paths"
Write-Host "CangJie_FOS root: $root"
$coach = Join-Path (Split-Path $root) "AI_Pitch_Coach\src"
if (Test-Path $coach) { Write-Host "[OK] AI_Pitch_Coach\src" } else { Write-Host "[!!] Missing: $coach"; $fail++ }

$dist = Join-Path $root "frontend\dist\index.html"
if (Test-Path $dist) { Write-Host "[OK] frontend\dist\index.html" } else { Write-Host "[!!] Missing: $dist"; $fail++ }

$envf = Join-Path $root "backend\.env"
if (Test-Path $envf) { Write-Host "[OK] backend\.env exists" } else { Write-Host "[!!] No backend\.env"; $fail++ }

Step "Python"
try {
  $v = & python --version 2>&1
  Write-Host "[OK] $v"
} catch { Write-Host "[!!] python not found"; $fail++ }

Step "uv (optional)"
$uvPath = Get-Command uv -ErrorAction SilentlyContinue
if ($uvPath) { & uv --version } else { Write-Host "[--] uv not in PATH (install from astral.sh)" }

exit $fail

