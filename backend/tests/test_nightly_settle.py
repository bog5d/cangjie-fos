"""Phase 3 — 夜间结算测试：DB CRUD、服务调用链、admin端点。"""
from __future__ import annotations

import sqlite3
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import cangjie_fos.services.pitch_job_db as _db_module
from cangjie_fos.main import app
from cangjie_fos.services.pitch_job_db import (
    db_nightly_suggestion_insert,
    db_nightly_suggestion_list_pending,
    db_nightly_suggestion_mark_consumed,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch, tmp_path):
    """每个测试使用独立 SQLite 文件，不污染 data/pitch_jobs.sqlite。"""
    db_file = tmp_path / "pitch_jobs.sqlite"
    monkeypatch.setattr(_db_module, "_db_path", lambda: str(db_file))
    yield


# ---------------------------------------------------------------------------
# Test 1: 表自动创建
# ---------------------------------------------------------------------------


def test_table_created(tmp_path):
    """首次访问 DB 后 nightly_suggestions 表必须存在。"""
    db_nightly_suggestion_list_pending("t1")  # trigger _init_db
    db_path = tmp_path / "pitch_jobs.sqlite"
    conn = sqlite3.connect(str(db_path))
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='nightly_suggestions'"
    )
    assert cur.fetchone() is not None, "nightly_suggestions 表未创建"
    conn.close()


# ---------------------------------------------------------------------------
# Test 2: 插入后 list_pending 返回正确记录
# ---------------------------------------------------------------------------


def test_insert_and_list_pending():
    sid = str(uuid.uuid4())
    db_nightly_suggestion_insert(
        id=sid,
        tenant_id="t1",
        type="material_update",
        content="测试建议内容",
        priority=3,
    )
    rows = db_nightly_suggestion_list_pending("t1")
    assert len(rows) == 1
    assert rows[0]["id"] == sid
    assert rows[0]["type"] == "material_update"
    assert rows[0]["content"] == "测试建议内容"
    assert rows[0]["priority"] == 3
    assert rows[0]["consumed_at"] is None


# ---------------------------------------------------------------------------
# Test 3: mark_consumed 后不再返回
# ---------------------------------------------------------------------------


def test_mark_consumed():
    sid = str(uuid.uuid4())
    db_nightly_suggestion_insert(id=sid, tenant_id="t1", type="risk_pattern", content="风险建议")
    db_nightly_suggestion_mark_consumed(sid)
    rows = db_nightly_suggestion_list_pending("t1")
    assert all(r["id"] != sid for r in rows), "已消费的建议不应出现在pending列表"


# ---------------------------------------------------------------------------
# Test 4: priority > max_priority 的记录不被列出
# ---------------------------------------------------------------------------


def test_list_pending_max_priority():
    low = str(uuid.uuid4())
    high = str(uuid.uuid4())
    db_nightly_suggestion_insert(id=low, tenant_id="t1", type="material_update", content="低优先级", priority=3)
    db_nightly_suggestion_insert(id=high, tenant_id="t1", type="material_update", content="高优先级", priority=8)
    rows = db_nightly_suggestion_list_pending("t1", max_priority=5)
    ids = {r["id"] for r in rows}
    assert low in ids
    assert high not in ids


# ---------------------------------------------------------------------------
# Test 5: limit 参数生效
# ---------------------------------------------------------------------------


def test_list_pending_limit():
    for i in range(5):
        db_nightly_suggestion_insert(
            id=str(uuid.uuid4()),
            tenant_id="t1",
            type="institution_insight",
            content=f"建议 {i}",
        )
    rows = db_nightly_suggestion_list_pending("t1", limit=3)
    assert len(rows) == 3


# ---------------------------------------------------------------------------
# Test 6: nightly_settle_for_tenant mock 调用链
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nightly_settle_for_tenant_mock():
    """验证 nightly_settle_for_tenant 调用 run_preference_extraction 并写入DB。"""
    import cangjie_fos.services.nightly_settle as _settle_mod

    with (
        patch(
            "cangjie_fos.services.evolution_extractor.run_preference_extraction",
            return_value=2,
        ) as mock_extract,
        patch.object(
            _settle_mod,
            "_generate_material_suggestions",
            return_value=[
                {"type": "material_update", "content": "mock建议", "priority": 5}
            ],
        ) as mock_gen,
    ):
        from cangjie_fos.services.nightly_settle import nightly_settle_for_tenant
        count = await nightly_settle_for_tenant("tenant-x")

    assert count == 1
    mock_extract.assert_called_once()
    mock_gen.assert_called_once_with("tenant-x")
    rows = db_nightly_suggestion_list_pending("tenant-x")
    assert len(rows) == 1
    assert rows[0]["content"] == "mock建议"


# ---------------------------------------------------------------------------
# Test 7: 手动触发端点 200
# ---------------------------------------------------------------------------


def test_admin_endpoint_200():
    with patch(
        "cangjie_fos.services.nightly_settle.nightly_settle_for_tenant",
        new=AsyncMock(return_value=3),
    ):
        resp = client.post("/api/v1/admin/nightly-settle?tenant_id=t1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tenant_id"] == "t1"
    assert data["suggested"] == 3


# ---------------------------------------------------------------------------
# Test 8: 手动触发端点 缺少 tenant_id → 422
# ---------------------------------------------------------------------------


def test_admin_endpoint_missing_tenant_id_422():
    resp = client.post("/api/v1/admin/nightly-settle")
    assert resp.status_code == 422
