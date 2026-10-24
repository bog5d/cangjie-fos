"""asset_context.build_relevant_asset_snippet 单元测试。"""
from __future__ import annotations

import pytest

from cangjie_fos.services.asset_context import (
    _extract_cjk_ngrams,
    _score_asset,
    build_relevant_asset_snippet,
)

_SAMPLE_ASSETS = [
    {"filename": "BP.pdf", "relative_path": "", "summary": "商业计划书", "tags": ["融资", "BP"]},
    {"filename": "财务模型.xlsx", "relative_path": "财务", "summary": "三年期财务预测", "tags": ["财务"]},
    {"filename": "技术架构图.pptx", "relative_path": "技术", "summary": "系统架构说明", "tags": ["技术"]},
]


# --- 辅助函数 ---

def test_extract_cjk_ngrams_basic():
    ng = _extract_cjk_ngrams("见红杉要准备什么材料")
    assert "红杉" in ng
    assert "材料" in ng
    assert "准备" in ng


def test_extract_cjk_ngrams_english():
    ng = _extract_cjk_ngrams("准备BP和DD材料")
    assert "bp" in ng
    assert "dd" in ng


def test_score_asset_filename_match():
    asset = {"filename": "BP.pdf", "summary": "", "tags": [], "relative_path": ""}
    ng = _extract_cjk_ngrams("BP材料")
    assert _score_asset(asset, ng) > 0


def test_score_asset_tag_match():
    asset = {"filename": "报告.docx", "summary": "", "tags": ["财务"], "relative_path": ""}
    ng = _extract_cjk_ngrams("财务相关文件")
    assert _score_asset(asset, ng) > 0


def test_score_asset_no_match():
    asset = {"filename": "技术架构.pdf", "summary": "架构说明", "tags": ["技术"], "relative_path": ""}
    ng = _extract_cjk_ngrams("融资材料")
    assert _score_asset(asset, ng) == 0


# --- build_relevant_asset_snippet ---

def test_snippet_triggers_on_material_keyword(monkeypatch):
    monkeypatch.setattr("cangjie_fos.services.asset_context.load_asset_index_assets", lambda: _SAMPLE_ASSETS)
    result = build_relevant_asset_snippet("见红杉需要准备什么材料")
    assert result != ""
    assert "相关档案推荐" in result


def test_snippet_no_trigger_for_irrelevant_query(monkeypatch):
    monkeypatch.setattr("cangjie_fos.services.asset_context.load_asset_index_assets", lambda: _SAMPLE_ASSETS)
    result = build_relevant_asset_snippet("今天天气怎么样")
    assert result == ""


def test_snippet_returns_empty_for_empty_assets(monkeypatch):
    monkeypatch.setattr("cangjie_fos.services.asset_context.load_asset_index_assets", lambda: [])
    result = build_relevant_asset_snippet("需要准备什么材料")
    assert result == ""


def test_snippet_empty_user_text(monkeypatch):
    monkeypatch.setattr("cangjie_fos.services.asset_context.load_asset_index_assets", lambda: _SAMPLE_ASSETS)
    assert build_relevant_asset_snippet("") == ""


def test_snippet_matched_files_appear(monkeypatch):
    monkeypatch.setattr("cangjie_fos.services.asset_context.load_asset_index_assets", lambda: _SAMPLE_ASSETS)
    result = build_relevant_asset_snippet("帮我找财务相关的文件")
    assert "财务模型.xlsx" in result


def test_snippet_bp_keyword(monkeypatch):
    monkeypatch.setattr("cangjie_fos.services.asset_context.load_asset_index_assets", lambda: _SAMPLE_ASSETS)
    result = build_relevant_asset_snippet("发一下BP给投资人")
    assert "BP.pdf" in result


def test_snippet_respects_limit(monkeypatch):
    assets = [
        {"filename": f"文件{i}.pdf", "relative_path": "", "summary": "财务报告", "tags": ["财务"]}
        for i in range(20)
    ]
    monkeypatch.setattr("cangjie_fos.services.asset_context.load_asset_index_assets", lambda: assets)
    result = build_relevant_asset_snippet("需要什么财务材料", limit=3)
    # 最多 3 条 + header，不应出现第4条文件
    lines = [l for l in result.splitlines() if l.startswith("-")]
    assert len(lines) <= 3
