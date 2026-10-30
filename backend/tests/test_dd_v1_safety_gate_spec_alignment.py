"""安全闸与**冻结评分规范**的一致性（独立 Reviewer 第 3 轮 MAJOR-1 的永久回归）。

★ **要防的坑**：冻结规范 `dd_v1_exam_scoring_spec.v1.json` 的 `safety.counted_kinds`
  明列 `WRONG_PERIOD`（错年度），且「命中任一 ⇒ ``safety_gate=FAIL`` ＋ 总分封顶 **59**」。
  但实现此前把「错年度」**完全排除在安全闸外** ⇒
  **错年度交付可以拿 100 分且 ``safety_gate=PASS``** ⇒ **实现比尺子松**。

⇒ 本文件把「**实现必须与冻结规范一致**」钉死，并锁住两条边界：
  ① 「口径不可比」（``CURRENT``/``当前``/``未知``）⇒ **不判**错年度（不冤枉机器）；
  ② 「选中但未交付」⇒ **只单列、不封顶**（与 ``WRONG_ENTITY`` 同口径，验收项 D6 的既有断言）。

全部夹具为**合成数据**（虚构主体名、假 SHA256），不跑真实模型、不联网。
"""
from __future__ import annotations

import json
from pathlib import Path

from cangjie_fos.services import dd_v1_exam_service as ex
from cangjie_fos.services import dd_v1_gold_service as gold_svc

#: 冻结规范里的安全闸计数项（**尺子在这里**）
SPEC = json.loads((Path(__file__).resolve().parents[1] / "config"
                   / "dd_v1_exam_scoring_spec.v1.json").read_text("utf-8"))
COUNTED_KINDS = tuple(SPEC.get("safety", {}).get("counted_kinds") or ())
CAP_ON_FAIL = int(SPEC.get("safety", {}).get("cap_on_fail") or 59)

# ── 合成图书馆 ──────────────────────────────────────────────────────────────
SHA_F1 = "a" * 64      # 主体甲 2024 审计报告（正确件）
SHA_F5 = "b" * 64      # 主体甲 2023 审计报告（**同主体、错年度** ⇒ 专门打 WRONG_PERIOD）

META = [
    {"file_id": "F1", "sha256": SHA_F1, "relative_path": "主体甲/2024审计报告.pdf",
     "entity": "主体甲", "entity_basis": "AUTHORITY", "period": "2024",
     "doc_type": "audit_report", "part": "正文", "version_status": "EFFECTIVE"},
    {"file_id": "F5", "sha256": SHA_F5, "relative_path": "主体甲/2023审计报告.pdf",
     "entity": "主体甲", "entity_basis": "AUTHORITY", "period": "2023",
     "doc_type": "audit_report", "part": "正文", "version_status": "EFFECTIVE"},
]


def _gold_manifest() -> dict:
    return {
        "schema_version": gold_svc.GOLD_MANIFEST_SCHEMA,
        "gold_pack_id": "GOLD-SAFETY-01",
        "exam_id": "EX-SAFETY-01",
        "checklist": {"checklist_id": "CL-SAFETY", "sha256": "f" * 64, "item_count": 1},
        "library": {"library_id": "LIB-SAFETY", "fingerprint": "0" * 64, "material_count": len(META)},
        "confirmed_by": "测试员",
        "confirmed_at": "2026-10-30T00:00:00+08:00",
        "items": [{"obligation_id": "O1", "item_no": "1-1", "expected_verdict": "MATCH",
                   "expected_files": [{"sha256": SHA_F1, "entity": "主体甲", "period": "2024",
                                        "doc_type": "audit_report"}]}],
    }


def _sheet(delivered: list[dict], selected: list[dict] | None = None) -> dict:
    """最小答卷：一条义务，**选中**与**交付**分开给。"""
    return {
        "schema_version": "dd_v1_answer_sheet.v1",
        "exam_id": "EX-SAFETY-01",
        "obligations": [{
            "obligation_id": "O1", "item_no": "1-1",
            "interpretation": {"resolved": True, "doc_type": "audit_report"},
            "selected": selected if selected is not None else [],
            "delivered": delivered,
            "verdict": "MATCH", "confidence": 0.9, "abstain_reason": None,
        }],
        "summary": {"obligations": 1, "delivered_files": len(delivered)},
    }


