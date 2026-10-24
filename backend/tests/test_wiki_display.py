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
