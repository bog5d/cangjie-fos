@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
title 仓颉 FOS — API 密钥配置（可选）

set ROOT=%~dp0
set ENVFILE=%ROOT%backend\.env

echo.
echo  ========================================
echo   仓颉 FOS — API 密钥配置
echo  ========================================
echo.
echo  说明：系统已内置默认配置，开箱即可使用。
echo  如需使用自己的 API Key，在下方文件中填写即可覆盖默认值。
echo.

:: 确保 .env 文件存在（不存在则创建骨架）
if not exist "%ENVFILE%" (
    echo  正在创建配置文件...
    (
        echo # 仓颉 FOS 配置文件（留空 = 使用内置默认值）
        echo.
        echo # DeepSeek AI 分析（可选覆盖）
        echo DEEPSEEK_API_KEY=
        echo.
        echo # 阿里云百炼 ASR 语音转写（可选覆盖）
        echo DASHSCOPE_API_KEY=
        echo.
        echo # 登录账号（格式：账号:密码:tenant_id，多账号逗号分隔）
        echo # 每个 tenant_id 数据完全隔离，互不影响
        echo # 示例（两位同事）：FOS_ACCOUNTS=zt001:123456:zt,gk001:123456:gk
        echo FOS_ACCOUNTS=zt001:123456:zt,gk001:123456:gk
    ) > "%ENVFILE%"
    echo  配置文件已创建。
)

echo.
echo  ────────────────────────────────────────
echo   配置说明（所有项均为可选覆盖）：
echo  ────────────────────────────────────────
echo.
echo   DEEPSEEK_API_KEY=     AI 分析引擎（留空使用内置）
echo   DASHSCOPE_API_KEY=    阿里云语音转写（留空使用内置）
echo   FOS_ACCOUNTS=         登录账号（留空使用内置默认账号）
echo.
echo   格式：在 "=" 后直接填写内容，不要加引号
echo.
echo  ────────────────────────────────────────
echo.
echo  即将打开配置文件，按需填写后保存关闭即可。
echo  （直接关闭记事本 = 保持现有配置不变）
echo.
pause

:: 打开记事本编辑
start /wait notepad.exe "%ENVFILE%"

echo.
echo  配置完成！现在可以双击"安装并启动.ps1"运行系统。
echo.
pause
