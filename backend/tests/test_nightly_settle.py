"""夜间结算测试（v1.9.5 起仅偏好提取；nightly_suggestions/晨报已下线）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import cangjie_fos.services.pitch_job_db as _db_module
from cangjie_fos.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch, tmp_path):
    db_file = tmp_path / "pitch_jobs.sqlite"
    monkeypatch.setattr(_db_module, "_db_path", lambda: str(db_file))
    yield


@pytest.mark.asyncio
async def test_nightly_settle_runs_preference_extraction():
    """nightly_settle_for_tenant 应调用偏好提取并返回其条数（保留的真实学习链路）。"""
    with patch(
        "cangjie_fos.services.evolution_extractor.run_preference_extraction",
        return_value=3,
    ) as mock_extract:
        from cangjie_fos.services.nightly_settle import nightly_settle_for_tenant
        count = await nightly_settle_for_tenant("tenant-x")
    assert count == 3
    mock_extract.assert_called_once()


def test_admin_nightly_settle_endpoint_200():
    with patch(
        "cangjie_fos.services.nightly_settle.nightly_settle_for_tenant",
        new=AsyncMock(return_value=2),
    ):
        resp = client.post("/api/v1/admin/nightly-settle?tenant_id=t1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tenant_id"] == "t1"
    assert data["extracted"] == 2


def test_admin_nightly_settle_missing_tenant_id_422():
    resp = client.post("/api/v1/admin/nightly-settle")
    assert resp.status_code == 422
