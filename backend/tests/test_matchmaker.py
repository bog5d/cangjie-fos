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


# ─── 5. MatcherSkill 协议 ─────────────────────────────────────────────────────

def test_matcher_skill_protocol():
    """BM25MatcherSkill 实现了 MatcherSkill 协议。"""
    from cangjie_fos.engine.matchmaker import (
        BM25MatcherSkill, MatcherSkill, RequirementItem, get_default_matcher,
    )
    matcher = get_default_matcher()
    assert isinstance(matcher, BM25MatcherSkill)
    assert isinstance(matcher, MatcherSkill)


def test_bm25_skill_returns_results():
    """BM25MatcherSkill.match() 接口与旧 run_matching() 等价。"""
    from cangjie_fos.engine.matchmaker import BM25MatcherSkill, RequirementItem

    assets = [
        {"filename": "财务报表.xlsx", "summary": "年度财务", "tags": ["财务"], "relative_path": "财务/财务报表.xlsx"},
        {"filename": "BP.pdf", "summary": "商业计划书", "tags": ["BP"], "relative_path": "BP.pdf"},
    ]
    reqs = [RequirementItem(description="财务报表", scene_type="财务审计")]
    results = BM25MatcherSkill().match(reqs, assets, top_n=3)
    assert len(results) == 1
    assert results[0].candidates[0].asset["filename"] == "财务报表.xlsx"


def test_bm25_skill_with_institution_profile_boosts_preferred():
    """institution_profile 历史偏好加权：偏好文件得分提升 1.3x 并附加标记。

    验证两个核心行为：
      1. 偏好文件的 matched_fields 中出现 "[机构历史偏好↑]"
      2. 偏好文件的 score 比不带 profile 时高（×1.3）

    注：BM25 对 ASCII 关键词要求 ≥3 个字符；中文关键词要求 2-6 个汉字。
    这里用中文关键词"审计"（2字）保证可靠命中。
    """
    from cangjie_fos.engine.matchmaker import BM25MatcherSkill, RequirementItem

    assets = [
        # 两个资产都含"审计"，audit_v1 是被偏好的资产
        {"filename": "审计报告.pdf", "summary": "年度审计报告",
         "tags": ["审计", "财务"], "relative_path": "审计报告.pdf"},
        {"filename": "股权结构.docx", "summary": "股权架构说明",
         "tags": ["股权"], "relative_path": "股权结构.docx"},
    ]
    reqs = [RequirementItem(description="审计", scene_type="财务审计")]

    # 无 profile：审计报告.pdf 应命中，且无偏好标记
    without_profile = BM25MatcherSkill().match(reqs, assets, top_n=2)
    base_cand = next(
        (c for c in without_profile[0].candidates if c.asset["filename"] == "审计报告.pdf"), None
    )
    assert base_cand is not None, "审计报告.pdf 应命中查询"
    base_score = base_cand.score
    assert "[机构历史偏好↑]" not in base_cand.matched_fields

    # 注入历史偏好（审计报告.pdf 历史上被机构选过）
    profile = {
        "preferred_paths": ["审计报告.pdf"],
        "preferred_tags": ["审计"],
        "total_sessions": 3,
    }
    with_profile = BM25MatcherSkill().match(reqs, assets, institution_profile=profile, top_n=2)
    boosted_cand = next(
        (c for c in with_profile[0].candidates if c.asset["filename"] == "审计报告.pdf"), None
    )
    assert boosted_cand is not None
    assert "[机构历史偏好↑]" in boosted_cand.matched_fields
    # 加权后得分 ≥ 基础分（×1.3，min(1.0, ...) 截断前必然提升）
    assert boosted_cand.score >= base_score


# ─── 6. match_outcomes 记忆飞轮 ───────────────────────────────────────────────

def test_match_outcome_batch_save_and_profile(isolated_db):
    """confirm → match_outcomes 写入 → db_institution_match_profile 正确聚合。"""
    from cangjie_fos.services.pitch_job_db import (
        db_match_outcome_batch_save,
        db_institution_match_profile,
    )

    # 模拟 3 次匹配，同一机构选了不同文件
    db_match_outcome_batch_save(
        session_id="sess-a",
        institution="红杉资本",
        selected_paths=["财务/报表.xlsx", "BP.pdf"],
        candidate_paths=["财务/报表.xlsx", "BP.pdf", "团队/简历.docx"],
    )
    db_match_outcome_batch_save(
        session_id="sess-b",
        institution="红杉资本",
        selected_paths=["BP.pdf"],
        candidate_paths=["BP.pdf", "产品/白皮书.pdf"],
    )

    profile = db_institution_match_profile("红杉资本")
    assert profile["institution"] == "红杉资本"
    assert profile["total_sessions"] == 2
    assert profile["total_selected"] == 3
    # BP.pdf 被选了 2 次，应排在 preferred_paths 第一位
    assert profile["preferred_paths"][0] == "BP.pdf"
    assert "财务/报表.xlsx" in profile["preferred_paths"]


