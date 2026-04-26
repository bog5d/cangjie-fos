#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
FRONTEND="$ROOT/frontend"
BACKEND="$ROOT/backend"

echo "[1/3] 检查依赖..."
command -v node >/dev/null 2>&1 || { echo "[错误] 未找到 node，请先安装 Node.js"; exit 1; }
command -v uv   >/dev/null 2>&1 || { echo "[错误] 未找到 uv，请先安装 uv"; exit 1; }

echo "[2/3] 构建前端..."
cd "$FRONTEND"
[[ ! -d node_modules ]] && npm install --silent
npm run build
echo "    前端构建完成 -> frontend/dist/"

echo "[3/3] 启动后端服务..."
cd "$BACKEND"

# 释放 8000 端口
lsof -ti:8000 | xargs kill -9 2>/dev/null || true

# 延迟打开浏览器
(sleep 2 && (open http://localhost:8000 2>/dev/null || xdg-open http://localhost:8000 2>/dev/null || true)) &

echo ""
echo " CangJie FOS 已启动"
echo " 访问: http://localhost:8000"
echo " 按 Ctrl+C 停止服务"
echo ""

uv run uvicorn cangjie_fos.main:app --host 0.0.0.0 --port 8000
