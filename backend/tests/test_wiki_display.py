"""Wiki 知识展示层测试：DB 函数 + API 端点。"""
from __future__ import annotations

import json
import pathlib
import time
import uuid

import pytest
from starlette.testclient import TestClient

pytestmark = [pytest.mark.real_db]

from cangjie_fos.main import app as global_app


@pytest.fixture()
def isolated_db(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    db_file = tmp_path / "test_wiki.sqlite"
    monkeypatch.setattr(
        "cangjie_fos.services.pitch_job_db._db_path",
        lambda: str(db_file),
    )
    return tmp_path


# ─── 1. db_institution_briefing ───────────────────────────────────────────────

def test_institution_briefing_no_history(isolated_db):
    """无历史时返回 has_history=False，gap_hints 为空列表。"""
    from cangjie_fos.services.pitch_job_db import db_institution_briefing

    result = db_institution_briefing("完全陌生机构")
    assert result["has_history"] is False
    assert result["gap_hints"] == []
    assert result["total_sessions"] == 0


def test_institution_briefing_detects_gaps(isolated_db):
    """confirm 后 gray/red 结果变成 gap_hints。"""
    from cangjie_fos.services.pitch_job_db import (
        db_institution_briefing,
        db_match_session_create,
        db_match_session_update,
    )

    # 造一个有 gray 结果的 confirmed session
    sess_id = str(uuid.uuid4())
    results = [
        {"requirement": {"description": "知识产权证书", "scene_type": "", "time_range": ""},
         "candidates": [], "color": "gray"},
        {"requirement": {"description": "近三年审计报告", "scene_type": "", "time_range": ""},
         "candidates": [{"asset": {"filename": "audit.pdf", "relative_path": "audit.pdf"},
                         "score": 0.85, "color": "green", "matched_fields": []}],
         "color": "green"},
    ]
    db_match_session_create(
        session_id=sess_id,
        institution="红杉资本",
        req_text="1. 知识产权证书\n2. 近三年审计报告",
        requirements=[],
        results=results,
    )
    db_match_session_update(sess_id, status="confirmed", confirmed_files=[])

    briefing = db_institution_briefing("红杉资本")
    assert briefing["has_history"] is True
    assert "知识产权证书" in briefing["gap_hints"]
    assert "近三年审计报告" not in briefing["gap_hints"]  # green 不算缺口


def test_institution_briefing_deduplicates_gaps(isolated_db):
    """同一缺口多次出现，只记录一次。"""
    from cangjie_fos.services.pitch_job_db import (
        db_institution_briefing,
        db_match_session_create,
        db_match_session_update,
    )

    gap_result = {"requirement": {"description": "竞品分析", "scene_type": "", "time_range": ""},
                  "candidates": [], "color": "gray"}

    for i in range(3):
        sid = str(uuid.uuid4())
        db_match_session_create(sid, "IDG", f"竞品分析 {i}", [], [gap_result])
        db_match_session_update(sid, status="confirmed", confirmed_files=[])

    briefing = db_institution_briefing("IDG")
    assert briefing["gap_hints"].count("竞品分析") == 1


# ─── 2. db_asset_wiki_summary ─────────────────────────────────────────────────

def test_asset_wiki_summary_no_history(isolated_db):
    """无历史数据时返回零值摘要，不报错。"""
    from cangjie_fos.services.pitch_job_db import db_asset_wiki_summary

    result = db_asset_wiki_summary("不存在的文件.pdf")
    assert result["total_selected"] == 0
    assert result["total_shown"] == 0
    assert result["institutions"] == []


def test_asset_wiki_summary_with_history(isolated_db):
    """有 match_outcomes 记录时正确聚合。"""
    from cangjie_fos.services.pitch_job_db import (
        db_asset_wiki_summary,
        db_match_outcome_batch_save,
    )

    db_match_outcome_batch_save(
        session_id="wiki-sess-a",
        institution="红杉资本",
        selected_paths=["BP.pdf"],
        candidate_paths=["BP.pdf", "审计.pdf"],
    )
    db_match_outcome_batch_save(
        session_id="wiki-sess-b",
        institution="IDG",
        selected_paths=["BP.pdf"],
        candidate_paths=["BP.pdf"],
    )

    result = db_asset_wiki_summary("BP.pdf")
    assert result["total_selected"] == 2
    assert result["total_shown"] >= 2
    assert result["selection_rate"] > 0
    institutions = [i["institution"] for i in result["institutions"]]
    assert "红杉资本" in institutions
    assert "IDG" in institutions


# ─── 3. candidate reason 字段 ─────────────────────────────────────────────────

def test_candidate_to_dict_has_reason():
    """candidate_to_dict 为每个候选生成 reason 文本。"""
    from cangjie_fos.engine.matchmaker import BM25MatcherSkill, RequirementItem

    assets = [
        {"filename": "审计报告.pdf", "summary": "年度审计", "tags": ["审计"],
         "relative_path": "审计报告.pdf"},
    ]
    reqs = [RequirementItem(description="审计")]
    results = BM25MatcherSkill().match(reqs, assets, top_n=1)
    from cangjie_fos.engine.matchmaker import result_to_dict
    d = result_to_dict(results[0])
    candidate = d["candidates"][0]
    assert "reason" in candidate
    assert isinstance(candidate["reason"], str)
    assert len(candidate["reason"]) > 0


def test_reason_includes_history_boost():
    """机构历史偏好命中时，reason 包含'机构历史首选'。"""
    from cangjie_fos.engine.matchmaker import BM25MatcherSkill, RequirementItem, result_to_dict

    assets = [{"filename": "审计报告.pdf", "summary": "年度审计", "tags": ["审计"],
               "relative_path": "审计报告.pdf"}]
    reqs = [RequirementItem(description="审计")]
    profile = {"preferred_paths": ["审计报告.pdf"], "preferred_tags": [], "total_sessions": 5}
    results = BM25MatcherSkill().match(reqs, assets, institution_profile=profile, top_n=1)
    d = result_to_dict(results[0])
    assert "机构历史首选" in d["candidates"][0]["reason"]


# ─── 4. API 端点 ──────────────────────────────────────────────────────────────

def test_institution_briefing_api_no_history(isolated_db):
    """/api/v1/institutions/{name}/briefing 无历史时返回 has_history=False。"""
    with TestClient(global_app) as client:
        r = client.get("/api/v1/institutions/从未接触的机构XYZ/briefing")
    assert r.status_code == 200
    body = r.json()
    assert body["has_history"] is False
    assert body["gap_hints"] == []


def test_asset_wiki_api(isolated_db):
    """/api/v1/assets/wiki/{path} 返回正确结构。"""
    with TestClient(global_app) as client:
        r = client.get("/api/v1/assets/wiki/不存在的文件.pdf")
    assert r.status_code == 200
    body = r.json()
    assert "total_selected" in body
    assert "institutions" in body
    assert "selection_rate" in body


def test_digest_pending_api(isolated_db):
    """/api/v1/digest/pending 返回 suggestions 列表（可为空）。"""
    with TestClient(global_app) as client:
        r = client.get("/api/v1/digest/pending")
    assert r.status_code == 200
    body = r.json()
    assert "suggestions" in body
    assert "count" in body
    assert isinstance(body["suggestions"], list)


def test_match_route_includes_gap_hints(isolated_db, monkeypatch):
    """POST /api/v1/assets/match 返回中包含 gap_hints 字段。"""
    monkeypatch.setattr(
        "cangjie_fos.api.routes.assets.db_assets_list",
        lambda limit=2000: [],
    )
    with TestClient(global_app) as client:
        r = client.post("/api/v1/assets/match", json={
            "institution": "任意机构", "req_text": "1. 审计报告",
        })
    assert r.status_code == 200
    body = r.json()
    assert "gap_hints" in body
    assert isinstance(body["gap_hints"], list)