def test_match_outcome_empty_institution(isolated_db):
    """无历史数据时 db_institution_match_profile 返回空画像，不报错。"""
    from cangjie_fos.services.pitch_job_db import db_institution_match_profile

    profile = db_institution_match_profile("完全陌生的机构XYZ")
    assert profile["total_sessions"] == 0
    assert profile["preferred_paths"] == []


def test_confirm_api_writes_outcomes(isolated_db, monkeypatch: pytest.MonkeyPatch):
    """API confirm 后，match_outcomes 表有对应记录，下次匹配时 profile_injected=True。"""
    from cangjie_fos.services.pitch_job_db import db_institution_match_profile

    # 第一次匹配：无历史，profile_injected=False
    monkeypatch.setattr(
        "cangjie_fos.api.routes.assets.db_assets_list",
        lambda limit=2000: [
            {"filename": "BP.pdf", "summary": "商业计划书", "tags": ["BP"], "relative_path": "BP.pdf"},
            {"filename": "财务.xlsx", "summary": "财务模型", "tags": ["财务"], "relative_path": "财务.xlsx"},
        ],
    )
    with TestClient(global_app) as client:
        match_resp = client.post(
            "/api/v1/assets/match",
            json={"institution": "测试机构_Profile", "req_text": "1. BP"},
        )
        assert match_resp.status_code == 200
        assert match_resp.json().get("profile_injected") is False

        session_id = match_resp.json()["session_id"]

        # confirm，选 BP.pdf
        confirm_resp = client.post(
            f"/api/v1/assets/match/{session_id}/confirm",
            json={"confirmed_files": [{"filename": "BP.pdf", "relative_path": "BP.pdf", "full_path": ""}]},
        )
        assert confirm_resp.status_code == 200

    # 验证 match_outcomes 已写入
    profile = db_institution_match_profile("测试机构_Profile")
    assert profile["total_sessions"] == 1
    assert "BP.pdf" in profile["preferred_paths"]


# ─── 7. BM25 关键词提取增强（2字母ASCII + 动态boost）──────────────────────────

def test_extract_keywords_recognizes_two_letter_ascii():
    """修复：_extract_keywords 现在能识别2字母ASCII词（BP/VC/PE等）。"""
    from cangjie_fos.engine.matchmaker import _extract_keywords

    kws = _extract_keywords("BP商业计划书 VC投资 PE基金")
    assert "bp" in kws, "BP 应被识别为关键词"
    assert "vc" in kws, "VC 应被识别为关键词"
    assert "pe" in kws, "PE 应被识别为关键词"


def test_bm25_matches_two_letter_query():
    """修复验证：查询词"BP"现在能正确命中含"BP"标签的文件。"""
    from cangjie_fos.engine.matchmaker import BM25MatcherSkill, RequirementItem

    assets = [
        {"filename": "BP.pdf", "summary": "商业计划书", "tags": ["BP"], "relative_path": "BP.pdf"},
        {"filename": "财务报表.xlsx", "summary": "年度财务", "tags": ["财务"], "relative_path": "财务.xlsx"},
    ]
    reqs = [RequirementItem(description="BP商业计划书")]
    results = BM25MatcherSkill().match(reqs, assets, top_n=2)
    assert len(results) == 1
    assert results[0].candidates, "BP查询应有命中结果"
    assert results[0].candidates[0].asset["filename"] == "BP.pdf", "BP.pdf 应排第一"


def test_compute_boost_factor_dynamic():
    """动态boost_factor：根据total_sessions返回正确的档位值。"""
    from cangjie_fos.engine.matchmaker import _compute_boost_factor

    assert _compute_boost_factor(None) == 1.0,           "无画像 → 1.0"
    assert _compute_boost_factor({}) == 1.0,              "空画像 → 1.0"
    assert _compute_boost_factor({"total_sessions": 0}) == 1.0,  "0次 → 1.0"
    assert _compute_boost_factor({"total_sessions": 3}) == 1.0,  "3次 → 1.0（数据不足）"
    assert _compute_boost_factor({"total_sessions": 4}) == 1.2,  "4次 → 1.2"
    assert _compute_boost_factor({"total_sessions": 10}) == 1.2, "10次 → 1.2"
    assert _compute_boost_factor({"total_sessions": 11}) == 1.3, "11次 → 1.3"
    assert _compute_boost_factor({"total_sessions": 30}) == 1.3, "30次 → 1.3"
    assert _compute_boost_factor({"total_sessions": 31}) == 1.5, "31次 → 1.5"


def test_boost_not_applied_below_threshold():
    """total_sessions ≤ 3 时，boost_factor=1.0，偏好文件仍有[机构历史偏好↑]标记但得分不变。"""
    from cangjie_fos.engine.matchmaker import BM25MatcherSkill, RequirementItem

    assets = [
        {"filename": "审计报告.pdf", "summary": "年度审计", "tags": ["审计"], "relative_path": "审计报告.pdf"},
    ]
    reqs = [RequirementItem(description="审计")]

    # 无 profile
    base_results = BM25MatcherSkill().match(reqs, assets, top_n=1)
    base_score = base_results[0].candidates[0].score

    # total_sessions=2 < 4 → boost_factor=1.0
    profile_low = {"preferred_paths": ["审计报告.pdf"], "preferred_tags": [], "total_sessions": 2}
    low_results = BM25MatcherSkill().match(reqs, assets, institution_profile=profile_low, top_n=1)
    # 标记仍然存在（路径在preferred_paths中）
    assert "[机构历史偏好↑]" in low_results[0].candidates[0].matched_fields
    # 但分数不变（×1.0不产生变化，min(1.0, score*1.0) == score）
    assert low_results[0].candidates[0].score == pytest.approx(base_score)


