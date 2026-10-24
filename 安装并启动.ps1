# 解压后于 CangJie_FOS 根目录运行：预检 + 启动 uvicorn（本机单用户）
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$be = Join-Path $root "backend"
$logsDir = Join-Path $be "logs"
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $logsDir "startup_$ts.log"

# ── 确保 logs 目录存在 ────────────────────────────────────
if (-not (Test-Path $logsDir)) {
  New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
}

function Write-Log {
  param([string]$msg)
  $line = "[$(Get-Date -Format 'HH:mm:ss')] $msg"
  Write-Host $msg
  Add-Content -Path $logFile -Value $line -Encoding UTF8
}

function Write-Fail {
  param([string]$step, [string]$detail)
  Write-Log "[错误] 步骤失败：$step"
  Write-Log "详情：$detail"

  # 生成桌面诊断报告（纯ASCII文件名，避免中文Windows乱码）
  $desktop = [Environment]::GetFolderPath("Desktop")
  $reportFile = Join-Path $desktop "FOS_DiagReport_$ts.txt"
  $sysInfo = "OS: $([System.Environment]::OSVersion.VersionString) | PS: $($PSVersionTable.PSVersion) | Log: $logFile"

  $lines = @(
    "==== CangJie FOS Startup Failure Report ===="
    "Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    "Failed step: $step"
    ""
    "Error detail:"
    $detail
    ""
    "System info:"
    $sysInfo
    ""
    "Log file: $logFile"
    ""
    "============================================"
    "Please paste all content above to AI / tech support."
    "============================================"
  )
  $reportContent = $lines -join [Environment]::NewLine

  $reportContent | Out-File -FilePath $reportFile -Encoding UTF8
  Write-Log "诊断报告已生成：$reportFile"
  Write-Host ""
  Write-Host "  ❌ 启动失败！诊断报告已保存到桌面："
  Write-Host "     $reportFile"
  Write-Host ""
  Write-Host "  请把该文件内容发给 AI 或技术支持，他们可以帮你快速定位问题。"
  Write-Host ""

  # 用记事本打开报告
  Start-Process "notepad.exe" -ArgumentList "`"$reportFile`"" -ErrorAction SilentlyContinue
}

Set-Location $be
Write-Log "=== 仓颉 FOS 启动日志 === (日志：$logFile)"

# ── 1. 安装 uv（如未安装）──────────────────────────────────
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Log "[1/4] 安装 uv 包管理器（约30秒）..."
  try {
    powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex" 2>&1 | Tee-Object -Append -FilePath $logFile
    $env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
      throw "uv 安装后仍未找到命令"
    }
    Write-Log "[1/4] uv 安装成功 ✓"
  } catch {
    Write-Fail "[1/4] 安装 uv" $_.Exception.Message
    pause; exit 1
  }
} else {
  Write-Log "[1/4] uv 已安装 ✓"
}

# ── 2. 安装 Python 依赖 ────────────────────────────────────
Write-Log "[2/4] 安装依赖（首次约3-5分钟，之后秒速）..."
$depOut = uv sync 2>&1
$depOut | ForEach-Object { Add-Content -Path $logFile -Value $_ -Encoding UTF8 }
$depOut | Write-Host
if ($LASTEXITCODE -ne 0) {
  Write-Log "[2/4] 安装失败，清理虚拟环境重试..."
  $venvPath = Join-Path $be ".venv"
  if (Test-Path $venvPath) { Remove-Item -Recurse -Force $venvPath }
  $depOut = uv sync 2>&1
  $depOut | ForEach-Object { Add-Content -Path $logFile -Value $_ -Encoding UTF8 }
  $depOut | Write-Host
  if ($LASTEXITCODE -ne 0) {
    Write-Fail "[2/4] 安装依赖" ($depOut | Select-Object -Last 20 | Out-String)
    pause; exit 1
  }
}
Write-Log "[2/4] 依赖安装完成 ✓"

# ── 3. 预下载 FFmpeg（imageio-ffmpeg 内置，首次需联网）────
Write-Log "[3/4] 准备 FFmpeg 音频处理器..."
$ffOut = uv run python -c "import imageio_ffmpeg; imageio_ffmpeg.get_ffmpeg_exe(); print('FFmpeg 就绪 ✓')" 2>&1
$ffOut | ForEach-Object { Add-Content -Path $logFile -Value $_ -Encoding UTF8 }
if ($LASTEXITCODE -ne 0) {
  Write-Log "[警告] FFmpeg 自动下载失败，音频压缩将跳过（不影响 ASR 功能）"
} else {
  Write-Log "[3/4] FFmpeg 就绪 ✓"
}

# ── 4. 启动服务 ────────────────────────────────────────────
Write-Log "[4/4] 启动服务，请稍候..."
$hostLine = "127.0.0.1"
Start-Process "http://${hostLine}:8000" -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "  ✅ 仓颉 FOS 正在运行：http://${hostLine}:8000"
Write-Host "  按 Ctrl+C 停止服务"
Write-Host "  启动日志：$logFile"
Write-Host ""

uv run uvicorn cangjie_fos.main:app --host $hostLine --port 8000 2>&1 | Tee-Object -Append -FilePath $logFile
