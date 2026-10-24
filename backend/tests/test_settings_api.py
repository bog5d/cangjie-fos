"""API Key 设置端点测试（/api/v1/settings/api-keys）。"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """创建测试客户端，使用临时目录模拟 backend 根目录。"""
    # 创建一个虚假的 .env 文件（空）
    env_file = tmp_path / ".env"
    env_file.write_text("DEEPSEEK_API_KEY=\nDASHSCOPE_API_KEY=\nKIMI_API_KEY=\n", encoding="utf-8")

    # 让 get_backend_root() 返回 tmp_path
    with patch("cangjie_fos.api.routes.settings.get_backend_root", return_value=tmp_path):
        from cangjie_fos.main import create_app
        yield TestClient(create_app(), raise_server_exceptions=False)


# ─── GET /api/v1/settings/api-keys ───────────────────────────────────────────

def test_get_api_keys_all_empty(client, monkeypatch):
    """未配置任何 Key 时，三个都返回 False。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    r = client.get("/api/v1/settings/api-keys")
    assert r.status_code == 200
    data = r.json()
    assert data["DEEPSEEK_API_KEY"] is False
    assert data["DASHSCOPE_API_KEY"] is False
    assert data["KIMI_API_KEY"] is False


def test_get_api_keys_partial(client, monkeypatch):
    """配置了 DeepSeek 但未配置 DashScope 时，返回正确状态。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-123456")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    r = client.get("/api/v1/settings/api-keys")
    assert r.status_code == 200
    data = r.json()
    assert data["DEEPSEEK_API_KEY"] is True
    assert data["DASHSCOPE_API_KEY"] is False


def test_get_api_keys_all_configured(client, monkeypatch):
    """三个 Key 都配置时，都返回 True。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-dashscope")
    monkeypatch.setenv("KIMI_API_KEY", "sk-kimi")
    r = client.get("/api/v1/settings/api-keys")
    assert r.status_code == 200
    data = r.json()
    assert data["DEEPSEEK_API_KEY"] is True
    assert data["DASHSCOPE_API_KEY"] is True
    assert data["KIMI_API_KEY"] is True


# ─── POST /api/v1/settings/api-keys ──────────────────────────────────────────

def test_set_api_keys_updates_env(client, monkeypatch, tmp_path):
    """设置 Key 后，os.environ 立即更新，.env 文件写入正确内容。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with patch("cangjie_fos.api.routes.settings.get_backend_root", return_value=tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("DEEPSEEK_API_KEY=\n", encoding="utf-8")

        r = client.post("/api/v1/settings/api-keys", json={"keys": {"DEEPSEEK_API_KEY": "sk-new-key"}})
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # os.environ 应已更新
        assert os.environ.get("DEEPSEEK_API_KEY") == "sk-new-key"

        # .env 文件应已更新
        content = env_file.read_text(encoding="utf-8")
        assert "DEEPSEEK_API_KEY=sk-new-key" in content


def test_set_api_keys_unknown_key_rejected(client):
    """未知 Key 名称应返回 400。"""
    r = client.post("/api/v1/settings/api-keys", json={"keys": {"UNKNOWN_KEY": "value"}})
    assert r.status_code == 400


def test_set_api_keys_strips_whitespace(client, monkeypatch, tmp_path):
    """Key 值中的首尾空格应被去除。"""
    with patch("cangjie_fos.api.routes.settings.get_backend_root", return_value=tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("DEEPSEEK_API_KEY=\n", encoding="utf-8")

        client.post("/api/v1/settings/api-keys", json={"keys": {"DEEPSEEK_API_KEY": "  sk-trimmed  "}})
        assert os.environ.get("DEEPSEEK_API_KEY") == "sk-trimmed"


# ─── POST /api/v1/settings/api-keys/test-deepseek ────────────────────────────

def test_test_deepseek_no_key(client, monkeypatch):
    """未配置 DeepSeek Key 时，返回 ok=False 并说明原因。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    r = client.post("/api/v1/settings/api-keys/test-deepseek")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert "未填写" in data["message"]


def test_test_deepseek_valid_key(client, monkeypatch):
    """DeepSeek Key 有效时（mock HTTP 200），返回 ok=True。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-valid")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("cangjie_fos.api.routes.settings.httpx.post", return_value=mock_resp):
        r = client.post("/api/v1/settings/api-keys/test-deepseek")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "正常" in data["message"]


def test_test_deepseek_invalid_key_401(client, monkeypatch):
    """DeepSeek Key 无效时（mock HTTP 401），返回 ok=False 并提示 401。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-invalid")
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    with patch("cangjie_fos.api.routes.settings.httpx.post", return_value=mock_resp):
        r = client.post("/api/v1/settings/api-keys/test-deepseek")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert "401" in data["message"]


