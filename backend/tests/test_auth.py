"""登录认证模块测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from cangjie_fos.main import create_app
    return TestClient(create_app(), raise_server_exceptions=False)


# ─── accounts-configured ──────────────────────────────────────────────────────

def test_accounts_configured_true_when_no_env(client, monkeypatch):
    """未配置 FOS_ACCOUNTS 时仍返回 configured=True（内置默认账号生效）。"""
    monkeypatch.delenv("FOS_ACCOUNTS", raising=False)
    r = client.get("/api/auth/accounts-configured")
    assert r.status_code == 200
    assert r.json()["configured"] is True


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


def test_login_builtin_accounts_when_no_env(client, monkeypatch):
    """未配置 FOS_ACCOUNTS 时，内置默认账号 zt001/gk001 均可登录。"""
    monkeypatch.delenv("FOS_ACCOUNTS", raising=False)
    r_zt = client.post("/api/auth/login", json={"username": "zt001", "password": "123456"})
    r_gk = client.post("/api/auth/login", json={"username": "gk001", "password": "123456"})
    assert r_zt.status_code == 200
    assert r_zt.json()["tenant_id"] == "zt"
    assert r_gk.status_code == 200
    assert r_gk.json()["tenant_id"] == "gk"


def test_env_fully_replaces_builtin_when_set(client, monkeypatch):
    """FOS_ACCOUNTS 设置后完全替换内置账号，只列出的账号可用。"""
    monkeypatch.setenv("FOS_ACCOUNTS", "zt001:123456:zt,gk001:123456:gk")
    r_zt = client.post("/api/auth/login", json={"username": "zt001", "password": "123456"})
    r_gk = client.post("/api/auth/login", json={"username": "gk001", "password": "123456"})
    assert r_zt.status_code == 200, "zt001 应能登录"
    assert r_gk.status_code == 200, "gk001 应能登录"
    assert r_gk.json()["tenant_id"] == "gk"


def test_env_can_override_builtin_password(client, monkeypatch):
    """.env 设置后只有该账号可用；同名账号使用 .env 密码。"""
    monkeypatch.setenv("FOS_ACCOUNTS", "gk001:newpass999:gk")
    r_old = client.post("/api/auth/login", json={"username": "gk001", "password": "123456"})
    r_new = client.post("/api/auth/login", json={"username": "gk001", "password": "newpass999"})
    assert r_old.status_code == 401, "旧密码应失效"
    assert r_new.status_code == 200, "新密码应生效"
    # FOS_ACCOUNTS 未列 zt001，所以 zt001 不可用
    r_zt = client.post("/api/auth/login", json={"username": "zt001", "password": "123456"})
    assert r_zt.status_code == 401


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
