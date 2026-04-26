@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title CangJie FOS — Docker 启动

set ROOT=%~dp0

echo.
echo  ========================================
echo   仓颉 FOS — Docker 一键启动
echo  ========================================
echo.

:: 检查 Docker
where docker >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Docker。
    echo.
    echo  请先安装 Docker Desktop：
    echo  https://www.docker.com/products/docker-desktop/
    echo.
    echo  安装后重启电脑，再双击本文件。
    pause
    exit /b 1
)

:: 检查 Docker daemon 是否运行
docker info >nul 2>&1
if errorlevel 1 (
    echo [错误] Docker 未启动，请先打开 Docker Desktop 等待它完全启动后再试。
    pause
    exit /b 1
)

echo [1/2] Docker 就绪，启动服务...
cd /d "%ROOT%"

:: 停止旧容器（如有）
docker compose down >nul 2>&1

echo [2/2] 构建并启动（首次约 3-5 分钟，后续秒开）...
echo.

:: 后台延迟打开浏览器
start "" cmd /c "timeout /t 15 >nul && start http://localhost:8000"

docker compose up --build

echo.
echo  服务已停止。按任意键退出。
pause >nul
