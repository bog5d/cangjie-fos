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
        echo DEEPSEEK_API_KEY=
        echo DASHSCOPE_API_KEY=
        echo KIMI_API_KEY=
        echo.
        echo # 已弃用（2026-05 起不再使用硅基流动，保留此行可忽略）
        echo # SILICONFLOW_API_KEY=
        echo.
        echo # 登录账号（格式：账号:密码:tenant_id，多账号用逗号隔开）
        echo # tenant_id 决定 GitHub 同步目录，强烈建议填写
        echo # 示例：FOS_ACCOUNTS=zt001:123456:zt001,gk001:password:gk001
        echo # 留空则任意用户名密码均可直接进入（仅限王波本地单人调试使用）
        echo FOS_ACCOUNTS=
    ) > "%ENVFILE%"
)

echo  即将用记事本打开密钥配置文件。
echo.
echo  填写说明：
echo  ─────────────────────────────────────────
echo   DEEPSEEK_API_KEY=     ← 必填，LLM 评估引擎（联系王波获取）
echo   DASHSCOPE_API_KEY=    ← 必填，阿里云百炼 ASR 语音转写（联系王波获取）
echo   KIMI_API_KEY=         ← 可选
echo.
echo   SILICONFLOW_API_KEY   ← 已弃用，无需填写（2026-05 停用）
echo.
echo   FOS_ACCOUNTS=         ← 强烈建议填写，用于多人使用时区分账号和数据
echo     格式：账号:密码:tenant_id（多账号用逗号隔开）
echo     示例（泽天机器）：FOS_ACCOUNTS=zt001:123456:zt001
echo     tenant_id 决定 GitHub 数据同步目录（analytics/tenant_id/）
echo     留空仅限王波本地单人调试使用，同事机器请务必填写！
echo  ─────────────────────────────────────────
echo.
echo  在"="后面直接填写内容，不要加引号，不要加空格。
echo  保存后关闭记事本，回到此窗口按任意键验证。
echo.
pause

:: ── 用记事本打开 ──
start /wait notepad.exe "%ENVFILE%"

echo.
echo  正在验证密钥格式...
echo.

:: ── 校验：DEEPSEEK_API_KEY 是否填写 ──
set DEEP_OK=0
for /f "tokens=2 delims==" %%v in ('findstr /I "^DEEPSEEK_API_KEY" "%ENVFILE%"') do (
    set VAL=%%v
    set VAL=!VAL: =!
    if not "!VAL!"=="" set DEEP_OK=1
)

:: ── 校验：DASHSCOPE_API_KEY 是否填写 ──
set DASH_OK=0
for /f "tokens=2 delims==" %%v in ('findstr /I "^DASHSCOPE_API_KEY" "%ENVFILE%"') do (
    set VAL=%%v
    set VAL=!VAL: =!
    if not "!VAL!"=="" set DASH_OK=1
)

:: ── 输出结果 ──
if %DEEP_OK%==1 (
    echo  DEEPSEEK_API_KEY    ... ? 已填写
) else (
    echo  DEEPSEEK_API_KEY    ... ? 未填写（必填）
)

if %DASH_OK%==1 (
    echo  DASHSCOPE_API_KEY   ... ? 已填写
) else (
    echo  DASHSCOPE_API_KEY   ... ? 未填写（必填）
)

echo.

if %DEEP_OK%==0 (
    echo  ??  必填 Key 未完成（DEEPSEEK_API_KEY），AI 评估功能将无法使用。
    echo  请重新填写，或向王波确认 Key 是否正确。
    echo.
    pause
    goto :eof
)

if %DASH_OK%==0 (
    echo  ??  必填 Key 未完成（DASHSCOPE_API_KEY），语音转写功能将无法使用。
    echo  请重新填写，或向王波确认 Key 是否正确。
    echo.
    pause
    goto :eof
)

:: ── 校验：FOS_ACCOUNTS 是否填写 ──
set ACCT_OK=0
for /f "tokens=2 delims==" %%v in ('findstr /I "^FOS_ACCOUNTS" "%ENVFILE%"') do (
    set VAL=%%v
    set VAL=!VAL: =!
    if not "!VAL!"=="" set ACCT_OK=1
)

if %ACCT_OK%==1 (
    echo  FOS_ACCOUNTS        ... ? 已设置（登录需验证账号密码，GitHub 按 tenant_id 隔离数据）
) else (
    echo  FOS_ACCOUNTS        ... ??  未设置！
    echo.
    echo  同事机器使用时请务必填写 FOS_ACCOUNTS，否则：
    echo    · 任意账号密码均可登录（无安全性）
    echo    · 所有数据归入 default 目录（数据混用）
    echo.
    echo  示例：FOS_ACCOUNTS=zt001:123456:zt001
    echo.
)

echo.
echo  ? 密钥配置完成！
echo.
echo  现在可以双击"点击开始-仓颉FOS.bat"启动系统了。
echo.
echo  提示：也可以在系统界面右上角点击 ?? 齿轮图标，在线填写并测试 API Key。
echo.
pause

