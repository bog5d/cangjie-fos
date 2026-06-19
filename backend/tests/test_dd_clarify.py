"""解析后人类在环（HITL）澄清服务测试（DB 隔离 + LLM mock）。"""
from __future__ import annotations

import pytest

from cangjie_fos.services import dd_clarify_service as clarify
from cangjie_fos.services.dd_match_service import create_match_session
from cangjie_fos.services.db_base import _connect


def _mk_session(context_note: str = "") -> str:
    items = [
        {"item_no": "1", "category": "财务", "requirement": "泽天湖南2021年12月增值税申报表"},
        {"item_no": "2", "category": "财务", "requirement": "泽天湖南2022年12月增值税申报表"},
        {"item_no": "3", "category": "业务", "requirement": "商业计划书"},
    ]
    return create_match_session("zt", "清单", "/data/x", items,
                                institution_name="A", context_note=context_note)


_FAKE_Q = [
    {"question": "材料含『泽天湖南』和『四川』两个主体，如何处理？",
     "options": ["分主体匹配", "视为同一项目"], "allow_multi": False},
    {"question": "“增值税申报表”要哪一年？", "options": ["2021", "2022", "都要"], "allow_multi": True},
    {"question": "", "options": ["x"]},  # 非法：无 question / 选项不足 → 应被剔
]


def test_parse_summary_counts():
    s = clarify.parse_summary([
        {"category": "财务", "requirement": "a"},
        {"category": "财务", "requirement": "b"},
        {"category": "业务", "requirement": "c"},
    ])
    assert s["total"] == 3
    assert s["by_category"] == {"财务": 2, "业务": 1}


def test_generate_clarifications(monkeypatch):
    monkeypatch.setattr(clarify, "_llm_clarify", lambda items, ctx: [dict(q) for q in _FAKE_Q])
    sid = _mk_session()
    out = clarify.generate_clarifications(sid)
    assert out["summary"]["total"] == 3
    # 非法题被剔，剩 2
    assert len(out["questions"]) == 2
    assert all(q["id"] and len(q["options"]) >= 2 for q in out["questions"])
    # 落库可读回
    assert clarify.get_clarifications(sid)["questions"][0]["question"].startswith("材料含")


def test_generate_unknown_session_raises(monkeypatch):
    monkeypatch.setattr(clarify, "_llm_clarify", lambda i, c: [])
    with pytest.raises(ValueError):
        clarify.generate_clarifications("nope")


def test_submit_answers_appends_to_context(monkeypatch):
    monkeypatch.setattr(clarify, "_llm_clarify", lambda items, ctx: [dict(q) for q in _FAKE_Q])
    sid = _mk_session(context_note="原始背景")
    out = clarify.generate_clarifications(sid)
    qid0 = out["questions"][0]["id"]
    qid1 = out["questions"][1]["id"]

    res = clarify.submit_answers(sid, {qid0: "分主体匹配", qid1: "2021、2022"})
    assert res["answered"] == 2

    with _connect() as conn:
        ctx = conn.execute(
            "SELECT context_note FROM dd_match_sessions WHERE session_id = ?", (sid,),
        ).fetchone()["context_note"]
    # 原背景保留 + 澄清补充追加，匹配 prompt 会自动吃到
    assert "原始背景" in ctx
    assert "【人工澄清补充】" in ctx
    assert "分主体匹配" in ctx and "2021、2022" in ctx


def test_resubmit_replaces_not_accumulates(monkeypatch):
    """重答应替换旧澄清块，不累积。"""
    monkeypatch.setattr(clarify, "_llm_clarify", lambda items, ctx: [dict(q) for q in _FAKE_Q])
    sid = _mk_session(context_note="背景X")
    out = clarify.generate_clarifications(sid)
    qid0 = out["questions"][0]["id"]

    clarify.submit_answers(sid, {qid0: "分主体匹配"})
    clarify.submit_answers(sid, {qid0: "视为同一项目"})

    with _connect() as conn:
        ctx = conn.execute(
            "SELECT context_note FROM dd_match_sessions WHERE session_id = ?", (sid,),
        ).fetchone()["context_note"]
    assert ctx.count("【人工澄清补充】") == 1  # 只有一块
    assert "视为同一项目" in ctx
    assert "分主体匹配" not in ctx
    assert "背景X" in ctx


def test_llm_failure_returns_no_questions(monkeypatch):
    """LLM 故障不阻断：澄清生成失败 → 返回空题目，流程仍可继续（凭现状走）。"""
    def _boom():
        raise RuntimeError("LLM down")
    monkeypatch.setattr(clarify, "get_dd_llm_client", _boom)
    assert clarify._llm_clarify([{"requirement": "x"}], "") == []


# ── API 层 e2e ────────────────────────────────────────────────

def test_clarify_endpoints_e2e(monkeypatch):
    from fastapi.testclient import TestClient
    from cangjie_fos.main import create_app
    monkeypatch.setattr(clarify, "_llm_clarify", lambda items, ctx: [dict(q) for q in _FAKE_Q])
    c = TestClient(create_app(), raise_server_exceptions=False)
    sid = _mk_session(context_note="背景")

    # 生成
    r = c.post(f"/api/v1/dd/sessions/{sid}/clarify")
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["total"] == 3 and len(body["questions"]) == 2
    qid = body["questions"][0]["id"]

    # 读取
    assert c.get(f"/api/v1/dd/sessions/{sid}/clarify").status_code == 200

    # 回答 → 回灌 context_note
    r2 = c.post(f"/api/v1/dd/sessions/{sid}/clarify/answers",
                json={"answers": {qid: "分主体匹配"}})
    assert r2.status_code == 200 and r2.json()["answered"] == 1

    # 404 路径
    assert c.post("/api/v1/dd/sessions/nope/clarify").status_code == 404
    assert c.get("/api/v1/dd/sessions/nope/clarify").status_code == 404
