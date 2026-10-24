"""尽调索引质量修复（H1 大库摘要兜底 / H2 目录黑名单 / H3 .doc 提示）测试。

对应同事 8/3 实测报告的根因：大库 summary 全空导致语义检索失效、
dev/node_modules 污染索引、.doc 旧格式报错。
"""
from __future__ import annotations

import pytest

from cangjie_fos.services import dd_index_service as idx


# ── H2 目录黑名单 ─────────────────────────────────────────────────────────────

def test_excluded_dirs_filtered(tmp_path):
    from pathlib import Path
    root = tmp_path
    (root / "材料").mkdir()
    (root / "材料" / "营业执照.pdf").write_text("x")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "readme.md").write_text("x")
    (root / "cangjie-venv").mkdir()
    (root / "cangjie-venv" / "lib.txt").write_text("x")
    (root / ".git").mkdir()
    (root / ".git" / "config.txt").write_text("x")

    assert idx._is_excluded_dir(root / "node_modules" / "readme.md", root) is True
    assert idx._is_excluded_dir(root / "cangjie-venv" / "lib.txt", root) is True
    assert idx._is_excluded_dir(root / ".git" / "config.txt", root) is True
    assert idx._is_excluded_dir(root / "材料" / "营业执照.pdf", root) is False


def test_scan_skips_excluded_dirs(tmp_path, monkeypatch):
    (tmp_path / "材料").mkdir()
    (tmp_path / "材料" / "章程.txt").write_text("公司章程正文")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.txt").write_text("junk")
    # 避免真实 LLM
    monkeypatch.setattr(idx, "_llm_summarize", lambda name, text: "摘要")
    result = idx.scan_and_index_folder(str(tmp_path), tenant_id="t1")
    assert result["total"] == 1  # 只有材料/章程.txt，node_modules 被排除


# ── H1 大库摘要兜底 ───────────────────────────────────────────────────────────

def test_summary_mode_tiers(tmp_path, monkeypatch):
    """总数决定摘要策略：小库=llm，中大库=excerpt，超大库=none。"""
    monkeypatch.setattr(idx, "MAX_LLM_SUMMARIZE_FILES", 2)
    monkeypatch.setattr(idx, "MAX_LIGHT_EXTRACT_FILES", 5)

    captured = []
    monkeypatch.setattr(
        idx, "_index_single_file",
        lambda fp, root, summary_mode="llm", **kw: captured.append(summary_mode),
    )
    monkeypatch.setattr(idx, "_llm_summarize", lambda name, text: "s")

    # 造 4 个文件 → 2 < 4 <= 5 → excerpt
    for i in range(4):
        (tmp_path / f"f{i}.txt").write_text("内容")
    idx.scan_and_index_folder(str(tmp_path), tenant_id="t1")
    assert set(captured) == {"excerpt"}


def test_excerpt_mode_produces_content_summary(tmp_path, monkeypatch):
    """excerpt 模式：不调 LLM，但用正文摘录做 summary（恢复语义粗筛）。"""
    from cangjie_fos.services.db_base import _connect

    f = tmp_path / "审计报告.txt"
    f.write_text("本报告为近三年财务审计报告，涵盖资产负债表与利润表明细。")

    called = []
    monkeypatch.setattr(idx, "_llm_summarize", lambda name, text: called.append(1) or "不该被调")
    idx._index_single_file(f, str(tmp_path), summary_mode="excerpt")

    with _connect() as conn:
        row = conn.execute(
            "SELECT summary FROM dd_asset_index WHERE file_path=?", (str(f),)
        ).fetchone()
    assert row is not None
    assert row["summary"] and "审计报告" in row["summary"]  # 有正文摘要
    assert called == []  # 没调 LLM（0 额外 token）


def test_none_mode_filename_only(tmp_path):
    from cangjie_fos.services.db_base import _connect
    f = tmp_path / "某文件.txt"
    f.write_text("正文")
    idx._index_single_file(f, str(tmp_path), summary_mode="none")
    with _connect() as conn:
        row = conn.execute("SELECT summary FROM dd_asset_index WHERE file_path=?", (str(f),)).fetchone()
    assert row["summary"] is None  # 超大库纯文件名


# ── H3 .doc 旧格式提示 ────────────────────────────────────────────────────────

def test_doc_old_format_clear_message(tmp_path):
    from cangjie_fos.services.dd_checklist_parser import _read_word
    doc = tmp_path / "清单.doc"
    doc.write_bytes(b"\xd0\xcf\x11\xe0old-ole-binary")  # 伪二进制 .doc
    with pytest.raises(ValueError) as ei:
        _read_word(doc)
    assert "另存为" in str(ei.value) or "docx" in str(ei.value)
