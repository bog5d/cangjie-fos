$ErrorActionPreference = "Stop"
# 若尚未构建前端：先执行 .\build_frontend.ps1
Set-Location (Join-Path $PSScriptRoot "backend")
python -m pip install -e ".[dev]" -q
python -m uvicorn cangjie_fos.main:app --reload --host 127.0.0.1 --port 8000

