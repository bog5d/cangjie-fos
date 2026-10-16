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
