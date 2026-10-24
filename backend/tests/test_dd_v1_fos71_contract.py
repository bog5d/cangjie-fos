"""cangjie-fos#71 WP02：Goal Contract 与代码常量一致性（防止合同与实现漂移）。"""
from __future__ import annotations

import json
from pathlib import Path

from cangjie_fos.services import dd_v1_agent_result_service as ar

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs" / "dd-v1-fos71" / "wp02" / "GOAL-CONTRACT-WP02.json"


def _c():
    return json.loads(CONTRACT.read_text("utf-8"))


def test_contract_header():
    c = _c()
    assert c["contract_version"] == "3.8" and c["task_level"] == "L1"


def test_contract_pins_current_schema_and_prompt_versions():
    ref = _c()["capability"]["effective_config_ref"]
    assert f"SCHEMA_VERSION={ar.SCHEMA_VERSION}" in ref
    assert f"PROMPT_VERSION={ar.PROMPT_VERSION}" in ref


def test_examinee_definitions_not_swapped():
    cands = {x["id"]: x for x in _c()["capability"]["candidates"]}
    assert "DeepSeek" in cands["EXAMINEE_3"]["definition"]
    assert cands["EXAMINEE_3"]["status"].startswith("UNAVAILABLE")
    assert "MiniMax" in cands["AUX_MINIMAX"]["definition"]
    assert "不计入考生3" in cands["AUX_MINIMAX"]["definition"]


def test_outcome_points_not_overclaimed():
    p = _c()["goal_alignment"]["progress"]
    assert p["outcome_verified_points"] == 0
    assert _c()["goal_alignment"]["baseline"]["status"] == "UNKNOWN"


# ---- 独立复核 WP02 N1–N4 ----
from cangjie_fos.services import dd_v1_agent_result_service as _ar  # noqa: E402,F401


def test_n1_scoring_rules_are_machine_readable():
    r = _c()["scoring_rules"]
    assert r["version"] == "fos71-scoring-v1"
    assert r["low_confidence_min_obligations"] == 30
    assert r["min_reruns"] == 3
    assert r["high_confidence_threshold"] == 0.8
    assert r["no_gold_status"] == "NOT_SCORABLE" and r["gold_required"] is True
    assert r["coverage_vs_correct_separate"] is True
    assert set(r["separate_counts"]) == {"wrong_entity", "wrong_period", "confident_mismatch"}


def test_n5_rerun_threshold_is_open_item_not_silently_set():
    c = _c()
    assert c["scoring_rules"]["rerun_agreement_threshold"] is None
    assert any(i["id"] == "WP05-PRE-1" and i["status"] == "OPEN" for i in c["open_items"])


def test_n2_engineering_percent_locked_to_reviewed_wps():
    p = _c()["goal_alignment"]["progress"]
    assert p["completed_reviewed_wps"] == ["WP00", "WP01"]
    assert p["total_wps"] == 8
    assert p["engineering_percent"] == round(100 * len(p["completed_reviewed_wps"]) / p["total_wps"])
    spec = (CONTRACT.parent / "SPEC-WP02.md").read_text("utf-8")
    assert "WP00、WP01 已完成并经独立复核 = 2/8 = 25%" in spec
    assert "WP00、WP01 已完成并经独立复核 = 2/8 = 25%" in p["note"]


def test_n3_r7_dimensions_and_error_categories():
    r = _c()["scoring_rules"]
    assert r["dimensions"] == ["entity", "period", "effective_version", "attachment",
                               "proof_original", "truly_missing", "unverifiable"]
    assert r["error_categories"] == ["RULE_DEFECT", "MODEL_REASONING_DEFECT", "RECALL_DEFECT", "MATERIAL_MISSING"]
    uva = " ".join(_c()["goal_alignment"]["user_visible_acceptance"])
    for w in ("证明原件", "无法核实", "规则缺陷", "模型推理缺陷", "召回缺陷", "资料缺失"):
        assert w in uva


def test_n4_structured_examinee_fields():
    cands = {x["id"]: x for x in _c()["capability"]["candidates"]}
    e1, e2, e3, aux = cands["EXAMINEE_1"], cands["EXAMINEE_2"], cands["EXAMINEE_3"], cands["AUX_MINIMAX"]
    assert (e1["vendor"], e1["uses_dd_v1"], e1["scored"], e1["ranked"]) == ("codex", False, True, True)
    assert (e2["vendor"], e2["uses_dd_v1"], e2["scored"], e2["ranked"]) == ("codex", True, True, True)
    assert e3["vendor"] == "deepseek-harness" and e3["score_status"] == "BLOCKED"
    assert aux["vendor"] == "minimax" and aux["scored"] is False and aux["ranked"] is False
    assert cands["CONTROL_RULE_ONLY"]["ranked"] is False


def test_wp03_n4_gold_not_on_executor_host_and_manual_not_examinee():
    c = _c()
    assert c["scoring_rules"]["gold_must_not_be_on_executor_host"] is True
    assert c["scoring_rules"]["manual_reply_counts_as_examinee"] is False
    assert any("执行器主机" in x for x in c["gate"]["acceptance_criteria"])
    assert "执行器主机任何可读位置" in (CONTRACT.parent / "SPEC-WP02.md").read_text("utf-8")
