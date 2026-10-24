"""
TDD：尽调 gk 模式 F4 — 历史问答复用（单次扒取 + 草稿）。

流程：
1. 扫描历史补充资料 → AI 提取「问题→答案」对 → 存 dd_qa_pairs。
2. 新需求 → 在 dd_qa_pairs 里语义检索最相近历史问答 → 出草稿（带置信度）。
3. 无命中 → 低置信初稿（不硬塞），标记待人工。

LLM 全程 mock，不真实调用。
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


# ════════════════════════════════════════════════════════════════════
# F4-1：历史补充资料扒取问答对
# ════════════════════════════════════════════════════════════════════

def test_extract_qa_pairs_persists_rows(tmp_path):
    """mock LLM 从一段文字扒出 2 个问答对 → dd_qa_pairs 落 2 行。"""
    from cangjie_fos.services.dd_qa_service import extract_qa_pairs_from_folder
    from cangjie_fos.services.db_base import _connect

    doc = tmp_path / "补充尽调资料.txt"
    doc.write_text("问：贵公司核心技术壁垒？答：自研算法。\n问：团队规模？答：50人。",
                   encoding="utf-8")

    fake_pairs = [
        {"question": "贵公司核心技术壁垒？", "answer": "自研算法",
         "confidence": 0.9},
        {"question": "团队规模？", "answer": "50人", "confidence": 0.9},
    ]
    with patch("cangjie_fos.services.dd_qa_service._llm_extract_qa",
               return_value=fake_pairs):
        result = extract_qa_pairs_from_folder(str(tmp_path), "gk")

    assert result["extracted"] == 2
    with _connect() as conn:
        rows = conn.execute(
            "SELECT question, answer, source_file FROM dd_qa_pairs "
            "WHERE folder_root = ?", (str(tmp_path),)
        ).fetchall()
    assert len(rows) == 2
    qs = {r["question"] for r in rows}
    assert "团队规模？" in qs
    assert all(r["source_file"] for r in rows), "应记录答案出处文件"


def test_extract_qa_only_scans_supplementary_files(tmp_path):
    """只扫描「补充/问答/答复」类文件，财报等正常材料不扒。"""
    from cangjie_fos.services.dd_qa_service import extract_qa_pairs_from_folder

    (tmp_path / "补充尽调资料.txt").write_text("问：A？答：B。", encoding="utf-8")
    (tmp_path / "2024财报.txt").write_text("资产负债表数据", encoding="utf-8")

    scanned: list[str] = []

    def _spy(filename, text):
        scanned.append(filename)
        return [{"question": "A？", "answer": "B", "confidence": 0.8}]

    with patch("cangjie_fos.services.dd_qa_service._llm_extract_qa",
               side_effect=_spy):
        extract_qa_pairs_from_folder(str(tmp_path), "gk")

    assert "补充尽调资料.txt" in scanned
    assert "2024财报.txt" not in scanned, "正常材料不应进问答扒取"


# ════════════════════════════════════════════════════════════════════
# F4-2：新需求 → 历史问答草稿
# ════════════════════════════════════════════════════════════════════

def test_generate_draft_hits_history(tmp_path):
    """新需求语义命中历史问答 → 草稿带出历史答案 + 高置信度。"""
    from cangjie_fos.services.dd_qa_service import (
        _persist_qa_pair, generate_answer_draft,
    )

    _persist_qa_pair("gk", str(tmp_path), "补充资料.txt",
                     "公司团队规模有多大？", "核心团队50人", "瑞源正方", 0.9)

    draft = generate_answer_draft("请说明团队规模情况", str(tmp_path))

    assert draft["matched"] is True
    assert "50人" in draft["answer"]
    assert draft["confidence"] >= 0.5
    assert draft["source_question"] == "公司团队规模有多大？"


def test_generate_draft_no_history_returns_low_conf(tmp_path):
    """无历史命中 → 低置信初稿（不硬塞历史答案），标记待人工。"""
    from cangjie_fos.services.dd_qa_service import (
        _persist_qa_pair, generate_answer_draft,
    )

    _persist_qa_pair("gk", str(tmp_path), "补充资料.txt",
                     "团队规模？", "50人", "瑞源正方", 0.9)

    # 与历史问答毫不相关的需求
    draft = generate_answer_draft("公司注册地及税务登记号", str(tmp_path))

    assert draft["matched"] is False
    assert draft["confidence"] < 0.5
    assert draft["answer"] == "", "无命中不应硬塞历史答案"


def test_generate_draft_empty_kb(tmp_path):
    """问答库为空（从没扒过历史）→ 不崩溃，返回未命中。"""
    from cangjie_fos.services.dd_qa_service import generate_answer_draft

    draft = generate_answer_draft("任意需求", str(tmp_path))
    assert draft["matched"] is False
    assert draft["confidence"] == 0.0
