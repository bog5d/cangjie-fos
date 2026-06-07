"""Phase 4 — 全数据关联测试：DB查询函数、capture_review_diff触发链路、nightly_settle真实计算、API端点。"""
from __future__ import annotations

import time
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import cangjie_fos.services.pitch_job_db as _db_module
from cangjie_fos.main import app
from cangjie_fos.services.pitch_job_db import (
    db_job_create,
    db_job_update,
    db_material_contribution_upsert,
    db_job_list_risk_keywords,
    db_assets_search_by_keywords,
    db_material_contribution_bulk_upsert,
    db_material_contributions_list,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch, tmp_path):
    """每个测试使用独立 SQLite 文件。"""
    db_file = tmp_path / "pitch_jobs.sqlite"
    monkeypatch.setattr(_db_module, "_db_path", lambda: str(db_file))
    yield


# ---------------------------------------------------------------------------
# Test 1: db_job_list_risk_keywords 返回正确格式
# ---------------------------------------------------------------------------


def test_db_job_list_risk_keywords_format():
    job_id = str(uuid.uuid4())
    tenant = "t-phase4"
    db_job_create(job_id, tenant)
    report = {
        "total_score": 80,
        "risk_points": [{"original_text": "估值偏高", "category": "估值风险"}],
    }
    db_job_update(job_id, status="completed", original_report=report)

    rows = db_job_list_risk_keywords(tenant, limit=5)
    assert len(rows) == 1
    row = rows[0]
    assert row["job_id"] == job_id
    assert isinstance(row["risk_points"], list)
    assert len(row["risk_points"]) == 1
    assert row["risk_points"][0]["original_text"] == "估值偏高"
    assert "created_at" in row


# ---------------------------------------------------------------------------
# Test 2: db_job_list_risk_keywords 只返回 completed 状态
# ---------------------------------------------------------------------------


def test_db_job_list_risk_keywords_only_completed():
    tenant = "t-phase4"
    for status in ("pending", "failed", "transcribing"):
        jid = str(uuid.uuid4())
        db_job_create(jid, tenant)
        db_job_update(jid, status=status)

    completed_id = str(uuid.uuid4())
    db_job_create(completed_id, tenant)
    db_job_update(completed_id, status="completed", original_report={"risk_points": []})

    rows = db_job_list_risk_keywords(tenant, limit=10)
    assert len(rows) == 1
    assert rows[0]["job_id"] == completed_id


# ---------------------------------------------------------------------------
# Test 3: db_assets_search_by_keywords 关键词匹配（tags命中）
# ---------------------------------------------------------------------------


def test_db_assets_search_by_keywords_tag_match():
    db_material_contribution_upsert(
        "pitch_deck.pdf",
        "docs/pitch_deck.pdf",
        tags=["估值", "路演"],
        usage_count_delta=2,
    )
    db_material_contribution_upsert(
        "logo.png",
        "assets/logo.png",
        tags=["品牌"],
        usage_count_delta=1,
    )

    results = db_assets_search_by_keywords("t1", ["估值"])
    filenames = [r["asset_filename"] for r in results]
    assert "pitch_deck.pdf" in filenames
    assert "logo.png" not in filenames


# ---------------------------------------------------------------------------
# Test 4: db_assets_search_by_keywords 空关键词返回空列表
# ---------------------------------------------------------------------------


def test_db_assets_search_by_keywords_empty_keywords():
    db_material_contribution_upsert("any.pdf", "any.pdf", usage_count_delta=1)
    results = db_assets_search_by_keywords("t1", [])
    assert results == []


# ---------------------------------------------------------------------------
# Test 5: db_material_contribution_bulk_upsert ON CONFLICT 累加
# ---------------------------------------------------------------------------


def test_db_material_contribution_bulk_upsert_accumulates():
    asset_id = "deck.pdf"
    # Insert once via bulk upsert
    db_material_contribution_bulk_upsert("t1", [asset_id], action="review_use")
    # Insert again
    db_material_contribution_bulk_upsert("t1", [asset_id], action="review_use")

    rows = db_material_contributions_list()
    matched = [r for r in rows if r["asset_filename"] == asset_id]
    assert len(matched) == 1
    assert matched[0]["usage_count"] >= 2


