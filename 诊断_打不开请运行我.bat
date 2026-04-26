@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title 仓颉 FOS — 启动诊断

echo.
echo  ========================================
echo   仓颉 FOS — 启动诊断（截图发给王波）
echo  ========================================
echo  诊断时间: %date% %time%
echo.

set ROOT=%~dp0
set BACKEND=%ROOT%backend
set PASS=0
set FAIL=0

:: ════════════════════════════════════════
:: [1/7] 路径检查
:: ════════════════════════════════════════
echo [1/7] 检查解压路径...
echo  当前路径: %ROOT%
echo %ROOT% | findstr /R "[^ -~]" >nul 2>&1
if not errorlevel 1 (
    echo  [警告] 路径含中文或特殊字符！
    echo  建议：把文件夹移动到纯英文路径，例如 C:\FOS\CangJie_FOS
    set /a FAIL+=1
) else (
    echo  路径 OK
    set /a PASS+=1
)

:: ════════════════════════════════════════
:: [2/7] 磁盘空间检查（需要约500MB）
:: ════════════════════════════════════════
echo.
echo [2/7] 检查磁盘可用空间...
for /f "tokens=3" %%s in ('dir /-c "%ROOT%" 2^>nul ^| findstr /C:"个可用字节" /C:"bytes free"') do set FREE_BYTES=%%s
set FREE_BYTES=%FREE_BYTES:,=%
if defined FREE_BYTES (
    if %FREE_BYTES% LSS 524288000 (
        echo  [错误] 磁盘空间不足！剩余: %FREE_BYTES% 字节（需要至少500MB）
        echo  请清理磁盘后重试。
        set /a FAIL+=1
    ) else (
        echo  磁盘空间 OK（剩余足够）
        set /a PASS+=1
    )
) else (
    echo  磁盘空间检测跳过（无法读取）
)

:: ════════════════════════════════════════
:: [3/7] Python 检查
:: ════════════════════════════════════════
echo.
echo [3/7] 检查 Python...
python --version 2>&1
if errorlevel 1 (
    echo  [错误] 未检测到 Python！
    echo.
    echo  解决方法：
    echo  1. 访问 https://www.python.org/downloads/
    echo  2. 下载 Python 3.12 安装包
    echo  3. 安装时必须勾选 "Add Python to PATH"
    echo  4. 安装完成后重新运行此诊断
    set /a FAIL+=1
    goto :check_uv
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo  Python %PYVER% OK
set /a PASS+=1

:check_uv
:: ════════════════════════════════════════
:: [4/7] uv 检查
:: ════════════════════════════════════════
echo.
echo [4/7] 检查 uv 包管理器...
where uv >nul 2>&1
if errorlevel 1 (
    echo  未找到 uv，尝试安装（约30秒，需要网络）...
    powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex" 2>&1
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    where uv >nul 2>&1
    if errorlevel 1 (
        echo  [错误] uv 安装失败！
        echo.
        echo  可能原因：
        echo  A. 网络被防火墙拦截（公司网络常见）
        echo     → 切换到手机热点重试
        echo  B. PowerShell 执行策略限制
        echo     → 右键"诊断_打不开请运行我.bat"→以管理员身份运行
        set /a FAIL+=1
        goto :check_network
    )
)
uv --version
echo  uv OK
set /a PASS+=1

:: ════════════════════════════════════════
:: [5/7] 网络连通性检查
:: ════════════════════════════════════════
:check_network
echo.
echo [5/7] 检查网络连通性...
powershell -Command "try { $r = Invoke-WebRequest -Uri 'https://pypi.org' -TimeoutSec 8 -UseBasicParsing; Write-Host 'PyPI 可达 OK' } catch { Write-Host '[警告] PyPI 不可达：' $_.Exception.Message }" 2>&1
powershell -Command "try { $r = Invoke-WebRequest -Uri 'https://astral.sh' -TimeoutSec 8 -UseBasicParsing; Write-Host 'astral.sh 可达 OK' } catch { Write-Host '[警告] astral.sh 不可达（uv下载源）：' $_.Exception.Message }" 2>&1
echo  如果以上显示"不可达"，请切换网络（手机热点）后重试

:: ════════════════════════════════════════
:: [6/7] .env 和 API Key 检查
:: ════════════════════════════════════════
echo.
echo [6/7] 检查 API Key 配置...
if not exist "%BACKEND%\.env" (
    echo  [错误] 未找到 %BACKEND%\.env
    echo  请运行"填写API密钥_双击我.bat"配置密钥
    set /a FAIL+=1
) else (
    echo  .env 文件存在 OK
    set SILI_FILLED=0
    for /f "tokens=2 delims==" %%v in ('findstr /I "SILICONFLOW_API_KEY" "%BACKEND%\.env"') do (
        set V=%%v
        set V=!V: =!
        if not "!V!"=="" set SILI_FILLED=1
    )
    if !SILI_FILLED!==1 (
        echo  SILICONFLOW_API_KEY: 已填写 OK
        set /a PASS+=1
    ) else (
        echo  [警告] SILICONFLOW_API_KEY 未填写（AI功能将不可用）
        echo  请运行"填写API密钥_双击我.bat"
    )
)

:: ════════════════════════════════════════
:: [7/7] 端口和依赖检查
:: ════════════════════════════════════════
echo.
echo [7/7] 检查端口和依赖...
netstat -ano 2>nul | findstr ":8000 " | findstr LISTENING >nul 2>&1
if not errorlevel 1 (
    echo  [注意] 端口8000已被占用，将自动释放...
    for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING 2^>nul') do (
        taskkill /PID %%p /F >nul 2>&1
    )
    echo  端口已释放 OK
) else (
    echo  端口 8000 可用 OK
    set /a PASS+=1
)

if exist "%BACKEND%\.venv" (
    echo  依赖目录已存在（无需重新下载）OK
    set /a PASS+=1
) else (
    echo  [注意] 首次运行，需要下载依赖（约250MB，5-15分钟）
    echo  请确保网络畅通
)

:: ════════════════════════════════════════
:: 汇总
:: ════════════════════════════════════════
echo.
echo  ════════════════════════════════════════
echo   诊断汇总
echo  ════════════════════════════════════════
if %FAIL%==0 (
    echo  ✅ 所有检查通过！正在启动系统...
    echo.
    cd /d "%BACKEND%"
    start "" cmd /c "timeout /t 8 >nul && start http://localhost:8000"
    uv run uvicorn cangjie_fos.main:app --host 0.0.0.0 --port 8000
) else (
    echo  ❌ 发现 %FAIL% 个问题，请按上方提示逐一解决。
    echo.
    echo  解决后重新运行此诊断，或截图发给王波。
)

echo.
pause
