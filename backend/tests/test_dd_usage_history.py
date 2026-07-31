"""材料使用履历（get_file_usage_history）测试。

覆盖：同一份文件被多个机构在不同尽调 session 里选中 → 反查能列出全部机构/清单。
"""
from __future__ import annotations

from cangjie_fos.services.dd_match_service import (
    create_match_session,
    get_file_usage_history,
)
from cangjie_fos.services.db_base import _connect


def _seed_session(institution_name: str, checklist_name: str, filename: str, file_path: str) -> str:
    sid = create_match_session(
        tenant_id="t1",
        checklist_name=checklist_name,
        folder_root="/materials",
        items=[{"item_no": 1, "category": "财务", "requirement": "审计报告"}],
        institution_name=institution_name,
    )
    with _connect() as conn:
        conn.execute(
            "UPDATE dd_match_items SET matched_file_path=?, matched_filename=?, "
            "confidence=0.9, user_confirmed=1 WHERE session_id=?",
            (file_path, filename, sid),
        )
    return sid


def test_usage_history_lists_all_institutions():
    """同一文件被 红杉 和 高瓴 两个 session 选中 → 反查返回 2 条。"""
    _seed_session("红杉资本", "红杉尽调清单", "2023审计报告.pdf", "/materials/A/2023审计报告.pdf")
    _seed_session("高瓴资本", "高瓴尽调清单", "2023审计报告.pdf", "/materials/B/2023审计报告.pdf")

    history = get_file_usage_history("2023审计报告.pdf")
    assert len(history) == 2
    institutions = {h["institution_name"] for h in history}
    assert institutions == {"红杉资本", "高瓴资本"}


def test_usage_history_matches_by_basename():
    """传完整路径也能命中（按 basename 匹配）。"""
    _seed_session("民生证券", "清单", "股权结构表.xlsx", "/materials/C/股权结构表.xlsx")
    history = get_file_usage_history("/some/other/root/股权结构表.xlsx")
    assert len(history) == 1
    assert history[0]["institution_name"] == "民生证券"


def test_usage_history_empty_for_unknown_file():
    assert get_file_usage_history("不存在的文件.pdf") == []
    assert get_file_usage_history("") == []


def test_wiki_endpoint_includes_dd_usage():
    """/assets/wiki 端点应带出 dd_usage / dd_institutions 字段。"""
    from fastapi.testclient import TestClient
    from cangjie_fos.main import create_app

    _seed_session("红杉资本", "清单", "商业计划书.pdf", "/materials/A/商业计划书.pdf")
    with TestClient(create_app()) as client:
        r = client.get("/api/v1/assets/wiki/商业计划书.pdf")
        assert r.status_code == 200
        body = r.json()
        assert "dd_usage" in body
        assert "dd_institutions" in body
        assert "红杉资本" in body["dd_institutions"]
