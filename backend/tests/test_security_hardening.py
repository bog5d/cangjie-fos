"""安全加固（K）测试：密码哈希 opt-in(#03) + GitHub push 冲突重试(#06)。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


# ── #03 密码哈希（向后兼容明文）────────────────────────────────────────────────

def test_hash_password_roundtrip():
    from cangjie_fos.api.routes.auth import hash_password, _password_matches
    h = hash_password("超级密码123")
    assert h.startswith("pbkdf2_sha256$")
    assert _password_matches(h, "超级密码123") is True
    assert _password_matches(h, "错密码") is False


def test_plaintext_still_works():
    """向后兼容：明文密码继续可用（不锁死存量 .env）。"""
    from cangjie_fos.api.routes.auth import _password_matches
    assert _password_matches("123456", "123456") is True
    assert _password_matches("123456", "wrong") is False


def test_malformed_hash_rejected():
    from cangjie_fos.api.routes.auth import _password_matches
    assert _password_matches("pbkdf2_sha256$坏数据", "任何") is False


def test_login_with_hashed_password(monkeypatch):
    from cangjie_fos.api.routes.auth import hash_password
    from cangjie_fos.main import create_app

    h = hash_password("mypw")
    monkeypatch.setenv("FOS_ACCOUNTS", f"zt001:{h}:zt")
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        assert c.post("/api/auth/login", json={"username": "zt001", "password": "mypw"}).status_code == 200
        assert c.post("/api/auth/login", json={"username": "zt001", "password": "no"}).status_code == 401


# ── #06 GitHub PUT 冲突重试 ───────────────────────────────────────────────────

def test_put_file_retries_on_conflict(monkeypatch):
    import urllib.error
    from cangjie_fos.services import github_sync as gs

    monkeypatch.setattr(gs, "_cfg", lambda: {"repo": "x/y", "token": "t", "branch": "main"})
    monkeypatch.setattr(gs, "_headers", lambda: {})
    shas = iter(["sha1", "sha2"])
    monkeypatch.setattr(gs, "_get_file_sha", lambda path: next(shas, "sha2"))

    calls = {"n": 0}

    class _Resp:
        def getcode(self):
            return 201
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=30):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError("url", 409, "conflict", {}, None)
        return _Resp()

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    ok = gs._put_file("analytics/x.json", {"a": 1}, "msg")
    assert ok is True
    assert calls["n"] == 2  # 第一次409、重取SHA后第二次成功


def test_put_file_gives_up_after_retries(monkeypatch):
    import urllib.error
    from cangjie_fos.services import github_sync as gs

    monkeypatch.setattr(gs, "_cfg", lambda: {"repo": "x/y", "token": "t", "branch": "main"})
    monkeypatch.setattr(gs, "_headers", lambda: {})
    monkeypatch.setattr(gs, "_get_file_sha", lambda path: "sha")
    monkeypatch.setattr("time.sleep", lambda *_: None)  # 别真睡

    def always_fail(req, timeout=30):
        raise urllib.error.URLError("network down")

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", always_fail)
    assert gs._put_file("analytics/x.json", {"a": 1}, "msg") is False
