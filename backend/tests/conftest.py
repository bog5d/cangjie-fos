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

import os
import socket
from pathlib import Path

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


@pytest.fixture(scope="session")
def fos_login_credentials() -> tuple[str, str]:
    """
    返回可用的登录凭据 (username, password)。

    优先读取 backend/.env 的 FOS_ACCOUNTS（格式：user:pass:tenant,...）。
    若未配置则返回 dev/dev（后端无账号限制时可用）。
    """
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("FOS_ACCOUNTS="):
                value = line[len("FOS_ACCOUNTS="):].strip()
                if value:
                    first_account = value.split(",")[0].strip()
                    parts = first_account.split(":")
                    if len(parts) >= 2:
                        return parts[0], parts[1]
    # 无账号配置 → dev mode，任意凭据
    return "dev", "dev"


@pytest.fixture(autouse=True)
def _isolate_db_per_test(request, tmp_path, monkeypatch):
    """每个测试获得独立的 SQLite 数据库实例（自动启用）。

    monkeypatch pitch_job_db._db_path 到临时目录，
    确保测试间完全隔离，杜绝并行测试时的全局状态泄漏。

    测试可通过 ``@pytest.mark.real_db`` 声明自己需要真实 DB：
    - 使用 module/class 级 fixture 预写数据的 E2E 测试
    - 已有自己的 isolated_db fixture 需要避免双重 monkeypatch

    对不使用 DB 的测试无副作用（只有首次 _connect() 时才创建文件）。
    """
    # ``@pytest.mark.real_db`` 标记的测试自行管理 DB，跳过隔离
    if request.node.get_closest_marker("real_db"):
        return

    import cangjie_fos.services.pitch_job_db as db_module  # noqa: PLC0415

    db_file = tmp_path / "test_fos.db"
    monkeypatch.setattr(db_module, "_db_path", lambda: str(db_file))
