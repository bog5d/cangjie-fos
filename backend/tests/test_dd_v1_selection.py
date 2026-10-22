"""DD-V1 精确选中规则测试（A3 · G-A3-2）。

## 判据对应

**A3-2**（精确集合）：

- 一条义务有 5 个同类型 deliverable 候选 → 交付集合**只含选中的那 1 份**（+ 必备附件）；
- 核对表里逐条列出「选了什么、为什么选它、其余为什么没选」；
- **不选中的候选**进「未选用」清单（可审计），**不得**出现在交付目录；
- 同一目录下**不得**出现「同目录顺带复制」的无关材料。

★ 「确定性可复现」是硬要求：同一输入 ⇒ 同一集合（逐字一致）。
"""
from __future__ import annotations

from cangjie_fos.services import dd_v1_selection_service as selsvc


def _cand(fid, score=1.0, deliverable=True, entity_ok=1, period_ok=1,
          doctype_ok=1, rel=None):
    return {
        "file_id": fid,
        "card_rel_path": rel or f"子公司甲/{fid}.txt",
        "card_title": fid,
        "score": score,
        "deliverable": deliverable,
        "entity_ok": entity_ok,
        "period_ok": period_ok,
        "doctype_ok": doctype_ok,
        "attachment_ok": 0,
        "evidence": "[]",
    }


def _five():
    return [_cand(f"f{i}", score=0.75) for i in range(1, 6)]


# ── 核心：5 个同类型候选 → 只交 1 份 ─────────────────────────────────────
def test_five_candidates_yield_exactly_one_selected():
    out = selsvc.select_for_obligation({"expected_count": 0}, _five())
    assert len(out["selected"]) == 1, "★ 交付集合只含选中的那 1 份"
    assert len(out["unselected"]) == 4
    assert out["target"] == 1
    assert "未规定" in out["target_reason"]


def test_unselected_entries_all_carry_a_reason():
    """「不交」是决定，「不解释」是失职 ⇒ 每一条都必须有理由。"""
    out = selsvc.select_for_obligation({"expected_count": 0}, _five())
    for u in out["unselected"]:
        assert u["reason"], f"未选用项缺理由：{u}"
        assert u["file_id"] and u["rel_path"]


def test_selected_entry_states_why_it_was_chosen():
    out = selsvc.select_for_obligation({"expected_count": 0}, _five())
    p = out["selected"][0]
    assert p["role"] == "主件"
    assert "选中规则" in p["reason"]


# ── 确定性可复现 ──────────────────────────────────────────────────────────
def test_selection_is_byte_identical_across_runs():
    a = selsvc.select_for_obligation({"expected_count": 0}, _five())
    b = selsvc.select_for_obligation({"expected_count": 0}, _five())
    assert a == b


def test_tiebreak_is_file_id_ascending():
    """同分 ⇒ 按 file_id 升序（稳定化 ⇒ 可逐字复现）。"""
    cands = [_cand("f9", score=0.5), _cand("f1", score=0.5), _cand("f5", score=0.5)]
    out = selsvc.select_for_obligation({"expected_count": 0}, cands)
    assert out["selected"][0]["file_id"] == "f1"


def test_period_match_breaks_tie():
    """同分时先比主体、再比期间、再比类型。"""
    cands = [_cand("a", score=0.75, period_ok=0),
             _cand("b", score=0.75, period_ok=1)]
    out = selsvc.select_for_obligation({"expected_count": 0}, cands)
    assert out["selected"][0]["file_id"] == "b"


# ── 份数决定「交几份」 ────────────────────────────────────────────────────
def test_expected_count_two_selects_two():
    out = selsvc.select_for_obligation({"expected_count": 2}, _five())
    assert out["target"] == 2
    assert len(out["selected"]) == 2
    assert len(out["unselected"]) == 3


def test_undeterminable_count_selects_nothing_and_flags_pending():
    """★ 不得默认 1 份：份数不可判定 ⇒ 不擅自交付，列入待人工确认。"""
    out = selsvc.select_for_obligation({"expected_count": None}, _five())
    assert out["target"] == 0
    assert out["selected"] == []
    assert out["count_pending"] is True
    assert "不得默认 1 份" in out["target_reason"]


def test_count_beyond_available_takes_what_exists():
    out = selsvc.select_for_obligation({"expected_count": 9}, _five())
    assert len(out["selected"]) == 5
    assert len(out["unselected"]) == 0


# ── 交付资格与附件 ────────────────────────────────────────────────────────
def test_non_deliverable_candidate_is_never_selected():
    cands = _five()
    cands[0]["deliverable"] = False
    cands[0]["evidence"] = '["披露不可外发（等级=RESTRICTED）：不可外发"]'
    out = selsvc.select_for_obligation({"expected_count": 0}, cands)
    assert all(p["file_id"] != cands[0]["file_id"] for p in out["selected"])
    blocked = [u for u in out["unselected"] if u["file_id"] == cands[0]["file_id"]]
    assert blocked and "不可交付" in blocked[0]["reason"]


def test_explicit_attachment_is_included():
    """必备附件**只认** related_files 显式列出的文件。"""
    main = _cand("m1", rel="子公司甲/审计报告2023.txt")
    att = _cand("m2", rel="子公司甲/审计报告2023_附件.txt")
    other = _cand("m3", rel="子公司甲/营业执照.txt")
    out = selsvc.select_for_obligation(
        {"expected_count": 0}, [main, att, other],
        related={"m1": ["子公司甲/审计报告2023_附件.txt"]})
    ids = {p["file_id"] for p in out["selected"]}
    assert "m1" in ids and "m2" in ids, "显式附件必须入选"
    assert "m3" not in ids, "没被列出的同目录材料不得顺带进包"
    roles = {p["file_id"]: p["role"] for p in out["selected"]}
    assert roles["m2"] == "必备附件"


def test_unrelated_same_folder_material_is_not_selected():
    """同目录顺带复制是老实现的病 ⇒ 必须在选中层被挡住。"""
    cands = [_cand("k1", rel="子公司甲/审计报告2023.txt"),
             _cand("k2", rel="子公司甲/审计报告2022.txt"),
             _cand("k3", rel="子公司甲/营业执照.txt"),
             _cand("k4", rel="子公司甲/公司章程.txt"),
             _cand("k5", rel="子公司甲/纳税凭证.txt")]
    out = selsvc.select_for_obligation({"expected_count": 0}, cands)
    assert len(out["selected"]) == 1
    assert {u["file_id"] for u in out["unselected"]} == {"k2", "k3", "k4", "k5"}
