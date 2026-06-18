"""尽调匹配质量优化测试：确定性年份护栏 + 项目背景注入 + prompt 铁律。

回应现场反馈：年份错配（2021→2022）、万能兜底、多主体不分。
"""
from __future__ import annotations

import time
import uuid
from unittest.mock import patch

from cangjie_fos.services import dd_match_service as ms
from cangjie_fos.services.db_base import _connect


# ── 确定性年份护栏 ──────────────────────────────────────────────────

def test_period_mismatch_detects_wrong_year():
    assert ms._period_mismatch("2021年12月增值税申报表", "2022.12增值税申报表.pdf") is True
    assert ms._period_mismatch("各主要产品2021年的成本结构", "2022年1-12月销售毛利汇总表.xlsx") is True


def test_period_mismatch_same_year_ok():
    assert ms._period_mismatch("2023年12月增值税申报表", "2023年增值税申报表.pdf") is False


def test_period_mismatch_range_requirement_skipped():
    """区间需求（2021至2024）不做确定性判定，避免误伤。"""
    assert ms._period_mismatch("2021至2024年10月关联交易", "2022年交易明细.xlsx") is False


def test_period_mismatch_no_year_no_constraint():
    assert ms._period_mismatch("公司章程", "公司章程2020.pdf") is False  # 需求无年份 → 不约束


def test_apply_period_guard_downgrades_green_to_yellow():
    sid = str(uuid.uuid4())
    iid = str(uuid.uuid4())
    with _connect() as conn:
        conn.execute(
            """INSERT INTO dd_match_sessions (session_id, tenant_id, folder_root, status, created_at)
               VALUES (?, 't', '/f', 'matched', ?)""", (sid, time.time()))
        conn.execute(
            """INSERT INTO dd_match_items
               (id, session_id, item_no, category, requirement, matched_file_path,
                matched_filename, confidence, verdict)
               VALUES (?, ?, '9', '财务', '2021年12月增值税申报表', '/f/2022.12.pdf',
                       '2022.12增值税申报表.pdf', 0.9, 'green')""",
            (iid, sid))

    ms._apply_period_guard(sid)

    with _connect() as conn:
        row = dict(conn.execute(
            "SELECT confidence, verdict, evidence FROM dd_match_items WHERE id = ?", (iid,),
        ).fetchone())
    assert row["confidence"] < ms._VERDICT_GREEN     # 压到绿线以下
    assert row["verdict"] in ("yellow", "red")        # 不再 green
    assert "年份" in row["evidence"]                  # 标注待核对


def test_apply_period_guard_leaves_correct_year_untouched():
    sid = str(uuid.uuid4())
    iid = str(uuid.uuid4())
    with _connect() as conn:
        conn.execute(
            """INSERT INTO dd_match_sessions (session_id, tenant_id, folder_root, status, created_at)
               VALUES (?, 't', '/f', 'matched', ?)""", (sid, time.time()))
        conn.execute(
            """INSERT INTO dd_match_items
               (id, session_id, item_no, category, requirement, matched_file_path,
                matched_filename, confidence, verdict)
               VALUES (?, ?, '11', '财务', '2023年12月增值税申报表', '/f/2023.pdf',
                       '2023年增值税申报表.pdf', 0.9, 'green')""",
            (iid, sid))

    ms._apply_period_guard(sid)
    with _connect() as conn:
        row = dict(conn.execute(
            "SELECT confidence, verdict FROM dd_match_items WHERE id = ?", (iid,),
        ).fetchone())
    assert row["confidence"] == 0.9 and row["verdict"] == "green"  # 年份对 → 不动


# ── 项目背景 + 铁律注入 ────────────────────────────────────────────

def _capture_match_prompt(items, context):
    captured = {}

    class _Resp:
        class _C:
            class _M:
                content = "{}"
            message = _M()
        choices = [_C()]

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(model, messages, **kw):
                    captured["prompt"] = messages[0]["content"]
                    return _Resp()

    rows = [{"file_path": "/f/a.pdf", "filename": "a.pdf", "summary": "s"}]
    with patch.object(ms, "get_dd_llm_client", lambda: _Client()):
        ms._llm_batch_match(items, "", rows, context=context)
    return captured.get("prompt", "")


def test_match_prompt_contains_rules_and_context():
    prompt = _capture_match_prompt(
        [{"id": "1", "requirement": "2021年审计报告"}],
        context="本项目含泽天湖南、四川两个主体，材料须按主体区分。",
    )
    assert "年份" in prompt and ("宁缺毋滥" in prompt or "真正满足" in prompt)  # 铁律
    assert "泽天湖南" in prompt and "两个主体" in prompt                       # 背景注入


def test_match_prompt_without_context_has_no_context_block():
    prompt = _capture_match_prompt([{"id": "1", "requirement": "审计报告"}], context="")
    assert "注意事项（务必遵守）" not in prompt          # 未注入背景块
    assert "宁缺毋滥" in prompt or "真正满足" in prompt   # 铁律仍在


def test_create_match_session_stores_context():
    sid = ms.create_match_session(
        "t", "c", "/f", [{"item_no": "1", "requirement": "x"}],
        context_note="多主体：湖南+四川",
    )
    with _connect() as conn:
        ctx = conn.execute(
            "SELECT context_note FROM dd_match_sessions WHERE session_id = ?", (sid,),
        ).fetchone()[0]
    assert ctx == "多主体：湖南+四川"


def test_run_matching_threads_context_to_match(monkeypatch):
    """run_matching 读取 session.context_note 并传给 _llm_batch_match。"""
    folder = "/data/ctx"
    sid = ms.create_match_session(
        "t", "c", folder, [{"item_no": "1", "requirement": "审计报告"}],
        context_note="泽天双主体",
    )
    with _connect() as conn:
        conn.execute(
            """INSERT INTO dd_asset_index
               (id, folder_root, file_path, filename, file_type, summary, readable, indexed_at)
               VALUES (?, ?, ?, 'a.pdf', '.pdf', 's', 1, ?)""",
            (str(uuid.uuid4()), folder, f"{folder}/a.pdf", time.time()))

    seen = {}
    def _fake_match(items, t, rows, **kw):
        seen["context"] = kw.get("context")
        return {}
    monkeypatch.setattr(ms, "_llm_batch_match", _fake_match)
    monkeypatch.setattr(ms, "_apply_decision_memory", lambda *a, **k: 0)
    monkeypatch.setattr(ms, "_refine_session_matches", lambda sid_, context="": None)

    ms.run_matching(sid, folder)
    assert seen["context"] == "泽天双主体"