# ─── 8. preferred_tags join assets 表 ────────────────────────────────────────

def test_preferred_tags_populated_from_assets_table(isolated_db):
    """db_institution_match_profile 现在从 assets 表 join 出偏好文件的 tags。"""
    from cangjie_fos.services.pitch_job_db import (
        db_asset_upsert,
        db_match_outcome_batch_save,
        db_institution_match_profile,
    )

    # 先写入资产（带 tags）
    db_asset_upsert(
        filename="审计报告.pdf",
        relative_path="审计报告.pdf",
        full_path="/data/审计报告.pdf",
        last_modified="2025-01-01",
        summary="年度审计报告",
        tags=["审计", "财务", "合规"],
        scan_dir="/data",
    )

    # 机构选中了这个文件
    db_match_outcome_batch_save(
        session_id="sess-tags-001",
        institution="测试机构_Tags",
        selected_paths=["审计报告.pdf"],
        candidate_paths=["审计报告.pdf"],
    )

    profile = db_institution_match_profile("测试机构_Tags")
    # preferred_tags 应从 assets 表 join 出来
    assert "审计" in profile["preferred_tags"], f"审计 应在 preferred_tags，实际: {profile['preferred_tags']}"
    assert "财务" in profile["preferred_tags"]
    assert "合规" in profile["preferred_tags"]


def test_preferred_tags_empty_when_no_assets_in_db(isolated_db):
    """preferred_paths 存在但 assets 表里没有对应记录时，preferred_tags 返回空列表（不报错）。"""
    from cangjie_fos.services.pitch_job_db import (
        db_match_outcome_batch_save,
        db_institution_match_profile,
    )

    # 只有 match_outcomes，assets 表里没有对应文件
    db_match_outcome_batch_save(
        session_id="sess-no-asset",
        institution="无资产机构",
        selected_paths=["不存在的文件.pdf"],
        candidate_paths=["不存在的文件.pdf"],
    )

    profile = db_institution_match_profile("无资产机构")
    assert profile["preferred_paths"] == ["不存在的文件.pdf"]
    assert profile["preferred_tags"] == []  # join 结果为空，不报错


# ─── 9. bundle 路由写 match_outcomes ────────────────────────────────────────

def test_bundle_route_writes_match_outcomes(isolated_db, monkeypatch: pytest.MonkeyPatch):
    """POST /api/v1/assets/bundle 完成后，match_outcomes 表有对应记录。"""
    from cangjie_fos.services.pitch_job_db import db_institution_match_profile

    with TestClient(global_app) as client:
        resp = client.post(
            "/api/v1/assets/bundle",
            json={
                "institution": "机构_Bundle飞轮",
                "files": [
                    {"filename": "BP.pdf", "relative_path": "BP.pdf", "full_path": ""},
                    {"filename": "财务.xlsx", "relative_path": "财务.xlsx", "full_path": ""},
                ],
            },
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed"

    # 验证 match_outcomes 写入
    profile = db_institution_match_profile("机构_Bundle飞轮")
    assert profile["total_sessions"] == 1
    assert "BP.pdf" in profile["preferred_paths"]
    assert "财务.xlsx" in profile["preferred_paths"]


# ─── 10. GET /api/v1/institutions/{name}/profile ────────────────────────────

def test_institution_profile_api(isolated_db, monkeypatch: pytest.MonkeyPatch):
    """GET /api/v1/institutions/{name}/profile 返回正确的偏好画像。"""
    from cangjie_fos.services.pitch_job_db import db_match_outcome_batch_save

    # 写入历史记录
    db_match_outcome_batch_save(
        session_id="sess-profile-api",
        institution="机构_ProfileAPI",
        selected_paths=["BP.pdf", "财务.xlsx"],
        candidate_paths=["BP.pdf", "财务.xlsx", "其他.docx"],
    )

    with TestClient(global_app) as client:
        resp = client.get("/api/v1/institutions/机构_ProfileAPI/profile")

    assert resp.status_code == 200
    body = resp.json()
    assert body["institution"] == "机构_ProfileAPI"
    assert body["total_sessions"] == 1
    assert body["total_selected"] == 2
    assert "BP.pdf" in body["preferred_paths"]
    assert isinstance(body["preferred_tags"], list)


def test_institution_profile_api_empty(isolated_db):
    """无历史数据时 GET /api/v1/institutions/{name}/profile 返回空画像（不报错）。"""
    with TestClient(global_app) as client:
        resp = client.get("/api/v1/institutions/完全陌生的机构ABC/profile")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_sessions"] == 0
    assert body["preferred_paths"] == []
    assert body["preferred_tags"] == []
