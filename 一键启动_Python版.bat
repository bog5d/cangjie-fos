@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title CangJie FOS — 启动中

set ROOT=%~dp0
set BACKEND=%ROOT%backend

echo.
echo  ========================================
echo   仓颉 FOS — Python 一键启动
echo  ========================================
echo.

:: ── 场景5：检测路径是否含中文或空格 ──
echo %ROOT% | findstr /R "[^ -~]" >nul 2>&1
if not errorlevel 1 (
    echo  [警告] 检测到路径含中文字符：
    echo  %ROOT%
    echo.
    echo  建议：把 CangJie_FOS 文件夹移动到全英文路径，例如：
    echo    C:\FOS\CangJie_FOS
    echo.
    echo  （可忽略此警告继续，但如遇启动失败请先移动路径）
    echo.
    pause
)

:: ── 检查 Python ──
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python。
    echo.
    echo  请先安装 Python 3.12：https://www.python.org/downloads/
    echo  安装时勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
for /f "tokens=1,2 delims=." %%a in ("%PYVER%") do (
    set PYMAJ=%%a
    set PYMIN=%%b
)
if %PYMAJ% LSS 3 (
    echo [错误] Python 版本太旧（需要 3.11+，当前 %PYVER%）
    pause & exit /b 1
)
if %PYMAJ% EQU 3 if %PYMIN% LSS 11 (
    echo [错误] Python 版本太旧（需要 3.11+，当前 %PYVER%）
    pause & exit /b 1
)
echo  Python %PYVER% OK

:: ── 安装 / 确认 uv ──
where uv >nul 2>&1
if errorlevel 1 (
    echo  未找到 uv，正在自动安装（需要网络，约30秒）...
    powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex" >nul 2>&1
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    where uv >nul 2>&1
    if errorlevel 1 (
        echo [错误] uv 安装失败。
        echo  可能是网络问题，请运行"诊断_打不开请运行我.bat"获取详细信息。
        pause & exit /b 1
    )
    echo  uv 安装完成 OK
) else (
    echo  uv OK
)

:: ── 前端检查 ──
if exist "%ROOT%frontend\dist\index.html" (
    echo  前端已预编译 OK
) else (
    echo [错误] 未找到预编译前端，请联系王波获取完整版本。
    pause & exit /b 1
)

:: ── 场景1：首次安装提示 ──
if not exist "%BACKEND%\.venv" (
    echo.
    echo  ╔══════════════════════════════════════════════╗
    echo  ║  首次启动：需要下载 Python 依赖（约250MB）   ║
    echo  ║  请耐心等待 5~15 分钟，不要关闭此窗口！     ║
    echo  ║  进度显示在下方，看到绿色 OK 才算完成。     ║
    echo  ╚══════════════════════════════════════════════╝
    echo.
)

:: ── 释放 8000 端口 ──
echo  检查端口 8000...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING 2^>nul') do (
    taskkill /PID %%p /F >nul 2>&1
)

:: ── 检查 .env ──
if not exist "%BACKEND%\.env" (
    echo.
    echo  [警告] 未找到 API Key 配置文件！
    echo  系统可以启动，但 AI 功能将无法使用。
    echo.
    echo  请先运行"填写API密钥_双击我.bat"配置密钥，再启动系统。
    echo.
    pause
)

:: ── 启动后端 ──
echo  启动服务...
cd /d "%BACKEND%"

start "" cmd /c "timeout /t 6 >nul && start http://localhost:8000"

echo.
echo  ✅ CangJie FOS 已启动
echo  访问: http://localhost:8000
echo  按 Ctrl+C 停止服务
echo.

REM 默认仅本机：127.0.0.1；若需局域网访问可改为 0.0.0.0
uv run uvicorn cangjie_fos.main:app --host 127.0.0.1 --port 8000

echo.
echo  服务已停止。按任意键退出。
pause >nul
