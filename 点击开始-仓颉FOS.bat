@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title 仓颉 FOS — 正在启动...

set ROOT=%~dp0
set BE=%ROOT%backend

:: ── 检查 uv 是否安装 ──────────────────────────────────────────
where uv >nul 2>&1
if errorlevel 1 (
    echo.
    echo  ? 未找到 uv 包管理器。
    echo  请先双击运行「安装并启动.ps1」完成首次安装，之后再用本文件启动。
    echo.
    pause
    exit /b 1
)

:: ── 检查 .env 是否有必填 Key ──────────────────────────────────
set ENVFILE=%BE%\.env
if not exist "%ENVFILE%" (
    echo.
    echo  ??  未找到密钥配置文件（backend\.env）
    echo  请先双击「填写API密钥_双击我.bat」填写密钥，再启动。
    echo.
    pause
    exit /b 1
)

:: ── 启动后端（新窗口，关闭本窗口不影响后端）──────────────────
echo.
echo  ? 正在启动仓颉 FOS...
echo.

start "仓颉FOS后端" /D "%BE%" cmd /c "uv run uvicorn cangjie_fos.main:app --host 127.0.0.1 --port 8000 & pause"

:: ── 等待后端就绪（最多 15 秒）────────────────────────────────
echo  等待后端启动中，请稍候...
set /a attempts=0
:wait_loop
    timeout /t 1 /nobreak >nul
    curl -s -o nul -w "%%{http_code}" http://127.0.0.1:8000/api/v1/ready 2>nul | findstr /C:"200" >nul
    if not errorlevel 1 goto :ready
    set /a attempts+=1
    if %attempts% geq 15 goto :timeout
goto :wait_loop

:timeout
echo  ??  后端未能在 15 秒内响应，尝试直接打开浏览器...
goto :open_browser

:ready
echo  ? 后端已就绪！

:open_browser
start "" "http://127.0.0.1:8000"
echo.
echo  已在浏览器打开：http://127.0.0.1:8000
echo.
echo  提示：关闭「仓颉FOS后端」窗口即可停止服务。
echo.
timeout /t 3 /nobreak >nul
exit /b 0

