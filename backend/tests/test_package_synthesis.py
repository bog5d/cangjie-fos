"""需求03 — 引导提问 + AI 合成（含事实护栏）测试。"""
from __future__ import annotations

from cangjie_fos.services import package_gap_service as gap
from cangjie_fos.services import package_synthesis_service as synth


def test_generate_questions(monkeypatch):
    monkeypatch.setattr(synth, "_llm_questions",
                        lambda req, cat: ["注册号是多少？", "成立日期？", "注册资本？"])
    qs = synth.generate_guiding_questions("营业执照", "财务")
    assert len(qs) == 3
    assert "注册号是多少？" in qs


def test_generate_questions_fallback(monkeypatch):
    monkeypatch.setattr(synth, "_llm_questions", lambda req, cat: [])
    qs = synth.generate_guiding_questions("某材料", "业务")
    assert len(qs) == 1
    assert "某材料" in qs[0]  # 兜底引导含需求名


def test_synthesize_keeps_grounded_numbers(monkeypatch):
    monkeypatch.setattr(synth, "_llm_synthesize",
                        lambda req, frag, ex, cat: "公司成立于2020年，注册资本500万元。")
    r = synth.synthesize_material("营业执照", "2020年成立，注册资本500万", "")
    assert "2020" in r["draft"]
    assert "500" in r["draft"]
    assert r["dropped_numbers"] == []


def test_synthesize_drops_fabricated_numbers(monkeypatch):
    # 素材里只有 500万，LLM 却编出 3000万员工持股 + 78%增长
    monkeypatch.setattr(
        synth, "_llm_synthesize",
        lambda req, frag, ex, cat: (
            "公司注册资本500万元。\n员工持股平台规模3000万元。\n年增长率达78%。"
        ),
    )
    r = synth.synthesize_material("公司概况", "注册资本500万", "")
    assert "500" in r["draft"]
    assert "3000" not in r["draft"]   # 编造数字所在句被整句剔除
    assert "78" not in r["draft"]
    assert set(r["dropped_numbers"]) == {"3000", "78"}


def test_synthesize_empty_returns_blank():
    r = synth.synthesize_material("营业执照", "", "")
    assert r["draft"] == ""
    assert r["dropped_numbers"] == []


def test_synthesize_for_item_persists(monkeypatch):
    sess = gap.create_session("zt", "/data/syn")
    item_id = gap.list_items(sess["session_id"])[0]["id"]
    monkeypatch.setattr(synth, "_llm_synthesize",
                        lambda req, frag, ex, cat: "整理后的材料正文。")
    r = synth.synthesize_for_item(item_id, "一些零碎信息")
    assert r["draft"] == "整理后的材料正文。"
    # 片段 + 初稿都落库
    items = {it["id"]: it for it in gap.list_items(sess["session_id"])}
    assert items[item_id]["user_fragments"] == "一些零碎信息"
    assert items[item_id]["draft_answer"] == "整理后的材料正文。"
