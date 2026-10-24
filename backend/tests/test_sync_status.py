"""Step 1：GitHub 同步状态稳定性测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cangjie_fos.main import app


def _token(monkeypatch) -> str:
    """获取测试用 session token。"""
    monkeypatch.setenv("FOS_ACCOUNTS", "tester:pass123:ttest")
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": "tester", "password": "pass123"})
    assert r.status_code == 200
    return r.json()["token"]


def test_sync_status_not_configured(monkeypatch):
    """未配置 GitHub Token 时，status 端点仍返回 200 含 configured=False。"""
    monkeypatch.delenv("COACH_DATA_GITHUB_TOKEN", raising=False)
    c = TestClient(app)
    r = c.get("/api/sync/status")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False
    assert "last_synced_at" in body
    assert "is_syncing" in body


def test_sync_state_initial_values():
    """初始状态：last_synced_at=None, is_syncing=False。"""
    import cangjie_fos.services.github_sync as gs
    gs._reset_sync_state()
    state = gs.get_sync_status()
    assert state["is_syncing"] is False
    assert state["last_synced_at"] is None
    assert state["last_error"] is None


def test_pull_updates_sync_state(monkeypatch, tmp_path):
    """pull_latest 完成后，last_synced_at 应有值，is_syncing=False。"""
    import cangjie_fos.services.github_sync as gs

    monkeypatch.setenv("COACH_DATA_GITHUB_TOKEN", "fake-token")
    monkeypatch.setattr(gs, "_list_folder_recursive", lambda path, repo=None: [])
    monkeypatch.setattr(gs, "is_configured", lambda: True)

    gs._reset_sync_state()
    gs.pull_latest()

    state = gs.get_sync_status()
    assert state["is_syncing"] is False
    assert state["last_synced_at"] is not None
    assert state["last_error"] is None


def test_pull_failure_records_error(monkeypatch):
    """pull_latest 内部抛异常时，last_error 应有内容，is_syncing=False。"""
    import cangjie_fos.services.github_sync as gs

    monkeypatch.setattr(gs, "is_configured", lambda: True)
    monkeypatch.setattr(gs, "_pull_latest_inner", lambda: (_ for _ in ()).throw(RuntimeError("simulated network failure")))

    gs._reset_sync_state()
    gs.pull_latest()

    state = gs.get_sync_status()
    assert state["is_syncing"] is False
    assert state["last_error"] is not None
    assert "simulated" in state["last_error"]


def test_sync_pull_endpoint_without_github(monkeypatch):
    """未配置 GitHub 时，POST /api/sync/pull 返回 ok=False 而非 500。"""
    monkeypatch.delenv("COACH_DATA_GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("FOS_ACCOUNTS", "tester:pass123:ttest")
    c = TestClient(app)
    login = c.post("/api/auth/login", json={"username": "tester", "password": "pass123"})
    token = login.json().get("token", "")
    r = c.post("/api/sync/pull", headers={"X-FOS-Token": token})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
