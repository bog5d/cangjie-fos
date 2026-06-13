"""v1.17.0 工作流可视化 — run_matching 阶段回调（粗筛→精判）测试。"""
from __future__ import annotations

import time
import uuid

from cangjie_fos.services import dd_match_service as ms
from cangjie_fos.services.db_base import _connect


def _seed(session_id: str, folder: str):
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO dd_match_sessions
               (session_id, tenant_id, checklist_name, folder_root, status, created_at)
               VALUES (?, 'zt', 'c', ?, 'pending', ?)""",
            (session_id, folder, now),
        )
        conn.execute(
            """INSERT INTO dd_match_items (id, session_id, item_no, category, requirement)
               VALUES (?, ?, '1', '财务', '审计报告')""",
            (str(uuid.uuid4()), session_id),
        )
        conn.execute(
            """INSERT INTO dd_asset_index
               (id, folder_root, file_path, filename, file_type, summary, readable, indexed_at)
               VALUES (?, ?, ?, '审计报告.pdf', '.pdf', '审计', 1, ?)""",
            (str(uuid.uuid4()), folder, f"{folder}/审计报告.pdf", now),
        )


def test_run_matching_emits_stages(monkeypatch):
    folder = "/data/stage"
    sid = str(uuid.uuid4())
    _seed(sid, folder)

    monkeypatch.setattr(ms, "_llm_batch_match", lambda items, t, rows, **k: {})
    monkeypatch.setattr(ms, "_apply_decision_memory", lambda *a, **k: 0)
    monkeypatch.setattr(ms, "_refine_session_matches", lambda sid_: None)

    stages: list[str] = []
    ms.run_matching(sid, folder, stage_callback=lambda s: stages.append(s))

    # 至少先粗筛、后精判
    assert "matching" in stages
    assert "verifying" in stages
    assert stages.index("matching") < stages.index("verifying")


def test_run_matching_no_callback_still_works(monkeypatch):
    """不传 stage_callback 时（旧调用方）不报错。"""
    folder = "/data/stage2"
    sid = str(uuid.uuid4())
    _seed(sid, folder)
    monkeypatch.setattr(ms, "_llm_batch_match", lambda items, t, rows, **k: {})
    monkeypatch.setattr(ms, "_apply_decision_memory", lambda *a, **k: 0)
    monkeypatch.setattr(ms, "_refine_session_matches", lambda sid_: None)
    ms.run_matching(sid, folder)  # 不应抛
    with _connect() as conn:
        st = conn.execute("SELECT status FROM dd_match_sessions WHERE session_id=?", (sid,)).fetchone()[0]
    assert st == "matched"
