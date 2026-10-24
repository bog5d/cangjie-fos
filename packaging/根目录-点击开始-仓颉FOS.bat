@echo off
setlocal
chcp 65001 >nul 2>&1
cd /d "%~dp0"

if not exist "CangJie_FOS\安装并启动.ps1" (
  echo.
  echo  [错误] 未找到 CangJie_FOS\安装并启动.ps1
  echo  请确认已完整解压压缩包，且本文件与 CangJie_FOS 文件夹在同一目录下。
  echo.
  pause
  exit /b 1
)

echo.
echo  ========================================
echo   仓颉 FOS — 正在启动
echo  ========================================
echo  将打开 PowerShell 执行安装与启动脚本。
echo  若被 Windows 拦截，请选「仍要运行」。
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0CangJie_FOS\安装并启动.ps1"
set ERR=%ERRORLEVEL%
if not "%ERR%"=="0" (
  echo.
  echo  若启动失败，请打开同目录下的《仓颉FOS-使用指引》或 CangJie_FOS\同事上手指南.md
  echo.
  pause
)

endlocal
exit /b 0
