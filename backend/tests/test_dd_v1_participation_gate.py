"""G8 真实模型参与门禁的回归测试（含**两类反例**）。

★ 这两类反例就是独立 Reviewer 亲手跑过、并且**穿透了旧实现**的那两个：
  A. 全 RULE_ONLY / 合成回放的旧证据 ⇒ 必须判 FAIL（`NO_REAL_MODEL_RUN_AT_ALL`）；
  B. 「参与信息塌缩成一个布尔值」（自报 participated=True）且身份 UNKNOWN
     ⇒ 必须判 FAIL（`MODEL_IDENTITY_UNVERIFIED`）。
⇒ 本文件的任务：证明**旧实现挡不住**、**新门禁挡得住**。

★ 为什么用 `unittest` 而不是 pytest：
  独立 Reviewer 那一轮实测 `pytest` 收集阶段就 BLOCKED
  （`ModuleNotFoundError: No module named 'pydantic'`，0 项执行、退出码 2）⇒
  **这条最关键的回归测试不能依赖任何第三方包** ⇒ 用 stdlib `unittest`
  （pytest 同样能收集 unittest 用例 ⇒ CI 侧零改动）。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from cangjie_fos.services.dd_v1_participation_gate import (
    AI_NOT_SCORED,
    GATE_MODEL_IDENTITY_UNVERIFIED,
    GATE_MODE_DOWNGRADED,
    GATE_NO_REAL_MODEL_RUN,
    MODE_AGENT_REQUIRED,
    MODE_AUTO,
    MODE_RULE_ONLY,
    PATH_AGENT,
    PATH_RULE,
    evaluate_participation_gate,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_RUN_RECORD = REPO_ROOT / "docs/dd-v1-fos71/wp03/runs/codex.run_record.json"


def _record_with_identity(model_id: str) -> dict:
    return {
        "adapter": {"adapter_id": "codex-cli", "vendor": "openai-codex",
                    "status": "OK", "raw_text": '{"results":[]}'},
        "validation": {
            "mode": "AGENT_SUGGESTION",
            "degrade_reason": None,
            "uncovered_obligations": [],
            "accepted": [{
                "item_id": "S1", "obligation_id": "S1-O1", "agent_id": "codex-cli",
                "provider": "openai-codex", "model_id_or_unknown": model_id,
                "proposed_verdict": "MATCH", "confidence_or_uncertain": "CONFIDENT",
            }],
            "rejected": [],
        },
    }


def _rule_only_record() -> dict:
    """全 RULE_ONLY 的合成回放产物（没有真实 adapter 记录 ⇒ 不是模型调用）。"""
    return {
        "adapter": {"adapter_id": "rule-engine", "vendor": "local", "status": "SKIPPED",
                    "raw_text": ""},
        "validation": {
            "mode": "AGENT_SUGGESTION",
            "degrade_reason": None,
            "uncovered_obligations": [],
            "accepted": [{
                "item_id": "S1", "obligation_id": "S1-O1", "agent_id": "rule-engine",
                "provider": "local", "model_id_or_unknown": "UNKNOWN",
                "proposed_verdict": "MATCH", "confidence_or_uncertain": "CONFIDENT",
            }],
            "rejected": [],
        },
    }


class ParticipationGateCounterexamples(unittest.TestCase):
    """两类反例（Reviewer 亲手跑过、旧实现挡不住的那两个）。"""

    def test_counterexample_a_all_rule_only_must_fail(self):
        res = evaluate_participation_gate([_rule_only_record()],
                                           requested_mode=MODE_AGENT_REQUIRED)
        self.assertEqual(res["verdict"], "FAIL", res)
        self.assertIn(GATE_NO_REAL_MODEL_RUN, res["failures"], res)
        self.assertEqual(res["ai_score"], AI_NOT_SCORED, res)
        self.assertNotEqual(res["execution_path"], PATH_AGENT, res)

    def test_counterexample_b_collapsed_boolean_must_fail(self):
        """自报 participated=True 且身份 UNKNOWN ⇒ 必须 FAIL（不许塌缩成一个布尔）。"""
        rec = _record_with_identity("UNKNOWN")
        res = evaluate_participation_gate([rec], requested_mode=MODE_AGENT_REQUIRED,
                                           identity_verified=True)
        self.assertEqual(res["verdict"], "FAIL", res)
        self.assertIn(GATE_MODEL_IDENTITY_UNVERIFIED, res["failures"], res)
        self.assertIs(res["identity_verified"], False, res)
        self.assertEqual(res["ai_score"], AI_NOT_SCORED, res)


class ParticipationGateHappyPaths(unittest.TestCase):

    def test_agent_required_with_verified_identity_passes(self):
        rec = _record_with_identity("gpt-5.6-sol")
        res = evaluate_participation_gate([rec], requested_mode=MODE_AGENT_REQUIRED,
                                           identity_verified=True)
        self.assertEqual(res["verdict"], "PASS", res)
        self.assertEqual(res["execution_path"], PATH_AGENT, res)
        self.assertIs(res["identity_verified"], True, res)
        self.assertEqual(res["failures"], [], res)
        self.assertIsNone(res["ai_score"], res)

    def test_rule_only_needs_no_agent_but_must_be_labelled(self):
        res = evaluate_participation_gate([_rule_only_record()],
                                           requested_mode=MODE_RULE_ONLY)
        self.assertEqual(res["verdict"], "PASS", res)
        self.assertEqual(res["execution_path"], PATH_RULE, res)
        self.assertEqual(res["failures"], [], res)

    def test_auto_with_degradation_is_not_ai_score(self):
        rec = _record_with_identity("gpt-5.6-sol")
        rec["validation"]["degrade_reason"] = "provider timeout"
        res = evaluate_participation_gate([rec], requested_mode=MODE_AUTO)
        self.assertTrue(res["degraded"], res)
        self.assertEqual(res["ai_score"], AI_NOT_SCORED, res)
        self.assertIn(GATE_MODE_DOWNGRADED, res["failures"], res)

    def test_degrade_reason_is_recorded_not_only_a_boolean(self):
        """规范 §2.1：降级必须**记录原因**，不许只有一个布尔。"""
        rec = _record_with_identity("gpt-5.6-sol")
        rec["validation"]["degrade_reason"] = "provider timeout"
        res = evaluate_participation_gate([rec], requested_mode=MODE_AUTO)
        self.assertTrue(res["degraded"], res)
        self.assertIn("provider timeout", res["degrade_reason"], res)

    def test_identity_source_requirement_is_declared(self):
        """规范 §2.2：身份必须来自 Agent 自己的权威元数据 ⇒ 门禁必须写明这条要求。"""
        res = evaluate_participation_gate([], requested_mode=MODE_RULE_ONLY)
        self.assertIn("Agent 自己", res["evidence"]["identity_source_requirement"], res)
        self.assertIn("禁止人工手填", res["evidence"]["identity_source_requirement"], res)

    def test_mode_must_be_one_of_three(self):
        with self.assertRaises(ValueError):
            evaluate_participation_gate([], requested_mode="SOMETHING_ELSE")


class ParticipationGateAgainstRealArtifacts(unittest.TestCase):
    """对**冻结产物**的实读：防止这条门禁只在合成数据上成立。"""

    def test_real_frozen_run_record_cannot_pass_identity_gate(self):
        if not REAL_RUN_RECORD.exists():
            self.skipTest("冻结 run record 不在本地快照中")
        rec = json.loads(REAL_RUN_RECORD.read_text(encoding="utf-8"))
        res = evaluate_participation_gate([rec], requested_mode=MODE_AGENT_REQUIRED)
        self.assertEqual(res["verdict"], "FAIL", res)
        self.assertIn(GATE_MODEL_IDENTITY_UNVERIFIED, res["failures"], res)
        self.assertEqual(res["execution_path"], PATH_AGENT, res)  # 真实调用确实发生过
        self.assertTrue(res["evidence"]["model_ids_unverified"], res)


if __name__ == "__main__":
    unittest.main(verbosity=2)