# ─── POST /api/v1/settings/api-keys/test-dashscope ───────────────────────────

def test_test_dashscope_no_key(client, monkeypatch):
    """未配置 DashScope Key 时，返回 ok=False。"""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    r = client.post("/api/v1/settings/api-keys/test-dashscope")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert "未填写" in data["message"]


def test_test_dashscope_invalid_key_401(client, monkeypatch):
    """DashScope Key 无效（mock 401），返回 ok=False。"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-invalid-dash")
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    with patch("cangjie_fos.api.routes.settings.httpx.get", return_value=mock_resp):
        r = client.post("/api/v1/settings/api-keys/test-dashscope")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert "401" in data["message"]


def test_test_dashscope_valid_key_non_401(client, monkeypatch):
    """DashScope Key 有效（非 401 响应），返回 ok=True。"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-valid-dash")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("cangjie_fos.api.routes.settings.httpx.get", return_value=mock_resp):
        r = client.post("/api/v1/settings/api-keys/test-dashscope")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "正常" in data["message"]


# ─── POST /api/v1/settings/api-keys/test-github ──────────────────────────────

def _gh_resp(status_code, permissions=None):
    """构造一个假的 GitHub repo 响应。"""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = {"permissions": permissions} if permissions is not None else {}
    return mock_resp


def test_test_github_no_token(client, monkeypatch):
    """未配置 Token 时，返回 ok=False。"""
    monkeypatch.delenv("COACH_DATA_GITHUB_TOKEN", raising=False)
    r = client.post("/api/v1/settings/api-keys/test-github")
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert "尚未填写" in r.json()["message"]


def test_test_github_read_write_ok(client, monkeypatch):
    """令牌能读且有写权限（push=True）→ ok=True。"""
    monkeypatch.setenv("COACH_DATA_GITHUB_TOKEN", "github_pat_rw")
    resp = _gh_resp(200, {"pull": True, "push": True, "admin": False})
    with patch("cangjie_fos.api.routes.settings.httpx.get", return_value=resp):
        r = client.post("/api/v1/settings/api-keys/test-github")
    data = r.json()
    assert data["ok"] is True
    assert "读写权限齐全" in data["message"]


def test_test_github_read_only_rejected(client, monkeypatch):
    """令牌只读（push=False）→ ok=False，明确提示改成 Read and write。

    这是本次修复的核心：只读令牌以前会被误报为「✅ 正常」，一同步就失败。
    """
    monkeypatch.setenv("COACH_DATA_GITHUB_TOKEN", "github_pat_readonly")
    resp = _gh_resp(200, {"pull": True, "push": False, "admin": False})
    with patch("cangjie_fos.api.routes.settings.httpx.get", return_value=resp):
        r = client.post("/api/v1/settings/api-keys/test-github")
    data = r.json()
    assert data["ok"] is False
    assert "没有写权限" in data["message"]
    assert "Read and write" in data["message"]


def test_test_github_admin_counts_as_writable(client, monkeypatch):
    """admin 权限也视为可写（经典令牌 repo scope 常返回 admin=True）。"""
    monkeypatch.setenv("COACH_DATA_GITHUB_TOKEN", "ghp_classic")
    resp = _gh_resp(200, {"pull": True, "push": True, "admin": True})
    with patch("cangjie_fos.api.routes.settings.httpx.get", return_value=resp):
        r = client.post("/api/v1/settings/api-keys/test-github")
    assert r.json()["ok"] is True


def test_test_github_401(client, monkeypatch):
    """令牌无效 → 401。"""
    monkeypatch.setenv("COACH_DATA_GITHUB_TOKEN", "github_pat_bad")
    resp = _gh_resp(401)
    with patch("cangjie_fos.api.routes.settings.httpx.get", return_value=resp):
        r = client.post("/api/v1/settings/api-keys/test-github")
    data = r.json()
    assert data["ok"] is False
    assert "401" in data["message"]


def test_test_github_404_repo_not_selected(client, monkeypatch):
    """令牌没勾这个仓库 → 404，提示 Only select repositories。"""
    monkeypatch.setenv("COACH_DATA_GITHUB_TOKEN", "github_pat_norepo")
    resp = _gh_resp(404)
    with patch("cangjie_fos.api.routes.settings.httpx.get", return_value=resp):
        r = client.post("/api/v1/settings/api-keys/test-github")
    data = r.json()
    assert data["ok"] is False
    assert "404" in data["message"]
    assert "coach_data" in data["message"]
