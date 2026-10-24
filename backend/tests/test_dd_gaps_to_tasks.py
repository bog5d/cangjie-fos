"""尽调缺口→跟进任务（F3a）测试。"""
from __future__ import annotations

from cangjie_fos.services.dd_match_service import create_match_session, create_tasks_from_gaps
from cangjie_fos.services.db_base import _connect
from cangjie_fos.services.pitch_job_db import db_follow_up_list


def _seed(institution="红杉资本"):
    sid = create_match_session(
        tenant_id="t1", checklist_name="清单", folder_root="/m",
        items=[
            {"item_no": 1, "requirement": "近三年审计报告"},
            {"item_no": 2, "requirement": "公司章程"},
            {"item_no": 3, "requirement": "专利证书"},
        ],
        institution_name=institution,
    )
    with _connect() as conn:
        # item1 匹配上文件（非缺口）
        conn.execute(
            "UPDATE dd_match_items SET matched_file_path='/m/审计.pdf', matched_filename='审计.pdf' "
            "WHERE session_id=? AND item_no=1", (sid,))
        # item2 人工标"缺"（缺口）
        conn.execute(
            "UPDATE dd_match_items SET user_skipped=1 WHERE session_id=? AND item_no=2", (sid,))
        # item3 未匹配（matched_file_path 空 → 缺口）
    return sid


def test_gaps_become_tasks():
    sid = _seed()
    n = create_tasks_from_gaps(sid)
    assert n == 2  # item2(标缺) + item3(未匹配)
    actions = {i["action"] for i in db_follow_up_list("t1", limit=100, include_done=True)}
    assert "补充尽调材料：公司章程" in actions
    assert "补充尽调材料：专利证书" in actions
    assert "补充尽调材料：近三年审计报告" not in actions  # 已匹配，非缺口


def test_gaps_idempotent():
    sid = _seed("高瓴")
    create_tasks_from_gaps(sid)
    second = create_tasks_from_gaps(sid)
    assert second == 0  # 已建过的不重复


def test_gaps_carry_institution():
    sid = _seed("民生证券")
    create_tasks_from_gaps(sid)
    items = db_follow_up_list("t1", limit=100, include_done=True)
    gap_items = [i for i in items if i.get("source") == "dd_gap"]
    assert gap_items
    assert all(i.get("institution_id") == "民生证券" for i in gap_items)


def test_endpoint_gaps_to_tasks():
    from fastapi.testclient import TestClient
    from cangjie_fos.main import create_app

    sid = _seed("软银")
    with TestClient(create_app()) as c:
        r = c.post(f"/api/v1/dd/sessions/{sid}/gaps-to-tasks")
        assert r.status_code == 200, r.text
        assert r.json()["created"] == 2
