"""asset_bridge.py 单元测试 — 覆盖资产索引加载、关键词搜索、空数据兜底。

Bug #10 入手模块，先建测试固件再修逻辑。
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from cangjie_fos.engine.asset_bridge import (
    build_asset_section,
    find_related_assets,
    load_asset_index,
    _get_fos_data_dir,
)


# ── Fixtures ──────────────────────────────────────────────────────

def _make_assets() -> list[dict]:
    return [
        {
            "filename": "商业计划书_v3.pdf",
            "relative_path": "/docs/",
            "last_modified": "2026-05-10",
            "summary": "公司商业计划书第三版",
            "tags": ["BP", "融资"],
        },
        {
            "filename": "技术白皮书.pdf",
            "relative_path": "/docs/tech/",
            "last_modified": "2026-04-20",
            "summary": "核心技术架构说明",
            "tags": ["技术", "架构"],
        },
        {
            "filename": "财务报表_Q1.xlsx",
            "relative_path": "/finance/",
            "last_modified": "2026-05-01",
            "summary": "第一季度财务报表",
            "tags": ["财务", "报表"],
        },
    ]


def _write_asset_index(tmp_path: Path, assets: list[dict]) -> Path:
    index_path = tmp_path / "asset_index.json"
    index_path.write_text(json.dumps({"assets": assets}, ensure_ascii=False))
    return tmp_path


# ── Tests: load_asset_index ────────────────────────────────────────

class TestLoadAssetIndex:
    def test_loads_valid_index(self, tmp_path):
        _write_asset_index(tmp_path, _make_assets())
        result = load_asset_index(tmp_path)
        assert len(result) == 3
        assert result[0]["filename"] == "商业计划书_v3.pdf"

    def test_missing_file_returns_empty(self, tmp_path):
        result = load_asset_index(tmp_path / "nonexistent")
        assert result == []

    def test_invalid_json_returns_empty(self, tmp_path):
        (tmp_path / "asset_index.json").write_text("not json")
        result = load_asset_index(tmp_path)
        assert result == []

    def test_empty_assets_key_returns_empty(self, tmp_path):
        (tmp_path / "asset_index.json").write_text('{"assets": []}')
        result = load_asset_index(tmp_path)
        assert result == []

    def test_no_assets_key_returns_empty(self, tmp_path):
        (tmp_path / "asset_index.json").write_text('{"other": 1}')
        result = load_asset_index(tmp_path)
        assert result == []

    def test_env_var_overrides_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FOS_DATA_DIR", str(tmp_path))
        _write_asset_index(tmp_path, _make_assets()[:1])
        result = load_asset_index()
        assert len(result) == 1


# ── Tests: find_related_assets ─────────────────────────────────────

class TestFindRelatedAssets:
    def setup_method(self):
        self.assets = _make_assets()

    def test_finds_exact_filename_match(self):
        result = find_related_assets("商业计划书", self.assets)
        assert len(result) >= 1
        assert result[0]["filename"] == "商业计划书_v3.pdf"

    def test_finds_by_tag(self):
        result = find_related_assets("技术", self.assets)
        assert len(result) >= 1
        assert result[0]["filename"] == "技术白皮书.pdf"

    def test_finds_by_summary(self):
        result = find_related_assets("财务报表", self.assets)
        assert len(result) >= 1

    def test_multiple_keywords_or_match(self):
        result = find_related_assets("商业计划书 白皮书", self.assets)
        assert len(result) >= 2

    def test_top_n_limit(self):
        result = find_related_assets("财务 商业 技术", self.assets, top_n=2)
        assert len(result) <= 2

    def test_no_match_returns_empty(self):
        result = find_related_assets("不存在的关键词", self.assets)
        assert result == []

    def test_empty_keywords_returns_empty(self):
        result = find_related_assets("", self.assets)
        assert result == []

    def test_empty_assets_returns_empty(self):
        result = find_related_assets("关键词", [])
        assert result == []

    def test_results_sorted_by_hits(self):
        result = find_related_assets("商业计划书 技术", self.assets)
        # Both should match, highest hits first
        if len(result) >= 2:
            assert result[0]["filename"] in ("商业计划书_v3.pdf", "技术白皮书.pdf")


# ── Tests: build_asset_section ─────────────────────────────────────

class TestBuildAssetSection:
    def test_returns_markdown_section(self):
        assets = _make_assets()[:1]
        section = build_asset_section(["商业计划书"], assets)
        assert "库中相关资产" in section
        assert "商业计划书_v3.pdf" in section

    def test_no_match_returns_empty_string(self):
        result = build_asset_section(["不存在"], _make_assets())
        assert result == ""

    def test_empty_assets_returns_empty(self):
        result = build_asset_section(["关键词"], [])
        assert result == ""


# ── Tests: _get_fos_data_dir ───────────────────────────────────────

class TestGetFosDataDir:
    def test_env_var_overrides(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FOS_DATA_DIR", str(tmp_path))
        result = _get_fos_data_dir()
        assert result == tmp_path

    def test_default_resolves_to_path(self):
        result = _get_fos_data_dir()
        assert isinstance(result, Path)
