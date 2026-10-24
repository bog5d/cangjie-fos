"""Tests for /api/pitch/jobs pagination (?page=1&size=N)."""
from __future__ import annotations

import time as _time

import pytest
from fastapi.testclient import TestClient

import cangjie_fos.services.pitch_job_db as _db_module
import cangjie_fos.services.pitch_job_store as _store_module
from cangjie_fos.main import app

client = TestClient(app)

TENANT = "paginate-tenant"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    db_file = tmp_path / "pitch_jobs.sqlite"
    monkeypatch.setattr(_db_module, "_db_path", lambda: str(db_file))
    # Reset in-memory store
    monkeypatch.setattr(_store_module, "_jobs", {})
    yield


def _seed_db_jobs(n: int) -> None:
    """Seed n jobs directly into SQLite (bypassing in-memory store)."""
    from cangjie_fos.services.pitch_job_db import _connect

    conn = _connect()
    for i in range(n):
        conn.execute(
            "INSERT INTO pitch_jobs (job_id, tenant_id, status, created_at) VALUES (?, ?, 'completed', ?)",
            (f"job-pg-{i:03d}", TENANT, _time.time() - i),
        )
    conn.commit()
    conn.close()


def test_default_page_returns_results():
    _seed_db_jobs(5)
    resp = client.get(f"/api/pitch/jobs?tenant_id={TENANT}&page=2&size=3")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2  # 5 total, page 2 of size 3 → 2 remaining


def test_page2_returns_different_results():
    """page=2 and page=3 must not share any job_ids (both use SQLite OFFSET)."""
    _seed_db_jobs(6)
    resp1 = client.get(f"/api/pitch/jobs?tenant_id={TENANT}&page=2&size=2")
    resp2 = client.get(f"/api/pitch/jobs?tenant_id={TENANT}&page=3&size=2")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    ids1 = {j["job_id"] for j in resp1.json()}
    ids2 = {j["job_id"] for j in resp2.json()}
    assert len(ids1) > 0, "page=2 must have results"
    assert len(ids2) > 0, "page=3 must have results"
    assert ids1.isdisjoint(ids2), "Pages must not overlap"


def test_page_beyond_data_returns_empty():
    _seed_db_jobs(3)
    resp = client.get(f"/api/pitch/jobs?tenant_id={TENANT}&page=99&size=10")
    assert resp.status_code == 200
    assert resp.json() == []


def test_backward_compat_limit_still_works():
    _seed_db_jobs(5)
    resp = client.get(f"/api/pitch/jobs?tenant_id={TENANT}&limit=2")
    assert resp.status_code == 200
    assert len(resp.json()) <= 2
