@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
title 仓颉 FOS — 自动诊断修复

echo.
echo  ========================================
echo   仓颉 FOS — 自动诊断 ^& 修复
echo  ========================================
echo  运行时间: %date% %time%
echo.

set ROOT=%~dp0
set BACKEND=%ROOT%backend

:: ════════════════════════════════════════
:: Step 1: doctor.py 自动诊断修复
:: ════════════════════════════════════════
echo [Step 1] 运行自动诊断修复...
echo.

python "%ROOT%tools\doctor.py" --fix
set DOCTOR_EXIT=%ERRORLEVEL%

echo.
if %DOCTOR_EXIT% NEQ 0 (
    echo  ┌──────────────────────────────────────────┐
    echo  │  诊断发现问题，请按提示操作               │
    echo  │                                          │
    echo  │  常见问题及解决方法：                     │
    echo  │  1. 端口被占用  → 关闭占用 8000 端口的进程│
    echo  │  2. 依赖缺失    → 重新运行安装并启动.ps1  │
    echo  │  3. 权限不足    → 右键以管理员身份运行    │
    echo  └──────────────────────────────────────────┘
    echo.
    pause
    exit /b 1
)

:: ════════════════════════════════════════
:: Step 2: 启动 uvicorn
:: ════════════════════════════════════════
echo [Step 2] 诊断通过，启动仓颉 FOS 系统...
echo.

:: 8 秒后自动打开浏览器
start "" cmd /c "timeout /t 8 >nul && start http://localhost:8000"

cd /d "%BACKEND%"
uv run uvicorn cangjie_fos.main:app --host 0.0.0.0 --port 8000
set START_EXIT=%ERRORLEVEL%

if %START_EXIT% NEQ 0 (
    echo.
    echo  ┌──────────────────────────────────────────────┐
    echo  │  启动失败，请检查上方错误信息                  │
    echo  │                                              │
    echo  │  常见原因及解决方法：                         │
    echo  │  - 端口 8000 被占用                          │
    echo  │    → 关闭其他占用 8000 端口的进程             │
    echo  │  - 依赖未安装完整                             │
    echo  │    → 重新运行 安装并启动.ps1                  │
    echo  │  - .env 缺少必要 API Key                     │
    echo  │    → 双击 填写API密钥_双击我.bat 填写          │
    echo  │  - Python 版本过低（需要 3.10+）              │
    echo  │    → 安装 Python 3.12                        │
    echo  └──────────────────────────────────────────────┘
    echo.
)

pause
