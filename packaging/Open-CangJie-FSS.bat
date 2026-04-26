@echo off
setlocal
chcp 65001 >nul 2>&1
cd /d "%~dp0"

REM === 仓颉资产台账 FSS：可选一键启动 + 打开桥目录 ===
REM 1) 将 FSS 安装后的 .exe 完整路径写入同目录 fss_path.txt（单行），或改下面 FSS_EXE。
set "FSS_EXE="
if exist "%~dp0fss_path.txt" (
  for /f "usebackq delims=" %%i in ("%~dp0fss_path.txt") do set "FSS_EXE=%%i"
)
if not "%FSS_EXE%"=="" if exist "%FSS_EXE%" (
  start "" "%FSS_EXE%"
) else (
  echo.
  echo  [提示] 未找到 FSS。请安装「仓颉资产台账」后，在本目录创建 fss_path.txt，首行写 FSS.exe 的完整路径。
  echo.
)

REM 2) 打开与 FOS 共用的 .fos_data（与解压布局一致时在本层）
if exist "%~dp0.fos_data" (
  explorer "%~dp0.fos_data"
) else (
  explorer "%~dp0"
)
endlocal
exit /b 0
