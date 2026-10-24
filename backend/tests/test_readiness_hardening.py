"""Readiness、API Key 中间件、队列。"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from cangjie_fos.main import app

CLIENT = TestClient(app)


def test_ready_200_includes_probes() -> None:
    r = CLIENT.get("/api/v1/ready")
    assert r.status_code == 200
    b = r.json()
    assert "ok" in b
    assert "pitch_coach_ok" in b
    assert "issues" in b
    assert "X-Request-ID" in r.headers


def test_request_id_header() -> None:
    r = CLIENT.get("/health", headers={"X-Request-ID": "test-rid-1"})
    assert r.headers.get("X-Request-ID") == "test-rid-1"


def test_ready_public_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CANGJIE_API_KEY", "secret-x")
    r = CLIENT.get("/api/v1/ready")
    assert r.status_code == 200
    monkeypatch.delenv("CANGJIE_API_KEY", raising=False)


def test_api_key_enforced_on_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CANGJIE_API_KEY", "only-for-test")
    r = CLIENT.get("/api/v1/assets")
    assert r.status_code == 401
    r2 = CLIENT.get("/api/v1/assets", headers={"X-API-Key": "only-for-test"})
    assert r2.status_code == 200
    monkeypatch.delenv("CANGJIE_API_KEY", raising=False)


def test_queue_reserve_and_release() -> None:
    from cangjie_fos.core.job_semaphore import queue_snapshot, release_job_slot, try_reserve_jobs

    s0 = queue_snapshot()["in_use"]
    assert try_reserve_jobs(1) is True
    assert queue_snapshot()["in_use"] == s0 + 1
    release_job_slot()
    assert queue_snapshot()["in_use"] == s0
