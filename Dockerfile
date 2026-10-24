# ── Stage 1: 构建前端 ─────────────────────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --silent
COPY frontend/ ./
RUN npm run build


# ── Stage 2: Python 运行时 ────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# 安装系统依赖（ffmpeg 供音频处理，curl 供健康检查）
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv（快速 Python 包管理器）
RUN pip install --no-cache-dir uv

WORKDIR /app

# 复制后端代码并安装依赖（non-editable，适合容器部署）
COPY backend/pyproject.toml backend/README.md* ./backend/
COPY backend/src ./backend/src
RUN cd backend && uv pip install --system --no-cache ".[dev]" 2>/dev/null || \
    uv pip install --system --no-cache "."

# 复制前端构建产物到 backend 可读取的位置
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# 数据目录（SQLite DB、音频文件、HTML 报告）挂载为 volume 保持持久化
RUN mkdir -p /app/backend/data/audio /app/backend/data/html_reports
VOLUME ["/app/backend/data"]

# 环境变量默认值
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend/src \
    ENABLE_WATCHDOG=false \
    PORT=8000

WORKDIR /app/backend

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "-m", "uvicorn", "cangjie_fos.main:app", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
