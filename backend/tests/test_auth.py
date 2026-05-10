"""登录认证模块测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from cangjie_fos.main import create_app
    return TestClient(create_app(), raise_server_exceptions=False)


# ─── accounts-configured ──────────────────────────────────────────────────────

def test_accounts_configured_false_when_no_env(client, monkeypatch):
    monkeypatch.delenv("FOS_ACCOUNTS", raising=False)
    r = client.get("/api/auth/accounts-configured")
    assert r.status_code == 200
    assert r.json()["configured"] is False


def test_accounts_configured_true_when_env_set(client, monkeypatch):
    monkeypatch.setenv("FOS_ACCOUNTS", "zt001:123456:zt")
    r = client.get("/api/auth/accounts-configured")
    assert r.status_code == 200
    assert r.json()["configured"] is True


# ─── login ────────────────────────────────────────────────────────────────────

def test_login_success(client, monkeypatch):
    monkeypatch.setenv("FOS_ACCOUNTS", "zt001:123456:zt")
    r = client.post("/api/auth/login", json={"username": "zt001", "password": "123456"})
    assert r.status_code == 200
    data = r.json()
    assert data["token"]
    assert data["username"] == "zt001"
    assert data["tenant_id"] == "zt"


def test_login_wrong_password(client, monkeypatch):
    monkeypatch.setenv("FOS_ACCOUNTS", "zt001:123456:zt")
    r = client.post("/api/auth/login", json={"username": "zt001", "password": "wrong"})
    assert r.status_code == 401


def test_login_unknown_user(client, monkeypatch):
    monkeypatch.setenv("FOS_ACCOUNTS", "zt001:123456:zt")
    r = client.post("/api/auth/login", json={"username": "nobody", "password": "123456"})
    assert r.status_code == 401


def test_login_dev_mode_no_accounts(client, monkeypatch):
    """无账号配置时，开发模式放行任意登录。"""
    monkeypatch.delenv("FOS_ACCOUNTS", raising=False)
    r = client.post("/api/auth/login", json={"username": "dev", "password": "anything"})
    assert r.status_code == 200
    assert r.json()["tenant_id"] == "default"


# ─── me ───────────────────────────────────────────────────────────────────────

def test_me_valid_token(client, monkeypatch):
    monkeypatch.setenv("FOS_ACCOUNTS", "zt001:123456:zt")
    login_r = client.post("/api/auth/login", json={"username": "zt001", "password": "123456"})
    token = login_r.json()["token"]

    r = client.get("/api/auth/me", headers={"X-FOS-Token": token})
    assert r.status_code == 200
    assert r.json()["username"] == "zt001"
    assert r.json()["tenant_id"] == "zt"


def test_me_no_token(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_me_invalid_token(client):
    r = client.get("/api/auth/me", headers={"X-FOS-Token": "fake-token-xyz"})
    assert r.status_code == 401


# ─── logout ───────────────────────────────────────────────────────────────────

def test_logout_invalidates_token(client, monkeypatch):
    monkeypatch.setenv("FOS_ACCOUNTS", "zt001:123456:zt")
    login_r = client.post("/api/auth/login", json={"username": "zt001", "password": "123456"})
    token = login_r.json()["token"]

    # 登出
    client.post("/api/auth/logout", headers={"X-FOS-Token": token})

    # token 失效
    r = client.get("/api/auth/me", headers={"X-FOS-Token": token})
    assert r.status_code == 401


# ─── 多账号 ────────────────────────────────────────────────────────────────────

def test_multiple_accounts(client, monkeypatch):
    monkeypatch.setenv("FOS_ACCOUNTS", "zt001:123456:zt,gk001:654321:gk")
    r1 = client.post("/api/auth/login", json={"username": "zt001", "password": "123456"})
    r2 = client.post("/api/auth/login", json={"username": "gk001", "password": "654321"})
    assert r1.json()["tenant_id"] == "zt"
    assert r2.json()["tenant_id"] == "gk"
