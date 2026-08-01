"""尽调台诊断模式（G1）测试。

验证逐条环节判定：粗筛漏召回 / 库里没有 / 正文读不出 / 精判拒 / 已确认。
"""
from __future__ import annotations

import time

from cangjie_fos.services.dd_match_service import create_match_session, diagnose_session
from cangjie_fos.services.db_base import _connect


def _index_file(folder_root, file_path, filename, summary="", content_text=""):
    with _connect() as conn:
        conn.execute(
            """INSERT INTO dd_asset_index
               (id, folder_root, file_path, filename, file_type, summary, readable,
                indexed_at, content_text)
               VALUES (?, ?, ?, ?, '.pdf', ?, 1, ?, ?)""",
            (file_path, folder_root, file_path, filename, summary, time.time(), content_text),
        )


def _set_item(sid, item_no, **cols):
    sets = ", ".join(f"{k}=?" for k in cols)
    with _connect() as conn:
        conn.execute(
            f"UPDATE dd_match_items SET {sets} WHERE session_id=? AND item_no=?",
            (*cols.values(), sid, item_no),
        )


def _mk_session(folder="/mat"):
    return create_match_session(
        tenant_id="t1", checklist_name="清单", folder_root=folder,
        items=[
            {"item_no": 1, "requirement": "公司营业执照"},   # 会命中且有正文
            {"item_no": 2, "requirement": "近三年审计报告"},  # 命中但无正文
            {"item_no": 3, "requirement": "股权结构表"},      # 未匹配但库里有相关
            {"item_no": 4, "requirement": "法定代表人身份证"},  # 库里完全没有相关
        ],
        institution_name="红杉",
    )


def test_diagnose_classifies_each_stage():
    folder = "/mat"
    sid = _mk_session(folder)
    # 建索引：营业执照（有正文）、审计报告（无正文）、股权结构表（相关但没被选）
    _index_file(folder, "/mat/营业执照.pdf", "营业执照.pdf", content_text="统一社会信用代码…")
    _index_file(folder, "/mat/2023审计报告.pdf", "审计报告.pdf", content_text="")  # 图片型，无正文
    _index_file(folder, "/mat/股权结构表.xlsx", "股权结构表.xlsx", content_text="股东名册")

    # item1 命中营业执照 + 绿
    _set_item(sid, 1, matched_file_path="/mat/营业执照.pdf", matched_filename="营业执照.pdf",
              confidence=0.9, verdict="green")
    # item2 命中审计报告 但该文件无正文
    _set_item(sid, 2, matched_file_path="/mat/2023审计报告.pdf", matched_filename="审计报告.pdf",
              confidence=0.5)
    # item3 未匹配（matched_file_path 空）——但库里有"股权结构表"
    # item4 未匹配——库里没有体检报告

    result = diagnose_session(sid)
    by_no = {int(d["item_no"]): d for d in result["items"]}
    assert by_no[1]["stage"] == "matched_green"
    assert by_no[2]["stage"] == "no_content"
    assert by_no[3]["stage"] == "prefilter_miss"
    assert "股权结构表.xlsx" in by_no[3]["candidates"]
    assert by_no[4]["stage"] == "not_in_library"
    assert result["total"] == 4
    assert result["stage_counts"]["no_content"] == 1


def test_diagnose_confirmed_item():
    folder = "/mat2"
    sid = create_match_session(
        tenant_id="t1", checklist_name="c", folder_root=folder,
        items=[{"item_no": 1, "requirement": "公司章程"}], institution_name="高瓴")
    _index_file(folder, "/mat2/章程.pdf", "章程.pdf", content_text="第一章…")
    _set_item(sid, 1, matched_file_path="/mat2/章程.pdf", matched_filename="章程.pdf",
              confidence=0.9, user_confirmed=1)
    result = diagnose_session(sid)
    assert result["items"][0]["stage"] == "ok_confirmed"


def test_diagnose_judge_reject():
    folder = "/mat3"
    sid = create_match_session(
        tenant_id="t1", checklist_name="c", folder_root=folder,
        items=[{"item_no": 1, "requirement": "海外子公司审计报告"}], institution_name="软银")
    _index_file(folder, "/mat3/国内审计.pdf", "国内审计.pdf", content_text="境内主体审计")
    _set_item(sid, 1, matched_file_path="/mat3/国内审计.pdf", matched_filename="国内审计.pdf",
              confidence=0.2, verdict="red")
    result = diagnose_session(sid)
    assert result["items"][0]["stage"] == "judge_reject"


def test_diagnose_endpoint():
    from fastapi.testclient import TestClient
    from cangjie_fos.main import create_app

    sid = _mk_session("/mat4")
    with TestClient(create_app()) as c:
        r = c.get(f"/api/v1/dd/sessions/{sid}/diagnose")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 4
        assert "stage_counts" in body
        assert "overall_hint" in body


def test_diagnose_unknown_session():
    result = diagnose_session("nope")
    assert result["total"] == 0
