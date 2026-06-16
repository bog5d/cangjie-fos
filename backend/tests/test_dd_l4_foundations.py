"""L4 地基测试：持久化中间态（stage/reflection_iter 落库）+ 决策记忆幂等化。

回应架构审计——加任何高级机制（持久化中断 + 评估打回）前必须先夯实的两块地基：
  1. 解决状态裂脑：run_matching 的 stage / 反思轮次写进 dd_match_sessions，重启可知断点。
  2. 守护跨机构决策资产：record_session_decisions 幂等，resume/重复 export 不重复计数。
"""
from __future__ import annotations

import time
import uuid

from cangjie_fos.services import dd_match_service as ms
from cangjie_fos.services.db_base import _connect


def _seed_session(session_id: str, folder: str = "/data/f", institution: str = "高瓴"):
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO dd_match_sessions
               (session_id, tenant_id, checklist_name, folder_root, status,
                institution_name, created_at)
               VALUES (?, 'zt', 'c', ?, 'pending', ?, ?)""",
            (session_id, folder, institution, now),
        )


def _add_item(session_id: str, requirement: str, file_path: str, confirmed: int = 1) -> str:
    item_id = str(uuid.uuid4())
    with _connect() as conn:
        conn.execute(
            """INSERT INTO dd_match_items
               (id, session_id, item_no, category, requirement,
                matched_file_path, matched_filename, confidence, user_confirmed)
               VALUES (?, ?, '1', '财务', ?, ?, ?, 0.9, ?)""",
            (item_id, session_id, requirement, file_path,
             file_path.split("/")[-1], confirmed),
        )
    return item_id


def _read_session(session_id: str) -> dict:
    with _connect() as conn:
        return dict(conn.execute(
            "SELECT status, stage, reflection_iter FROM dd_match_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone())


# ── 地基 1：持久化中间态 ──────────────────────────────────────────────

def test_persist_session_progress_writes_db():
    sid = str(uuid.uuid4())
    _seed_session(sid)
    ms.persist_session_progress(sid, stage="verifying", reflection_iter=3)
    row = _read_session(sid)
    assert row["stage"] == "verifying"
    assert row["reflection_iter"] == 3


def test_persist_session_progress_partial_update():
    """只传 stage 不动 reflection_iter，反之亦然。"""
    sid = str(uuid.uuid4())
    _seed_session(sid)
    ms.persist_session_progress(sid, reflection_iter=5)
    ms.persist_session_progress(sid, stage="matching")
    row = _read_session(sid)
    assert row["stage"] == "matching" and row["reflection_iter"] == 5


def test_run_matching_persists_stage_and_resets_iter(monkeypatch):
    sid = str(uuid.uuid4())
    folder = "/data/persist"
    _seed_session(sid, folder)
    # 预置一个非零反思轮次，验证开跑时被归零
    ms.persist_session_progress(sid, reflection_iter=9)
    with _connect() as conn:
        conn.execute(
            """INSERT INTO dd_match_items (id, session_id, item_no, category, requirement)
               VALUES (?, ?, '1', '财务', '审计报告')""", (str(uuid.uuid4()), sid))
        conn.execute(
            """INSERT INTO dd_asset_index
               (id, folder_root, file_path, filename, file_type, summary, readable, indexed_at)
               VALUES (?, ?, ?, 'a.pdf', '.pdf', 's', 1, ?)""",
            (str(uuid.uuid4()), folder, f"{folder}/a.pdf", time.time()))

    monkeypatch.setattr(ms, "_llm_batch_match", lambda items, t, rows, **k: {})
    monkeypatch.setattr(ms, "_apply_decision_memory", lambda *a, **k: 0)
    monkeypatch.setattr(ms, "_refine_session_matches", lambda sid_: None)

    ms.run_matching(sid, folder)
    row = _read_session(sid)
    assert row["status"] == "matched"
    assert row["stage"] == "done"          # 终态落库
    assert row["reflection_iter"] == 0     # 开跑归零


def test_run_matching_failure_marks_stage_failed(monkeypatch):
    sid = str(uuid.uuid4())
    folder = "/data/fail"
    _seed_session(sid, folder)
    with _connect() as conn:
        conn.execute(
            """INSERT INTO dd_match_items (id, session_id, item_no, category, requirement)
               VALUES (?, ?, '1', '财务', 'x')""", (str(uuid.uuid4()), sid))
        conn.execute(
            """INSERT INTO dd_asset_index
               (id, folder_root, file_path, filename, file_type, summary, readable, indexed_at)
               VALUES (?, ?, ?, 'a.pdf', '.pdf', 's', 1, ?)""",
            (str(uuid.uuid4()), folder, f"{folder}/a.pdf", time.time()))

    def _boom(*a, **k):
        raise RuntimeError("匹配崩溃")
    monkeypatch.setattr(ms, "_llm_batch_match", _boom)

    ms.run_matching(sid, folder)
    row = _read_session(sid)
    assert row["status"] == "failed" and row["stage"] == "failed"


# ── 地基 2：决策记忆幂等化 ────────────────────────────────────────────

def _mem_count(norm_substr: str) -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT confirm_count FROM dd_decision_memory WHERE requirement_norm LIKE ?",
            (f"%{norm_substr}%",),
        ).fetchone()
    return row["confirm_count"] if row else 0


def test_record_decisions_idempotent_on_rerun():
    """同一 session 重跑（resume/重复 export）不重复计数。"""
    sid = str(uuid.uuid4())
    _seed_session(sid)
    _add_item(sid, "2023年审计报告", "/data/f/审计2023.pdf", confirmed=1)

    n1 = ms.record_session_decisions(sid)
    n2 = ms.record_session_decisions(sid)   # 重入
    n3 = ms.record_session_decisions(sid)   # 再重入
    assert n1 == 1
    assert n2 == 0 and n3 == 0              # 不再计数
    assert _mem_count("2023") == 1          # 记忆只 +1，未被双计


def test_record_decisions_counts_newly_confirmed_only():
    """后来又确认了一条再导出：只计入新确认的那条，老的不重复。"""
    sid = str(uuid.uuid4())
    _seed_session(sid)
    _add_item(sid, "营业执照", "/data/f/执照.pdf", confirmed=1)
    assert ms.record_session_decisions(sid) == 1

    # 用户随后确认第二条
    _add_item(sid, "公司章程", "/data/f/章程.pdf", confirmed=1)
    n = ms.record_session_decisions(sid)
    assert n == 1                            # 只计新确认的一条
    assert _mem_count("营业执照") == 1       # 老的没被再 +1


def test_decisions_recorded_flag_set():
    """沉淀后 decisions_recorded 置 1（幂等键落位）。"""
    sid = str(uuid.uuid4())
    _seed_session(sid)
    iid = _add_item(sid, "验资报告", "/data/f/验资.pdf", confirmed=1)
    ms.record_session_decisions(sid)
    with _connect() as conn:
        flag = conn.execute(
            "SELECT decisions_recorded FROM dd_match_items WHERE id = ?", (iid,),
        ).fetchone()[0]
    assert flag == 1
