@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title CangJie FOS — 启动中

set ROOT=%~dp0
set FRONTEND=%ROOT%frontend
set BACKEND=%ROOT%backend

echo [1/3] 检查依赖...
where node >nul 2>&1 || (echo [错误] 未找到 node，请先安装 Node.js && pause && exit /b 1)
where uv   >nul 2>&1 || (echo [错误] 未找到 uv，请先安装 uv && pause && exit /b 1)

echo [2/3] 构建前端...
cd /d "%FRONTEND%"
if not exist node_modules (
    echo     安装 npm 依赖...
    call npm install --silent
    if errorlevel 1 (echo [错误] npm install 失败 && pause && exit /b 1)
)
call npm run build
if errorlevel 1 (echo [错误] 前端构建失败 && pause && exit /b 1)
echo     前端构建完成 -> frontend\dist\

echo [3/3] 启动后端服务...
cd /d "%BACKEND%"

:: 释放 8000 端口（如有旧进程）
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING 2^>nul') do (
    taskkill /PID %%p /F >nul 2>&1
)

:: 延迟打开浏览器（等 uvicorn 启动）
start "" cmd /c "timeout /t 3 >nul && start http://localhost:8000"

echo.
echo  CangJie FOS 已启动
echo  访问: http://localhost:8000
echo  按 Ctrl+C 停止服务
echo.

uv run uvicorn cangjie_fos.main:app --host 0.0.0.0 --port 8000
