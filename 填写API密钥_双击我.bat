@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title 仓颉 FOS — 填写 API 密钥

set ROOT=%~dp0
set ENVFILE=%ROOT%backend\.env

echo.
echo  ========================================
echo   仓颉 FOS — API 密钥配置向导
echo  ========================================
echo.

:: ── 确保 .env 文件存在 ──
if not exist "%ENVFILE%" (
    echo  正在创建配置文件...
    (
        echo # 仓颉 FOS — API Key 配置
        echo SILICONFLOW_API_KEY=
        echo DEEPSEEK_API_KEY=
        echo DASHSCOPE_API_KEY=
        echo KIMI_API_KEY=
    ) > "%ENVFILE%"
)

echo  即将用记事本打开密钥配置文件。
echo.
echo  填写说明：
echo  ─────────────────────────────────────────
echo   SILICONFLOW_API_KEY=  ← 必填，主力 AI（向王波索取）
echo   DEEPSEEK_API_KEY=     ← 必填（向王波索取）
echo   DASHSCOPE_API_KEY=    ← 可选，语音转写功能需要
echo   KIMI_API_KEY=         ← 可选
echo  ─────────────────────────────────────────
echo.
echo  在"="后面直接粘贴 Key，不要加引号，不要加空格。
echo  保存后关闭记事本，回到此窗口按任意键验证。
echo.
pause

:: ── 用记事本打开 ──
start /wait notepad.exe "%ENVFILE%"

echo.
echo  正在验证密钥格式...
echo.

:: ── 校验：SILICONFLOW_API_KEY 是否填写 ──
set SILI_OK=0
for /f "tokens=2 delims==" %%v in ('findstr /I "SILICONFLOW_API_KEY" "%ENVFILE%"') do (
    set VAL=%%v
    set VAL=!VAL: =!
    if not "!VAL!"=="" set SILI_OK=1
)

:: ── 校验：DEEPSEEK_API_KEY 是否填写 ──
set DEEP_OK=0
for /f "tokens=2 delims==" %%v in ('findstr /I "DEEPSEEK_API_KEY" "%ENVFILE%"') do (
    set VAL=%%v
    set VAL=!VAL: =!
    if not "!VAL!"=="" set DEEP_OK=1
)

:: ── 输出结果 ──
if %SILI_OK%==1 (
    echo  SILICONFLOW_API_KEY ... ✅ 已填写
) else (
    echo  SILICONFLOW_API_KEY ... ❌ 未填写（必填）
)

if %DEEP_OK%==1 (
    echo  DEEPSEEK_API_KEY    ... ✅ 已填写
) else (
    echo  DEEPSEEK_API_KEY    ... ❌ 未填写（必填）
)

echo.

if %SILI_OK%==0 (
    echo  ⚠️  必填 Key 未完成，AI 功能将无法使用。
    echo  请重新填写，或向王波确认 Key 是否正确。
    echo.
    pause
    goto :eof
)

echo  ✅ 密钥配置完成！
echo.
echo  现在可以双击"一键启动_Python版.bat"启动系统了。
echo.
pause
