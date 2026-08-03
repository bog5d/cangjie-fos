"""决策记忆相似度命中（G2）测试。

飞轮从"逐字命中"升级为"措辞相近命中"，同时保留跨年份安全护栏。
"""
from __future__ import annotations

import time

from cangjie_fos.services.dd_match_service import (
    lookup_decision_memory,
    normalize_requirement,
    _bigram_jaccard,
)
from cangjie_fos.services.db_base import _connect


def _seed_mem(requirement: str, file_path: str, filename: str = "f.pdf", confirm_count: int = 3):
    norm = normalize_requirement(requirement)
    with _connect() as conn:
        conn.execute(
            """INSERT INTO dd_decision_memory
               (id, requirement_norm, requirement, file_path, filename,
                confirm_count, last_institution, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (f"{norm}::{file_path}", norm, requirement, file_path, filename,
             confirm_count, "红杉", time.time()),
        )


def test_exact_match_still_works():
    _seed_mem("公司营业执照", "/m/执照.pdf")
    hit = lookup_decision_memory("公司营业执照")
    assert hit is not None
    assert hit["match_type"] == "exact"
    assert hit["file_path"] == "/m/执照.pdf"


def test_fuzzy_match_on_reworded_requirement():
    """措辞相近（多个"的"）应命中同一份记忆文件。"""
    _seed_mem("近三年财务审计报告", "/m/审计.pdf")
    hit = lookup_decision_memory("近三年的财务审计报告")
    assert hit is not None
    assert hit["match_type"] == "fuzzy"
    assert hit["file_path"] == "/m/审计.pdf"
    assert hit["similarity"] >= 0.5


def test_year_guard_blocks_cross_year_match():
    """跨年份安全：2023 存的记忆不应被 2024 的需求命中。"""
    _seed_mem("2023年审计报告", "/m/2023审计.pdf")
    hit = lookup_decision_memory("2024年审计报告")
    assert hit is None  # 年份不同 → 不套用


def test_low_similarity_not_matched():
    _seed_mem("公司章程", "/m/章程.pdf")
    assert lookup_decision_memory("员工花名册及社保清单") is None


def test_fuzzy_forced_yellow_in_apply():
    """相似命中即便历史确认多次，也降为 yellow 待复核（不自动放绿）。"""
    from cangjie_fos.services import dd_match_service as m

    _seed_mem("公司股权结构表", "/m/股权.pdf", confirm_count=5)  # 确认多次
    # 建一个真实 session + item（措辞相近）
    sid = m.create_match_session(
        tenant_id="t1", checklist_name="清单", folder_root="/m",
        items=[{"item_no": 1, "requirement": "公司的股权结构表"}],
        institution_name="高瓴",
    )
    with _connect() as conn:
        item_id = conn.execute(
            "SELECT id FROM dd_match_items WHERE session_id=?", (sid,)
        ).fetchone()["id"]

    n = m._apply_decision_memory(
        sid, [{"id": item_id, "requirement": "公司的股权结构表"}],
        [{"file_path": "/m/股权.pdf"}],
    )
    assert n == 1
    with _connect() as conn:
        row = conn.execute(
            "SELECT matched_file_path, confidence, match_reason FROM dd_match_items WHERE id=?",
            (item_id,),
        ).fetchone()
    assert row["matched_file_path"] == "/m/股权.pdf"
    # 相似命中 → 置信度落在 yellow（未可信）区间，且 reason 标"措辞相近·待复核"
    assert row["confidence"] == m._MEMORY_UNTRUSTED_CONFIDENCE
    assert "措辞相近" in row["match_reason"]


def test_bigram_jaccard_basic():
    assert _bigram_jaccard("审计报告", "审计报告") == 1.0
    assert _bigram_jaccard("", "x") == 0.0
