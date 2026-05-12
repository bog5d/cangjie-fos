"""pytest 全局夹具。

包含 Playwright 浏览器 E2E 测试所需的 live_server fixture。
普通的 API 集成测试不依赖这里（它们用自己的 TestClient）。

使用方式：
  # 普通测试套件（无需启动服务）
  uv run --extra dev pytest tests/ -q

  # 浏览器烟雾测试（需要先在另一个终端启动服务）
  uv run uvicorn cangjie_fos.main:app --port 8000
  uv run --extra dev pytest tests/test_ui_smoke.py -v
"""
from __future__ import annotations

import socket
import pytest


@pytest.fixture(scope="session")
def fos_server_url() -> str:
    """
    返回正在运行的 FOS 服务地址（默认 http://127.0.0.1:8000）。
    如果服务未运行，直接 skip（不影响普通测试套件）。

    浏览器测试运行前需手动启动服务：
      uv run uvicorn cangjie_fos.main:app --port 8000
    """
    host, port = "127.0.0.1", 8000
    try:
        with socket.create_connection((host, port), timeout=1):
            return f"http://{host}:{port}"
    except OSError:
        pytest.skip(
            f"FOS 服务未运行（{host}:{port}）。"
            "浏览器烟雾测试需要先启动服务：uv run uvicorn cangjie_fos.main:app --port 8000"
        )
