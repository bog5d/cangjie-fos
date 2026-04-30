"""MatchMaker V5.0 测试：引擎层 + DB 层 + API 端点。"""
from __future__ import annotations

import pathlib

import pytest
from starlette.testclient import TestClient

from cangjie_fos.main import app as global_app


# ─── 隔离 DB fixture ──────────────────────────────────────────────────────────

@pytest.fixture()
def isolated_db(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    db_file = tmp_path / "test_mm.sqlite"
    monkeypatch.setattr(
        "cangjie_fos.services.pitch_job_db._db_path",
        lambda: str(db_file),
    )
    return tmp_path


# ─── 1. 引擎：启发式解析基本功能 ─────────────────────────────────────────────

def test_parse_requirements_heuristic_basic():
    from cangjie_fos.engine.matchmaker import parse_requirements_heuristic

    text = "1. 近三年审计报告\n2. 股权结构图\n3. 核心团队简历"
    items = parse_requirements_heuristic(text)
    assert len(items) == 3
    assert items[0].description == "近三年审计报告"
    assert items[2].description == "核心团队简历"


def test_parse_requirements_heuristic_empty():
    from cangjie_fos.engine.matchmaker import parse_requirements_heuristic

    assert parse_requirements_heuristic("") == []
    assert parse_requirements_heuristic("   \n  ") == []


# ─── 2. 引擎：BM25 匹配评分 ──────────────────────────────────────────────────

def test_run_matching_returns_correct_count():
    from cangjie_fos.engine.matchmaker import RequirementItem, run_matching

    # 使用与关键词精准对齐的资产数据：标签字段权重最高(×3)，确保可靠命中
    assets = [
        {"filename": "audit2023.pdf",  "summary": "annual audit",  "tags": ["审计", "财务"]},
        {"filename": "equity.docx",    "summary": "equity structure", "tags": ["股权"]},
        {"filename": "resume.pdf",     "summary": "team background",  "tags": ["团队", "高管"]},
    ]
    reqs = [
        RequirementItem(description="审计", scene_type="财务审计"),  # "审计" 在 tags 中精准命中
        RequirementItem(description="股权"),                          # "股权" 在 tags 中精准命中
    ]
    results = run_matching(reqs, assets, top_n=2)
    assert len(results) == 2
    # 第一条需求：审计相关资产应排第一
    assert results[0].candidates[0].asset["filename"] == "audit2023.pdf"


def test_run_matching_gray_when_no_assets():
    from cangjie_fos.engine.matchmaker import RequirementItem, run_matching, COLOR_GRAY

    reqs = [RequirementItem(description="知识产权证书")]
    results = run_matching(reqs, [], top_n=3)
    assert len(results) == 1
    assert results[0].color == COLOR_GRAY


# ─── 3. DB：match_sessions CRUD ──────────────────────────────────────────────

def test_db_match_session_create_and_get(isolated_db):
    from cangjie_fos.services.pitch_job_db import (
        db_match_session_create,
        db_match_session_get,
    )

    db_match_session_create(
        session_id="sess-001",
        institution="红杉资本",
        req_text="1. 审计报告",
        requirements=[{"description": "审计报告", "scene_type": "", "time_range": ""}],
        results=[{"requirement": {"description": "审计报告"}, "candidates": [], "color": "gray"}],
    )
    sess = db_match_session_get("sess-001")
    assert sess is not None
    assert sess["institution"] == "红杉资本"
    assert sess["status"] == "draft"
    assert isinstance(sess["requirements"], list)


def test_db_match_session_update_status(isolated_db):
    from cangjie_fos.services.pitch_job_db import (
        db_match_session_create,
        db_match_session_get,
        db_match_session_update,
    )

    db_match_session_create("sess-002", "IDG", "1. BP", [], [])
    db_match_session_update("sess-002", status="confirmed", confirmed_files=[{"filename": "BP.pdf"}])
    sess = db_match_session_get("sess-002")
    assert sess["status"] == "confirmed"
    assert sess["confirmed_files"][0]["filename"] == "BP.pdf"


# ─── 4. API 路由 ─────────────────────────────────────────────────────────────

def test_api_match_post_returns_session(isolated_db, monkeypatch: pytest.MonkeyPatch):
    """POST /api/v1/assets/match：正常流 → 返回 session_id + results。"""
    # patch db_assets_list 返回假资产，避免依赖真实 DB 数据
    monkeypatch.setattr(
        "cangjie_fos.api.routes.assets.db_assets_list",
        lambda limit=2000: [
            {"filename": "审计报告.pdf", "summary": "年度审计", "tags": ["审计"], "relative_path": ""},
        ],
    )
    with TestClient(global_app) as client:
        resp = client.post(
            "/api/v1/assets/match",
            json={"institution": "测试机构", "req_text": "1. 近三年审计报告\n2. 股权结构图"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "session_id" in body
    assert body["req_count"] == 2
    assert len(body["results"]) == 2


def test_api_match_get_session(isolated_db, monkeypatch: pytest.MonkeyPatch):
    """GET /api/v1/assets/match/{id}：存在返回 200，不存在返回 404。"""
    monkeypatch.setattr(
        "cangjie_fos.api.routes.assets.db_assets_list",
        lambda limit=2000: [],
    )
    with TestClient(global_app) as client:
        # 先创建一个 session
        post_resp = client.post(
            "/api/v1/assets/match",
            json={"req_text": "审计报告"},
        )
        session_id = post_resp.json()["session_id"]

        # 正常取回
        get_resp = client.get(f"/api/v1/assets/match/{session_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == session_id

        # 不存在的 ID → 404
        not_found = client.get("/api/v1/assets/match/nonexistent-id")
        assert not_found.status_code == 404


def test_api_match_confirm(isolated_db, monkeypatch: pytest.MonkeyPatch):
    """POST /api/v1/assets/match/{id}/confirm：更新 status=confirmed。"""
    monkeypatch.setattr(
        "cangjie_fos.api.routes.assets.db_assets_list",
        lambda limit=2000: [],
    )
    with TestClient(global_app) as client:
        post_resp = client.post(
            "/api/v1/assets/match",
            json={"req_text": "1. 审计报告"},
        )
        session_id = post_resp.json()["session_id"]

        confirm_resp = client.post(
            f"/api/v1/assets/match/{session_id}/confirm",
            json={"confirmed_files": [{"filename": "audit.pdf", "full_path": "/data/audit.pdf"}]},
        )
    assert confirm_resp.status_code == 200
    body = confirm_resp.json()
    assert body["status"] == "confirmed"
    assert body["confirmed_count"] == 1