def _grade(sheet: dict) -> dict:
    idx = gold_svc.index_from_snapshot(None, META)
    return ex.grade_answer_sheet(sheet, _gold_manifest(), library_index=idx,
                                 min_obligations=1)


def _delivered(fid: str, **extra) -> list[dict]:
    d = {"file_id": fid, "delivered_path": f"交付/{fid}", "source_sha256": "",
         "copy_sha256": "", "hash_match": True, "approved": True}
    d.update(extra)
    return [d]


# ─────────────────────────────────────────────────── 尺子本身

def test_frozen_spec_counts_wrong_period():
    """★ 前置：冻结规范确实把 ``WRONG_PERIOD`` 列为安全闸计数项（否则下面断言无意义）。"""
    assert "WRONG_PERIOD" in COUNTED_KINDS, COUNTED_KINDS
    assert CAP_ON_FAIL == 59


# ─────────────────────────────────────────────────── MAJOR-1 的核心

def test_delivered_wrong_period_enters_safety_gate_and_caps():
    """★ **交付**了错年度（2023，该交 2024）的材料 ⇒ 进安全闸 ⇒ FAIL ＋ 封顶 59。"""
    sheet = _sheet(_delivered("F5"))
    card = _grade(sheet)
    gate = card["safety_gate"]
    assert gate["status"] == "FAIL", gate
    assert gate["by_kind"].get("WRONG_PERIOD") == 1, gate
    assert card["scores"]["total_score"] <= CAP_ON_FAIL, card["scores"]


def test_delivered_wrong_period_recorded_in_sheet_also_caps():
    """★ 答卷里记录的期间与 Gold 不同（同一 file_id）⇒ 同样进闸。"""
    sheet = _sheet(_delivered("F1", period="2023"))
    card = _grade(sheet)
    gate = card["safety_gate"]
    assert gate["status"] == "FAIL", gate
    assert gate["by_kind"].get("WRONG_PERIOD") == 1, gate


def test_uncomparable_period_is_not_judged():
    """★ **口径不可比**（``CURRENT``/``当前``/``未知``）⇒ **不判**错年度（不冤枉机器）。"""
    for marker in ("CURRENT", "当前", "未知"):
        sheet = _sheet(_delivered("F1", period=marker))
        gate = _grade(sheet)["safety_gate"]
        assert gate["by_kind"].get("WRONG_PERIOD", 0) == 0, (marker, gate["by_kind"])
        assert gate["status"] == "PASS", (marker, gate)


def test_selected_but_not_delivered_wrong_period_does_not_cap():
    """★ 「选中但未交付」的错年度 ⇒ **只单列、不封顶**（与 WRONG_ENTITY 同口径）。"""
    sheet = _sheet([], selected=[{"file_id": "F5", "entity": "主体甲", "period": "2023"}])
    gate = _grade(sheet)["safety_gate"]
    assert gate["by_kind"].get("WRONG_PERIOD", 0) == 0, gate["by_kind"]
    assert gate["status"] == "PASS", gate
    assert gate["selection_mismatch_by_kind"].get("WRONG_PERIOD") == 1, gate


# ─────────────────────────────────────────────────── 回归护栏（既有口径不得被带偏）

def test_wrong_entity_still_caps():
    """★ ``WRONG_ENTITY`` 的既有口径**不得**被本次修改带偏。"""
    sheet = _sheet(_delivered("F5", entity="主体乙"))
    card = _grade(sheet)
    gate = card["safety_gate"]
    assert gate["status"] == "FAIL", gate
    assert gate["by_kind"].get("WRONG_ENTITY") == 1, gate["by_kind"]
    assert card["scores"]["total_score"] <= CAP_ON_FAIL


def test_hash_mismatch_still_caps():
    """★ ``HASH_MISMATCH`` 仍然进闸封顶。"""
    sheet = _sheet(_delivered("F1", hash_match=False))
    card = _grade(sheet)
    gate = card["safety_gate"]
    assert gate["by_kind"].get("HASH_MISMATCH") == 1, gate["by_kind"]
    assert gate["status"] == "FAIL", gate


def test_clean_run_still_passes():
    """★ 没有违规时安全闸**必须** PASS（不许因为修 MAJOR-1 变成常态红）。"""
    sheet = _sheet(_delivered("F1"))
    gate = _grade(sheet)["safety_gate"]
    assert gate["status"] == "PASS", gate
    assert gate["violations"] == 0, gate
