# 解压后于 CangJie_FOS 根目录运行：预检 + 启动 uvicorn（本机单用户）
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$be = Join-Path $root "backend"
Set-Location $be

# ── 1. 安装 uv（如未安装）──────────────────────────────────
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Host "[1/4] 安装 uv 包管理器（约30秒）..."
  powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  $env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
} else {
  Write-Host "[1/4] uv 已安装 ✓"
}

# ── 2. 安装 Python 依赖 ────────────────────────────────────
Write-Host "[2/4] 安装依赖（首次约3-5分钟，之后秒速）..."
uv sync --extra dev 2>&1
if ($LASTEXITCODE -ne 0) {
  Write-Host "[错误] 依赖安装失败。请检查网络，或联系发包人。"
  pause; exit 1
}

# ── 3. 预下载 FFmpeg（imageio-ffmpeg 内置，首次需联网）────
Write-Host "[3/4] 准备 FFmpeg 音频处理器..."
uv run python -c "import imageio_ffmpeg; imageio_ffmpeg.get_ffmpeg_exe(); print('FFmpeg 就绪 ✓')" 2>&1
if ($LASTEXITCODE -ne 0) {
  Write-Host "[警告] FFmpeg 自动下载失败，音频压缩将跳过（不影响 ASR 功能）"
}

# ── 4. 启动服务 ────────────────────────────────────────────
Write-Host "[4/4] 启动服务，请稍候..."
$hostLine = "127.0.0.1"
Start-Process "http://${hostLine}:8000" -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "  ✅ 仓颉 FOS 正在运行：http://${hostLine}:8000"
Write-Host "  按 Ctrl+C 停止服务"
Write-Host ""
uv run uvicorn cangjie_fos.main:app --host $hostLine --port 8000
