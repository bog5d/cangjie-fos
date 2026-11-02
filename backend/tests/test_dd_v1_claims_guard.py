"""「声称 ↔ 实现」守卫的回归测试（含**真实仓库自证**）。

★ 本文件钉住的是本轮两次独立 Reviewer FAIL 的**同款根因**：
  文档声称「已落地」而实现里 grep 命中 0 ⇒ 虚假 PASS。

★ 用 stdlib `unittest`（无第三方依赖）——理由同
  `test_dd_v1_participation_gate.py`：Reviewer 那轮实测 pytest 收集阶段因缺 pydantic 直接 BLOCKED。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from cangjie_fos.services.dd_v1_claims_guard import (
    CLAIM_DECLARED_UNKNOWN,
    CLAIM_IMPLEMENTED,
    CLAIM_UNSUPPORTED,
    check_claims,
    evaluate_claim,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CLAIMS_FILE = REPO_ROOT / "docs/dd-v1-fos71/wp05-real-integration/CLAIMS.json"
GOLD_FILE = REPO_ROOT / "backend/tests/fixtures/dd-v1-fos71-a4/gold.json"


class ClaimsGuardLogic(unittest.TestCase):
    """守卫自身的逻辑（合成夹具）。"""

    def test_claim_without_evidence_but_says_implemented_is_unsupported(self):
        """说「已落地」却**没有任何证据** ⇒ 虚假 PASS ⇒ 必须被抓。"""
        res = evaluate_claim({"id": "X", "claim": "x 已落地", "status": "IMPLEMENTED",
                              "evidence": []}, REPO_ROOT)
        self.assertEqual(res["status"], CLAIM_UNSUPPORTED, res)
        self.assertTrue(res["violation"], res)

    def test_claim_with_matching_evidence_is_implemented(self):
        res = evaluate_claim({"id": "Y", "claim": "文件存在", "status": "IMPLEMENTED",
                              "evidence": [{"type": "file_exists",
                                            "path": "backend/tests/test_dd_v1_claims_guard.py"}]},
                             REPO_ROOT)
        self.assertEqual(res["status"], CLAIM_IMPLEMENTED, res)
        self.assertFalse(res["violation"], res)

    def test_claim_with_failing_evidence_is_unsupported(self):
        res = evaluate_claim({"id": "Z", "claim": "有个不存在的锚点", "status": "IMPLEMENTED",
                              "evidence": [{"type": "grep", "path": "backend/src",
                                            "pattern": "THIS_ANCHOR_DOES_NOT_EXIST_9F3A",
                                            "min_hits": 1}]}, REPO_ROOT)
        self.assertEqual(res["status"], CLAIM_UNSUPPORTED, res)
        self.assertTrue(res["violation"], res)

    def test_unknown_evidence_type_is_not_satisfied(self):
        """**写错的证据类型**不得当成命中（否则守卫会被一个 typo 变成永远绿）。"""
        res = evaluate_claim({"id": "TYPO", "claim": "证据类型写错", "status": "IMPLEMENTED",
                              "evidence": [{"type": "file_exsts", "path": "README.md"}]},
                             REPO_ROOT)
        self.assertEqual(res["status"], CLAIM_UNSUPPORTED, res)
        self.assertTrue(res["violation"], res)

    def test_report_level_violations_exclude_declared_unknown(self):
        """报告级：显式声明「未知」的声称**不进**违规清单（否则缺口会被当成虚假 PASS）。"""
        claims = [
            {"id": "U1", "claim": "还没做", "status": "NOT_IMPLEMENTED", "evidence": []},
            {"id": "I1", "claim": "做了", "status": "IMPLEMENTED",
             "evidence": [{"type": "file_exists",
                           "path": "backend/tests/test_dd_v1_claims_guard.py"}]},
        ]
        report = check_claims(claims, REPO_ROOT)
        self.assertEqual([r["id"] for r in report["violations"]], [], report)
        self.assertEqual(report["verdict"], "PASS", report)

    def test_honestly_declared_unknown_is_not_a_violation(self):
        """显式写「未知/未落地」⇒ **不违规**（缺口仍可见，但不能算虚假 PASS）。"""
        res = evaluate_claim({"id": "W", "claim": "还没做", "status": "NOT_IMPLEMENTED",
                              "evidence": []}, REPO_ROOT)
        self.assertEqual(res["status"], CLAIM_DECLARED_UNKNOWN, res)
        self.assertFalse(res["violation"], res)


class ClaimsGuardAgainstRealRepo(unittest.TestCase):
    """对**真实仓库**跑：证明守卫在真东西上成立，而不是只在合成夹具上成立。"""

    def test_real_claims_file_flags_gold_human_approval_as_false_pass(self):
        if not CLAIMS_FILE.exists():
            self.skipTest("CLAIMS.json 不在本地快照中")
        claims = json.loads(CLAIMS_FILE.read_text(encoding="utf-8"))["claims"]
        report = check_claims(claims, REPO_ROOT)
        by_id = {r["id"]: r for r in report["results"]}

        # 本 PR 已落地两条 ⇒ 有证据
        self.assertEqual(by_id["G8-PARTICIPATION-GATE"]["status"], CLAIM_IMPLEMENTED,
                         by_id["G8-PARTICIPATION-GATE"])
        self.assertEqual(by_id["THRESHOLD-FROZEN-AT"]["status"], CLAIM_IMPLEMENTED,
                         by_id["THRESHOLD-FROZEN-AT"])
        # 第三条缺口（独立人工 Gold）**故意**声称已落地 ⇒ 守卫必须抓到虚假 PASS
        self.assertEqual(by_id["GOLD-HUMAN-APPROVED"]["status"], CLAIM_UNSUPPORTED,
                         by_id["GOLD-HUMAN-APPROVED"])
        self.assertTrue(by_id["GOLD-HUMAN-APPROVED"]["violation"])
        self.assertEqual(report["verdict"], "FAIL", report)
        # ★ 必须是「因为真的逐条校验过」而红，不是「因为路径写错」而红（假绿）
        detail = " ".join(c["detail"] for c in by_id["GOLD-HUMAN-APPROVED"]["evidence_checks"])
        self.assertIn("条不满足", detail, detail)
        self.assertNotIn("不是列表", detail, detail)
        self.assertIn("非人工批准", detail, detail)

    def test_frozen_gold_is_indeed_machine_confirmed_only(self):
        """钉住现状：仓内 gold.json 的每一条都**不是**人工批准。"""
        if not GOLD_FILE.exists():
            self.skipTest("gold.json 不在本地快照中")
        items = json.loads(GOLD_FILE.read_text(encoding="utf-8"))
        self.assertTrue(items, "gold.json 不应为空")
        for it in items:
            by = str(it.get("confirmed_by", ""))
            self.assertIn("非人工批准", by,
                          "★ 若业务方已完成人工批准，这条断言会失败 ⇒ "
                          "请同步更新 CLAIMS.json 的证据与本测试的说明（不是删断言）")
            self.assertNotIn("UNKNOWN", by)


if __name__ == "__main__":
    unittest.main(verbosity=2)
