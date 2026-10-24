"""Bug #10 修复测试 — 资产台账搜索不到内容的根因验证。"""
from __future__ import annotations

from cangjie_fos.engine.asset_bridge import find_related_assets, load_asset_index, build_asset_section


class TestBug10SearchFixes:
    def setup_method(self):
        self.assets = [
            {
                "filename": "财务报表_Q1.xlsx",
                "relative_path": "/finance/",
                "last_modified": "2026-05-01",
                "summary": "第一季度财务报表",
                "tags": ["财务", "报表"],
            },
            {
                "filename": "商业计划书_v3.pdf",
                "summary": "公司商业计划书",
                "tags": ["BP"],
            },
        ]

    def test_partial_keyword_finds_full_filename(self):
        """搜索 '财务' 应匹配文件名含 '财务报表' 的资产。"""
        result = find_related_assets("财务", self.assets)
        assert len(result) >= 1, "部分关键词应命中完整文件名"
        assert "财务报表" in result[0]["filename"]

    def test_tag_search_case_insensitive(self):
        """标签搜索应不区分大小写。"""
        result = find_related_assets("bp", self.assets)
        assert len(result) >= 1

    def test_mixed_chinese_english_search(self):
        """中英混合关键词应正常工作。"""
        result = find_related_assets("商业 计划书", self.assets)
        assert len(result) >= 1

    def test_build_section_returns_non_empty(self):
        """build_asset_section 应有输出。"""
        section = build_asset_section(["财务"], self.assets)
        assert len(section) > 0
