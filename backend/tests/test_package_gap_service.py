"""需求03 — 数据包缺口分析测试（DB 隔离 + LLM mock）。"""
from __future__ import annotations

import time

from cangjie_fos.services import package_gap_service as gap
from cangjie_fos.services.db_base import _connect


def _seed_index(folder_root: str, files: list[tuple[str, str, float]]):
    """往 dd_asset_index 塞测试文件：(file_path, filename, mtime)。"""
    import uuid
    now = time.time()
    with _connect() as conn:
        for path, name, mtime in files:
            conn.execute(
                """INSERT INTO dd_asset_index
                   (id, folder_root, file_path, filename, file_type, summary,
                    readable, indexed_at, mtime, content_text)
                   VALUES (?, ?, ?, ?, '.pdf', ?, 1, ?, ?, '')""",
                (str(uuid.uuid4()), folder_root, path, name, name, now, mtime),
            )


def test_create_session_lays_out_template():
    r = gap.create_session("zt", "/data/pkg", title="A轮数据包")
    assert r["count"] >= 18
    items = gap.list_items(r["session_id"])
    assert len(items) == r["count"]
    assert all(it["gap_state"] == "pending" for it in items)


def test_gap_analysis_classifies_have_update_missing(monkeypatch):
    folder = "/data/pkg1"
    now = time.time()
    _seed_index(folder, [
        ("/data/pkg1/营业执照.pdf", "营业执照.pdf", now),                 # 新 + 高置信 → have
        ("/data/pkg1/2020审计报告.pdf", "2020审计报告.pdf", now - 800 * 86400),  # 旧 → update
    ])
    sess = gap.create_session("zt", folder)
    items = gap.list_items(sess["session_id"])
    by_req = {it["requirement"]: it["id"] for it in items}

    # mock 匹配：给"营业执照"高置信新文件、"审计报告"高置信旧文件，其余无匹配
    def fake_match(items_arg, index_rows):
        out = {}
        for it in items_arg:
            if "营业执照" in it["requirement"]:
                out[it["id"]] = {"file_path": "/data/pkg1/营业执照.pdf",
                                 "filename": "营业执照.pdf", "confidence": 0.95, "reason": "命中"}
            elif "审计报告" in it["requirement"]:
                out[it["id"]] = {"file_path": "/data/pkg1/2020审计报告.pdf",
                                 "filename": "2020审计报告.pdf", "confidence": 0.9, "reason": "命中但旧"}
        return out
    monkeypatch.setattr(gap, "_llm_match_package", fake_match)

    gap.run_gap_analysis(sess["session_id"], folder)

    items = gap.list_items(sess["session_id"])
    states = {it["requirement"]: it["gap_state"] for it in items}
    assert states["营业执照"] == "have"
    assert states["近三年审计报告"] == "update"          # 文件过旧 → 需更新
    assert states["商业计划书（BP）"] == "missing"        # 无匹配 → 缺失

    summary = gap.gap_summary(sess["session_id"])
    assert summary["have"] == 1
    assert summary["update"] == 1
    assert summary["missing"] == summary["total"] - 2
    # 分析完会话标记 done
    assert gap.get_session(sess["session_id"])["status"] == "done"


def test_gap_analysis_empty_index_all_missing(monkeypatch):
    monkeypatch.setattr(gap, "_llm_match_package", lambda i, r: {})
    sess = gap.create_session("zt", "/data/empty")
    gap.run_gap_analysis(sess["session_id"], "/data/empty")
    items = gap.list_items(sess["session_id"])
    assert all(it["gap_state"] == "missing" for it in items)
    assert gap.get_session(sess["session_id"])["status"] == "done"


def test_yellow_confidence_is_update(monkeypatch):
    folder = "/data/pkg2"
    _seed_index(folder, [("/data/pkg2/x.pdf", "x.pdf", time.time())])
    sess = gap.create_session("zt", folder)

    def fake_match(items_arg, index_rows):
        # 给第一项中置信度（0.5，落在 yellow 区间）
        first = items_arg[0]
        return {first["id"]: {"file_path": "/data/pkg2/x.pdf", "filename": "x.pdf",
                              "confidence": 0.5, "reason": "中等"}}
    monkeypatch.setattr(gap, "_llm_match_package", fake_match)

    gap.run_gap_analysis(sess["session_id"], folder)
    items = gap.list_items(sess["session_id"])
    assert items[0]["gap_state"] == "update"  # 中置信 → 需更新（待核）


def test_analysis_failure_marks_failed(monkeypatch):
    def boom(items_arg, index_rows):
        raise RuntimeError("LLM 炸了")
    folder = "/data/pkg3"
    _seed_index(folder, [("/data/pkg3/y.pdf", "y.pdf", time.time())])
    sess = gap.create_session("zt", folder)
    monkeypatch.setattr(gap, "_llm_match_package", boom)
    gap.run_gap_analysis(sess["session_id"], folder)
    # 异常也要给终态，防前端无限轮询
    assert gap.get_session(sess["session_id"])["status"] == "failed"


def test_list_sessions_isolated_to_package(monkeypatch):
    monkeypatch.setattr(gap, "_llm_match_package", lambda i, r: {})
    gap.create_session("tenant-iso", "/data/a", title="包A")
    rows = gap.list_sessions("tenant-iso")
    assert len(rows) == 1
    assert rows[0]["title"] == "包A"
    assert "missing_count" in rows[0]
