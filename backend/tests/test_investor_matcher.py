"""investor_matcher.py 单元测试 — 覆盖关键词匹配、阶段评分、画像构建、空数据兜底。

Bug #3 入手模块，先建测试固件再修逻辑。
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from cangjie_fos.engine.investor_matcher import (
    CompanySnapshot,
    InstitutionMatchResult,
    _build_match_reason,
    _load_analytics_by_institution,
    _stage_proximity,
    build_institution_profile_from_analytics,
    calculate_match_score,
    format_match_report,
    match_institutions,
)


# ── Fixtures ──────────────────────────────────────────────────────

def _make_company(**kw) -> CompanySnapshot:
    defaults = {
        "company_name": "测试公司",
        "industry_tags": ["军工电子", "AI"],
        "stage": "B轮",
        "revenue_rmb_wan": 5000,
        "model_tags": ["ToB", "硬科技"],
        "highlights": ["军方合同"],
    }
    defaults.update(kw)
    return CompanySnapshot(**defaults)


def _make_profile(**kw) -> dict:
    defaults = {
        "institution_id": "inst_001",
        "institution_name": "深创投",
        "all_keywords": ["军工电子", "AI", "ToB", "半导体"],
        "preferred_stages": ["A轮", "B轮"],
        "session_count": 3,
    }
    defaults.update(kw)
    return defaults


def _make_analytics_record(institution_id: str, **kw) -> dict:
    defaults = {
        "institution_id": institution_id,
        "institution_name": "深创投",
        "high_freq_topics": ["军工电子", "AI"],
        "focus_keywords": ["ToB"],
        "preferred_stages": ["B轮"],
        "session_count": 2,
    }
    defaults.update(kw)
    return defaults


# ── Tests: _stage_proximity ────────────────────────────────────────

class TestStageProximity:
    def test_same_stage_returns_one(self):
        assert _stage_proximity("B轮", "B轮") == 1.0

    def test_one_step_apart(self):
        assert _stage_proximity("B轮", "B+轮") == 0.75

    def test_two_steps_apart(self):
        assert _stage_proximity("A轮", "B轮") == 0.5

    def test_far_apart_returns_zero(self):
        assert _stage_proximity("天使轮", "上市前") == 0.0

    def test_unknown_stage_returns_zero(self):
        assert _stage_proximity("未知", "B轮") == 0.0

    def test_both_unknown(self):
        assert _stage_proximity("X", "Y") == 0.0


# ── Tests: build_institution_profile_from_analytics ────────────────

class TestBuildProfile:
    def test_empty_records_returns_none(self):
        assert build_institution_profile_from_analytics([]) is None

    def test_single_record_builds_profile(self):
        profile = build_institution_profile_from_analytics([
            _make_analytics_record("inst_001"),
        ])
        assert profile is not None
        assert profile["institution_id"] == "inst_001"
        assert "军工电子" in profile["all_keywords"]

    def test_multiple_records_merge_keywords(self):
        profile = build_institution_profile_from_analytics([
            _make_analytics_record("inst_001", high_freq_topics=["AI"]),
            _make_analytics_record("inst_001", focus_keywords=["半导体"]),
        ])
        assert "AI" in profile["all_keywords"]
        assert "半导体" in profile["all_keywords"]

    def test_missing_name_falls_back_to_id(self):
        profile = build_institution_profile_from_analytics([
            {"institution_id": "inst_x", "high_freq_topics": [], "focus_keywords": []},
        ])
        assert profile["institution_name"] == "inst_x"

    def test_session_count_accumulated(self):
        profile = build_institution_profile_from_analytics([
            _make_analytics_record("inst_001", session_count=3),
            _make_analytics_record("inst_001", session_count=5),
        ])
        assert profile["session_count"] == 8


# ── Tests: calculate_match_score ───────────────────────────────────

class TestCalculateScore:
    def test_perfect_match(self):
        company = _make_company()
        profile = _make_profile()
        score = calculate_match_score(company, profile)
        assert 60 <= score <= 100  # 3 keyword hits + stage match + depth

    def test_no_keyword_overlap(self):
        company = _make_company(industry_tags=["医疗"], model_tags=["消费"])
        profile = _make_profile(all_keywords=["半导体", "新能源"])
        score = calculate_match_score(company, profile)
        # Only depth bonus + stage half credit = 15+12 = 27
        assert score < 50

    def test_no_profile_stage_gives_half_credit(self):
        company = _make_company(stage="B轮")
        profile = _make_profile(preferred_stages=[])
        score = calculate_match_score(company, profile)
        # stage_score=12 when no preferred stages
        assert score > 0

    def test_score_capped_at_100(self):
        company = _make_company(
            industry_tags=["军工电子", "AI", "半导体", "新能源", "ToB", "硬科技"],
            model_tags=["SaaS", "数据安全", "云计算"],
        )
        profile = _make_profile(
            all_keywords=["军工电子", "AI", "半导体", "新能源", "ToB", "硬科技", "SaaS", "数据安全", "云计算"],
            session_count=10,
        )
        score = calculate_match_score(company, profile)
        assert score <= 100

    def test_empty_profile_keywords_zero_industry_score(self):
        company = _make_company()
        profile = _make_profile(all_keywords=[])
        score = calculate_match_score(company, profile)
        assert score < 50


# ── Tests: _build_match_reason ─────────────────────────────────────

class TestMatchReason:
    def test_full_reason(self):
        company = _make_company()
        profile = _make_profile()
        reason = _build_match_reason(company, profile, ["军工电子", "AI"], True)
        assert "军工电子" in reason
        assert "B轮" in reason
        assert "3 次访谈" in reason

    def test_no_keywords_no_stage(self):
        company = _make_company(stage="")
        profile = _make_profile(preferred_stages=[], session_count=0, all_keywords=[])
        reason = _build_match_reason(company, profile, [], False)
        assert reason == "基础关键词匹配"


# ── Tests: match_institutions ──────────────────────────────────────

class TestMatchInstitutions:
    def test_empty_workspace_returns_empty(self, tmp_path):
        ws = str(tmp_path / "empty")
        Path(ws).mkdir()
        company = _make_company()
        results = match_institutions(company, ws)
        assert results == []

    def test_single_institution_match(self, tmp_path):
        ws = tmp_path / "analytics"
        ws.mkdir()
        record = {
            "institution_id": "inst_001",
            "institution_name": "深创投",
            "high_freq_topics": ["军工电子", "AI"],
            "focus_keywords": ["ToB"],
            "preferred_stages": ["B轮"],
            "session_count": 3,
        }
        (ws / "inst_001_analytics.json").write_text(json.dumps(record, ensure_ascii=False))

        company = _make_company()
        results = match_institutions(company, str(ws))
        assert len(results) >= 1
        assert results[0].institution_name == "深创投"

    def test_top_n_limit(self, tmp_path):
        ws = tmp_path / "many"
        ws.mkdir()
        for i in range(15):
            record = {
                "institution_id": f"inst_{i:03d}",
                "institution_name": f"机构{i}",
                "high_freq_topics": ["军工电子"],
                "focus_keywords": [],
                "preferred_stages": ["B轮"],
                "session_count": 1,
            }
            (ws / f"inst_{i:03d}_analytics.json").write_text(json.dumps(record, ensure_ascii=False))

        company = _make_company()
        results = match_institutions(company, str(ws), top_n=5)
        assert len(results) <= 5

    def test_results_sorted_by_score(self, tmp_path):
        ws = tmp_path / "sorted"
        ws.mkdir()
        # Create two institutions with different keyword overlap
        for i, topics in enumerate([["军工电子", "AI", "ToB", "硬科技"], ["医疗"]]):
            record = {
                "institution_id": f"inst_{i}",
                "institution_name": f"机构{i}",
                "high_freq_topics": topics,
                "focus_keywords": [],
                "preferred_stages": ["B轮"],
                "session_count": 3,
            }
            (ws / f"inst_{i}_analytics.json").write_text(json.dumps(record, ensure_ascii=False))

        company = _make_company()
        results = match_institutions(company, str(ws))
        assert len(results) >= 2
        assert results[0].score >= results[1].score

    def test_invalid_json_skipped(self, tmp_path):
        ws = tmp_path / "mixed"
        ws.mkdir()
        (ws / "bad_analytics.json").write_text("这不是JSON")
        record = _make_analytics_record("inst_good")
        (ws / "good_analytics.json").write_text(json.dumps(record, ensure_ascii=False))

        company = _make_company()
        results = match_institutions(company, str(ws))
        assert len(results) == 1


# ── Tests: format_match_report ─────────────────────────────────────

class TestFormatReport:
    def test_empty_results_shows_hint(self):
        company = _make_company()
        report = format_match_report(company, [])
        assert "暂无匹配数据" in report

    def test_non_empty_report(self):
        company = _make_company()
        results = [
            InstitutionMatchResult(
                institution_id="inst_001",
                institution_name="深创投",
                score=85,
                matched_keywords=["军工电子", "AI"],
                stage_match=True,
                session_count=3,
                match_reason="行业标签重合：军工电子, AI",
            )
        ]
        report = format_match_report(company, results)
        assert "深创投" in report
        assert "85分" in report
        assert "3 次访谈" in report
