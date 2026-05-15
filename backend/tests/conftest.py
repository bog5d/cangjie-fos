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

    例外：E2E 测试（wizard/pipeline/retry-eval）使用 module/class 级
    fixture 预先写入 DB 数据，scope 不匹配会导致读取临时空 DB——
    对这类测试跳过隔离，让它们直接使用真实 DB 路径。

    对不使用 DB 的测试无副作用（只有首次 _connect() 时才创建文件）。
    """
    # E2E 测试在 module/class fixture 中预写数据到真实 DB 路径，
    # function-scope DB 隔离会导致读不到数据 → 跳过 monkeypatch
    _SKIP_DB_ISOLATION_MODULES = (
        "test_wizard_pipeline_e2e",
        "test_pipeline_e2e",
        "test_p0_retry_eval",
        "test_follow_ups_api",
        # test_wiki_display 已有自己的 isolated_db fixture 做 DB 隔离，
        # 若 autouse 再做一次 monkeypatch 会导致双重 patch 互相干扰（不同 tmp_path）
        "test_wiki_display",
    )
    module_path = str(request.node.path)
    if any(name in module_path for name in _SKIP_DB_ISOLATION_MODULES):
        return  # yield nothing — E2E tests use real DB

    import cangjie_fos.services.pitch_job_db as db_module  # noqa: PLC0415

    db_file = tmp_path / "test_fos.db"
    monkeypatch.setattr(db_module, "_db_path", lambda: str(db_file))
