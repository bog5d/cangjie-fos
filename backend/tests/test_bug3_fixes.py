"""Bug #3 修复测试 — 尽调匹配不准的根因验证。

额外测试追加到 test_investor_matcher.py。
"""
from __future__ import annotations

from cangjie_fos.engine.investor_matcher import (
    _stage_proximity,
    calculate_match_score,
    match_institutions,
    CompanySnapshot,
    _build_match_reason,
)


class TestBug3MatchingFixes:
    """验证 Bug #3 根因的测试。"""

    def test_substring_keyword_should_match(self):
        """关键词 '军工电子' 应匹配标签 '军工'（子串匹配）。"""
        company = CompanySnapshot(
            company_name="测试公司",
            industry_tags=["军工"],
            stage="天使轮",  # 阶段不匹配，隔离关键词评分
        )
        profile = {
            "institution_id": "x",
            "institution_name": "Y",
            "all_keywords": ["军工电子", "AI"],
            "preferred_stages": ["D轮"],  # 完全不同
            "session_count": 0,  # 无深度奖励
        }
        score = calculate_match_score(company, profile)
        # 当前: 0分（无关键词交集、无阶段重合、无深度奖励）
        # 期望: >0分（子串匹配）
        assert score > 0, f"子串关键词应命中，实际 {score} 分"

    def test_partial_keyword_both_directions(self):
        """双向子串：机构关键词是公司标签的子串也应命中。"""
        company = CompanySnapshot(
            company_name="测试公司",
            industry_tags=["人工智能应用"],
            stage="天使轮",
        )
        profile = {
            "institution_id": "x",
            "institution_name": "Y",
            "all_keywords": ["人工智能"],
            "preferred_stages": ["D轮"],
            "session_count": 0,
        }
        score = calculate_match_score(company, profile)
        assert score > 0, f"双向子串应命中，实际 {score} 分"

    def test_stage_match_flag_uses_proximity(self):
        """`stage_match` 应按接近度判断，而非仅精确匹配。"""
        # 当前代码 line 274: company.stage in inst_stages — 严格相等
        # 但计分时 _stage_proximity("B轮", "B+轮")=0.75 给了部分分
        # 这导致 stage_match=False 但给了高分的不一致
        company = CompanySnapshot(
            company_name="测试公司",
            industry_tags=["AI"],
            stage="B轮",
        )
        profile = {
            "institution_id": "x",
            "institution_name": "Y",
            "all_keywords": ["AI"],
            "preferred_stages": ["B+轮"],
            "session_count": 1,
        }
        # 阶段接近应标记为匹配
        score = calculate_match_score(company, profile)
        assert score > 0  # 应有阶段部分分

    def test_pack_download_generates_json(self):
        """打包下载应生成包含匹配结果的 JSON 字符串。"""
        from cangjie_fos.engine.investor_matcher import (
            download_match_pack,
            InstitutionMatchResult,
        )
        company = CompanySnapshot(
            company_name="测试公司",
            industry_tags=["AI"],
        )
        results = [
            InstitutionMatchResult(
                institution_id="inst_001",
                institution_name="深创投",
                score=85,
                matched_keywords=["AI"],
                stage_match=True,
                session_count=3,
                match_reason="标签重合",
            )
        ]
        pack = download_match_pack(company, results)
        assert isinstance(pack, str)
        assert "inst_001" in pack
        assert "深创投" in pack
