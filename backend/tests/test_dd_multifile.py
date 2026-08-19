"""多文件需求聚合（_apply_multifile_aggregation）测试。

针对「最近两年 / 多年度」这类一个需求要多份文件的场景：确定性地从候选池里
为每个应覆盖年份挑一份，落 extra_files_json 并按覆盖度重判。全程不调 LLM。
"""
from __future__ import annotations

import json
import time

import pytest

from cangjie_fos.services.dd_match_service import _apply_multifile_aggregation
from cangjie_fos.services.db_base import _connect


def _seed_item(item_id, requirement, matched_name, candidates,
               *, user_confirmed=0, extra=""):
    """插入一条 dd_match_item（含 session）。candidates=[(path,name),...]。"""
    cj = json.dumps(
        [{"file_path": f"/lib/{n}", "filename": n, "confidence": 0.7, "reason": ""}
         for _, n in candidates],
        ensure_ascii=False,
    )
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO dd_match_sessions (session_id, tenant_id, created_at) "
            "VALUES ('S','zt',?)", (time.time(),))
        conn.execute(
            "INSERT INTO dd_match_items (id, session_id, item_no, requirement, "
            "matched_file_path, matched_filename, confidence, candidates_json, "
            "user_confirmed, extra_files_json, verdict) "
            "VALUES (?, 'S', ?, ?, ?, ?, 0.7, ?, ?, ?, 'red')",
            (item_id, item_id, requirement, f"/lib/{matched_name}", matched_name,
             cj, user_confirmed, extra),
        )


def _get(item_id):
    with _connect() as conn:
        return dict(conn.execute(
            "SELECT * FROM dd_match_items WHERE id = ?", (item_id,)).fetchone())


def test_aggregates_multiyear_all_covered():
    _seed_item(
        "a", "请提供2023、2024年审计报告", "审计报告2023.pdf",
        [("", "审计报告2023.pdf"), ("", "审计报告2024.pdf")],
    )
    _apply_multifile_aggregation("S")
    row = _get("a")
    extras = json.loads(row["extra_files_json"])
    assert row["verdict"] == "green"
    assert row["matched_filename"] == "审计报告2023.pdf"      # 主文件=最早年
    assert len(extras) == 1 and extras[0]["year"] == 2024     # 另一年进 extra
    assert "已聚合" in (row["evidence"] or "")


def test_partial_coverage_marks_yellow_with_missing():
    _seed_item(
        "b", "请提供2022、2023、2024年纳税申报表", "纳税申报表2022.pdf",
        [("", "纳税申报表2022.pdf"), ("", "纳税申报表2023.pdf")],  # 缺 2024
    )
    _apply_multifile_aggregation("S")
    row = _get("b")
    assert row["verdict"] == "yellow"
    assert "2024" in (row["evidence"] or "")   # 标注缺哪年
    assert len(json.loads(row["extra_files_json"])) == 1


def test_single_year_requirement_untouched():
    _seed_item("c", "请提供2023年审计报告", "审计报告2023.pdf",
               [("", "审计报告2023.pdf")])
    _apply_multifile_aggregation("S")
    row = _get("c")
    assert not (row["extra_files_json"] or "")   # 单年度需求不聚合


def test_only_one_year_available_untouched():
    """多年度需求但库里只有一年 → 不硬凑，交回原判定。"""
    _seed_item("d", "请提供2023、2024年审计报告", "审计报告2023.pdf",
               [("", "审计报告2023.pdf")])   # 只有 2023
    _apply_multifile_aggregation("S")
    row = _get("d")
    assert not (row["extra_files_json"] or "")
    assert row["verdict"] == "red"   # 未被升级


def test_respects_user_confirmed():
    _seed_item("e", "请提供2023、2024年审计报告", "审计报告2023.pdf",
               [("", "审计报告2023.pdf"), ("", "审计报告2024.pdf")],
               user_confirmed=1)
    _apply_multifile_aggregation("S")
    assert not (_get("e")["extra_files_json"] or "")   # 用户已确认，不碰


def test_respects_existing_extra_files():
    _seed_item("f", "请提供2023、2024年审计报告", "审计报告2023.pdf",
               [("", "审计报告2023.pdf"), ("", "审计报告2024.pdf")],
               extra='[{"file_path":"/lib/手动.pdf","filename":"手动.pdf"}]')
    _apply_multifile_aggregation("S")
    row = _get("f")
    assert "手动.pdf" in row["extra_files_json"]   # 用户手动多选的保留不动


def test_matched_file_included_even_if_not_in_candidates():
    """已匹配文件本身也算候选池的一员（即使没进 candidates_json）。"""
    _seed_item("g", "请提供2023、2024年审计报告", "审计报告2024.pdf",
               [("", "审计报告2023.pdf")])   # candidates 只有 2023，matched 是 2024
    _apply_multifile_aggregation("S")
    row = _get("g")
    assert row["verdict"] == "green"   # 2023(候选)+2024(已匹配) 两年齐
    assert len(json.loads(row["extra_files_json"])) == 1