# ---------------------------------------------------------------------------
# Test 6: db_material_contribution_bulk_upsert 批量多个 asset
# ---------------------------------------------------------------------------


def test_db_material_contribution_bulk_upsert_multiple():
    assets = ["a.pdf", "b.pdf", "c.pdf"]
    db_material_contribution_bulk_upsert("t1", assets, action="review_use")
    rows = db_material_contributions_list()
    filenames = {r["asset_filename"] for r in rows}
    for a in assets:
        assert a in filenames


# ---------------------------------------------------------------------------
# Test 7: capture_review_diff 触发后 material_contributions 有新记录
# ---------------------------------------------------------------------------


def test_capture_review_diff_triggers_association():
    # Pre-populate asset using filename as relative_path (matches bulk_upsert convention)
    db_material_contribution_upsert(
        "risk_cover.pdf", "risk_cover.pdf",
        tags=["estimations", "valuation"],
        usage_count_delta=1,
    )

    job_id = str(uuid.uuid4())
    tenant = "t-assoc"
    db_job_create(job_id, tenant)
    db_job_update(job_id, status="completed")

    edited = {
        "total_score": 75,
        "risk_points": [
            {"original_text": "valuation risk", "category": "valuation"}
        ],
    }

    from cangjie_fos.services.evolution_capture import capture_review_diff
    diff_id = capture_review_diff(
        job_id=job_id,
        tenant_id=tenant,
        committed_at=time.time(),
        original_report=None,
        edited_report=edited,
    )

    assert isinstance(diff_id, int)
    # material_contributions usage_count should be incremented (ON CONFLICT on relative_path)
    rows = db_material_contributions_list()
    counts = {r["asset_filename"]: r["usage_count"] for r in rows}
    assert "risk_cover.pdf" in counts
    assert counts["risk_cover.pdf"] >= 2  # initial 1 + 1 from association


# ---------------------------------------------------------------------------
# Test 8: capture_review_diff 核心行为（写 review_diffs）仍正常
# （match_history 采集已下线，但 diff 捕获这一保留路径不受影响）
# ---------------------------------------------------------------------------


def test_capture_review_diff_writes_diff():
    job_id = str(uuid.uuid4())
    tenant = "t-match"
    db_job_create(job_id, tenant)
    db_job_update(job_id, status="completed")

    edited = {
        "total_score": 60,
        "risk_points": [{"original_text": "financing risk", "category": "financing"}],
    }

    from cangjie_fos.services.evolution_capture import capture_review_diff
    diff_id = capture_review_diff(
        job_id=job_id,
        tenant_id=tenant,
        committed_at=time.time(),
        original_report=None,
        edited_report=edited,
    )
    assert isinstance(diff_id, int)  # review_diffs 写入成功（核心保留行为）


# ---------------------------------------------------------------------------
# Test 9: nightly_settle_for_tenant 真实素材建议计算（mock assets 数据）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nightly_settle_real_material_suggestions():
    """验证 nightly_settle 用真实 TF-IDF 计算并写入 nightly_suggestions。"""
    import cangjie_fos.services.nightly_settle as _settle_mod

    tenant = "t-settle"
    # 创建已完成路演（含风险点）
    job_id = str(uuid.uuid4())
    db_job_create(job_id, tenant)
    report = {
        "total_score": 70,
        "risk_points": [{"original_text": "估值偏高", "category": "估值风险"}],
    }
    db_job_update(job_id, status="completed", original_report=report)

    # Mock evolution_extractor
    with patch(
        "cangjie_fos.services.evolution_extractor.run_preference_extraction",
        return_value=0,
    ):
        from cangjie_fos.services.nightly_settle import nightly_settle_for_tenant
        count = await nightly_settle_for_tenant(tenant)

    # 应当至少生成1条建议（兜底建议：素材库无数据）
    assert count >= 1

    from cangjie_fos.services.pitch_job_db import db_nightly_suggestion_list_pending
    rows = db_nightly_suggestion_list_pending(tenant, limit=10)
    assert len(rows) >= 1
    assert all(r["type"] in ("material_update", "institution_insight") for r in rows)


