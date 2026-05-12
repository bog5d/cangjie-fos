@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title 仓颉 FOS — 启动诊断

echo.
echo  ========================================
echo   仓颉 FOS — 启动诊断
echo  ========================================
echo  诊断时间: %date% %time%
echo.

set ROOT=%~dp0
set BACKEND=%ROOT%backend

:: ════════════════════════════════════════
:: Step 1: 运行 doctor.py 自动诊断修复
:: ════════════════════════════════════════
echo [Step 1] 运行自动诊断与修复...
echo.

python "%ROOT%tools\doctor.py" --fix
set DOCTOR_EXIT=%ERRORLEVEL%

echo.
if %DOCTOR_EXIT% NEQ 0 (
    echo  ┌─────────────────────────────────────────┐
    echo  │  ? 诊断发现问题，请按上方提示操作后重试  │
    echo  │                                         │
    echo  │  常见问题处理：                          │
    echo  │  1. 端口占用  → 已自动释放，重新运行即可  │
    echo  │  2. 依赖缺失  → 已自动安装，重新运行即可  │
    echo  │  3. 无网络    → 切换手机热点后重新运行    │
    echo  │  4. 权限不足  → 右键以管理员身份运行      │
    echo  └─────────────────────────────────────────┘
    echo.
    pause
    exit /b 1
)

:: ════════════════════════════════════════
:: Step 2: 启动 uvicorn
:: ════════════════════════════════════════
echo [Step 2] 所有检查通过，正在启动系统...
echo.

:: 8 秒后自动打开浏览器
start "" cmd /c "timeout /t 8 >nul && start http://localhost:8000"

cd /d "%BACKEND%"
uv run uvicorn cangjie_fos.main:app --host 0.0.0.0 --port 8000
set START_EXIT=%ERRORLEVEL%

if %START_EXIT% NEQ 0 (
    echo.
    echo  ┌─────────────────────────────────────────────┐
    echo  │  ? 启动失败，请查看上方错误信息              │
    echo  │                                             │
    echo  │  常见原因及解决方法：                        │
    echo  │  ● 端口 8000 仍被占用                       │
    echo  │    → 打开任务管理器，结束占用 8000 端口的进程 │
    echo  │  ● 依赖安装不完整                            │
    echo  │    → 手动运行：cd backend ^&^& uv sync --extra dev  │
    echo  │  ● .env 缺少必要 API Key                    │
    echo  │    → 双击「填写API密钥_双击我.bat」配置密钥   │
    echo  │  ● Python 版本过低（需要 3.10+）             │
    echo  │    → 重新安装 Python 3.12                   │
    echo  │  ● 权限不足（Windows 安全策略）              │
    echo  │    → 右键此文件，选择「以管理员身份运行」     │
    echo  └─────────────────────────────────────────────┘
    echo.
)

pause

