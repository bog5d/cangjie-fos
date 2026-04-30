"""资产活力雷达测试：DB层 + 服务层 + API端点。"""
from __future__ import annotations

import pathlib

import pytest
from starlette.testclient import TestClient

from cangjie_fos.main import app as global_app


# ---------------------------------------------------------------------------
# 辅助 fixture：隔离 SQLite
# ---------------------------------------------------------------------------

@pytest.fixture()
def isolated_db(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    db_file = tmp_path / "test_health.sqlite"
    monkeypatch.setattr(
        "cangjie_fos.services.pitch_job_db._db_path",
        lambda: str(db_file),
    )
    return tmp_path


# ---------------------------------------------------------------------------
# 1. DB：health snapshot 写入与读回
# ---------------------------------------------------------------------------

def test_db_health_snapshot_insert_and_list(isolated_db):
    from cangjie_fos.services.pitch_job_db import (
        db_health_snapshot_insert,
        db_health_snapshot_list,
        db_health_snapshot_latest,
    )

    db_health_snapshot_insert(score=75, total_files=20, indexed_files=20,
                               missing_cats=["财务报表"], scan_dir="/data")
    snaps = db_health_snapshot_list()
    assert len(snaps) == 1
    assert snaps[0]["score"] == 75
    assert snaps[0]["missing_cats"] == ["财务报表"]

    latest = db_health_snapshot_latest()
    assert latest is not None
    assert latest["score"] == 75


# ---------------------------------------------------------------------------
# 2. 服务层：compute_health 评分逻辑
# ---------------------------------------------------------------------------

def test_compute_health_empty_assets(isolated_db):
    from cangjie_fos.services.asset_health_service import compute_health

    result = compute_health([])
    assert result["score"] == 0
    assert len(result["missing_cats"]) > 0
    assert result["present_cats"] == []


def test_compute_health_with_assets(isolated_db):
    from cangjie_fos.services.asset_health_service import compute_health

    assets = [
        {"filename": "BP.pdf", "tags": ["BP"], "summary": "商业计划书"},
        {"filename": "audit.xlsx", "tags": ["审计"], "summary": "财务报表"},
        {"filename": "equity.docx", "tags": ["股权"], "summary": "股权结构"},
    ]
    result = compute_health(assets)
    assert result["score"] > 0
    assert "商业计划书" in result["present_cats"]


# ---------------------------------------------------------------------------
# 3. API：GET /api/v1/assets/health 无数据时返回 200 + has_data=False
# ---------------------------------------------------------------------------

def test_api_health_get_no_data(isolated_db, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "cangjie_fos.api.routes.assets.get_health_dashboard",
        lambda: {"score": 0, "total_files": 0, "missing_cats": [],
                 "present_cats": [], "trend": [], "has_data": False},
    )
    with TestClient(global_app) as client:
        resp = client.get("/api/v1/assets/health")
    assert resp.status_code == 200
    assert resp.json()["has_data"] is False


# ---------------------------------------------------------------------------
# 4. API：POST /api/v1/assets/health/snapshot 写入快照并返回 score
# ---------------------------------------------------------------------------

def test_api_health_snapshot_post(isolated_db, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "cangjie_fos.api.routes.assets.take_health_snapshot",
        lambda: {"id": 1, "score": 50, "total_files": 10,
                 "present_cats": ["商业计划书"], "missing_cats": ["财务报表"],
                 "scan_dir": "/data", "snapshot_at": "2026-04-29T00:00:00+00:00"},
    )
    with TestClient(global_app) as client:
        resp = client.post("/api/v1/assets/health/snapshot")
    assert resp.status_code == 200
    body = resp.json()
    assert body["score"] == 50
    assert "snapshot_at" in body
