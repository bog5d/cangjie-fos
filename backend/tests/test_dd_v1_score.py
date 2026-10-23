"""DD-V1 错误分类 + Gold 隔离测试（A4a · G-A4a-3 / G-A4a-4）。

判据对应
--------
- **A4-3**：每条 Gold 有 ``confirmed_by`` + ``confirmed_at``；``assert_gold_isolated`` 通过；
  Gold 不在任何材料 / 运行 / 输出目录与 **Git 仓**内。
- **A4-4**：合成 Gold 上输出含 TP / FP / FN / 错主体 / 错年度 / 自信错配；
  每错能回指 run_record + locator；**UNCERTAIN 单列不计入 FN**。

红线：不得把「没查」算成「查了没有」；不得把 UNCERTAIN 计入 FN。
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_score_service as sc

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import dd_v1_local_run as lr  # noqa: E402

CONFIRMED_BY = "司仓机械核对（非人工批准）"
CONFIRMED_AT = "2026-10-22T12:30:00+08:00"
META = [
    {"file_id": "F00001", "relative_path": "主体甲/a.txt", "entity": "主体甲", "period": "2024"},
    {"file_id": "F00002", "relative_path": "主体甲/b.txt", "entity": "主体甲", "period": "2024"},
    {"file_id": "F00004", "relative_path": "主体甲/c.txt", "entity": "主体甲", "period": "2023"},
    {"file_id": "F00008", "relative_path": "主体乙/d.txt", "entity": "主体乙", "period": "2024"},
]


def _rec(oid, verdict, files, conf, *, locator="L2-L6", entity="主体甲", period="2024",
         path="/tmp/run/run-R1/run_record.json"):
    """造一条 run_record（authoritative 层 = semantic_validation）。"""
    return {
        "authoritative_validation": "semantic_validation",
        "semantic_validation": {
            "mode": "AGENT_SUGGESTION",
            "accepted": [{
                "item_id": "R1", "obligation_id": oid, "agent_id": "synthetic-replay",
                "provider": "SYNTHETIC", "model_id_or_unknown": "UNKNOWN",
                "prompt_version": "fos71-wp04-p1", "source_snapshot_id": "snap-test",
                "candidate_files": [{"file_id": f, "relative_path": f"主体甲/{f}.txt", "sha256": "0" * 64,
                                     "locator": locator, "entity": entity, "period": period,
                                     "match_reason": "测试用"} for f in files],
                "proposed_verdict": verdict, "confidence_or_uncertain": conf,
                "abstain_reason": "", "warnings": [], "elapsed": 0,
                "token_usage_or_UNKNOWN": "UNKNOWN",
            }],
            "rejected": [], "uncovered": [],
        },
    }, path


def _gold(oid, verdict, files, **extra):
    g = {"obligation_id": oid, "expected_verdict": verdict, "expected_files": files,
         "confirmed_by": CONFIRMED_BY, "confirmed_at": CONFIRMED_AT}
    g.update(extra)
    return g


def _classify(recs, gold, meta=None):
    paths = [r[1] for r in recs]
    return sc.score_with_classification([r[0] for r in recs], gold, meta=meta or META,
                                        record_paths=paths, run_dir=Path("/tmp/run"))


# ---------------- G-A4a-4 分类

def test_all_categories_are_produced():
    recs = [
        _rec("O-TP", "MATCH", ["F00001", "F00002"], 0.9),
        _rec("O-FP", "MATCH", ["F00001", "F00002"], 0.5),
        _rec("O-FN", "MISSING", [], 0.4),
        _rec("O-ENT", "MATCH", ["F00001"], 0.7),
        _rec("O-PER", "OUTDATED", ["F00004"], 0.9, period="2023"),
        _rec("O-SET", "MATCH", ["F00001", "F00004"], 0.5, period="2024"),
        _rec("O-UNC", "UNCERTAIN", [], "UNCERTAIN"),
    ]
    gold = [
        _gold("O-TP", "MATCH", ["F00001", "F00002"]),
        _gold("O-FP", "MATCH", ["F00001"]),
        _gold("O-FN", "MATCH", ["F00001"]),
        _gold("O-ENT", "MATCH", ["F00008"], expected_entity="主体乙", expected_period="2024"),
        _gold("O-PER", "MATCH", ["F00001"]),
        _gold("O-SET", "MATCH", ["F00001", "F00002"]),
        _gold("O-UNC", "MATCH", ["F00001"]),
    ]
    counts = _classify(recs, gold)["classification"]["counts"]
    assert counts["TP"] == 1
    assert counts["FP"] == 1
    assert counts["FN"] == 1
    assert counts["WRONG_ENTITY"] == 1
    assert counts["WRONG_PERIOD"] == 1
    assert counts["WRONG_FILE_SET"] == 1
    assert counts["CONFIDENT_MISMATCH"] == 1
    assert counts["UNCERTAIN"] == 1


def test_uncertain_is_not_counted_as_fn():
    recs = [_rec("O-UNC", "UNCERTAIN", [], "UNCERTAIN")]
    gold = [_gold("O-UNC", "MATCH", ["F00001"])]
    res = _classify(recs, gold)
    counts = res["classification"]["counts"]
    assert counts["UNCERTAIN"] == 1 and counts["FN"] == 0
    assert res["classification"]["fn_count"] == 0
    # 既有基线把 UNCERTAIN 计入 wrong（本包不改其语义）⇒ 分类层必须把它单列出来
    assert res["base"]["agent"]["wrong"] == 1


def test_confident_mismatch_only_when_row_is_wrong():
    recs = [_rec("O-OK", "MATCH", ["F00001"], 0.95), _rec("O-BAD", "MATCH", ["F00004"], 0.95, period="2023")]
    gold = [_gold("O-OK", "MATCH", ["F00001"]), _gold("O-BAD", "MATCH", ["F00001"])]
    rows = {r["obligation_id"]: r for r in _classify(recs, gold)["classification"]["rows"]}
    assert rows["O-OK"]["confident_mismatch"] is False
    assert rows["O-BAD"]["confident_mismatch"] is True
    assert rows["O-BAD"]["flags"] == ["CONFIDENT_MISMATCH"]


def test_no_answer_is_not_treated_as_checked():
    """「没查」不得算成「查了没有」：NO_ANSWER 与 MISSING 分开记。"""
    recs = [({"authoritative_validation": "semantic_validation",
              "semantic_validation": {"mode": "RULE_ONLY", "accepted": [], "rejected": [],
                                      "uncovered": []}},
             "/tmp/run/run-R1/run_record.json")]
    gold = [_gold("O-NA", "MATCH", ["F00001"])]
    res = _classify(recs, gold)
    row = res["classification"]["rows"][0]
    assert row["agent_verdict"] == "NO_ANSWER"
    assert row["category"] == "FN"          # 期望有货、没给答案
    assert res["base"]["agent"]["no_answer"] == 1


def test_error_points_back_to_run_record_and_locator():
    recs = [_rec("O-ERR", "OUTDATED", ["F00004"], 0.9, period="2023",
                 path="/tmp/run/run-R7/run_record.json")]
    gold = [_gold("O-ERR", "MATCH", ["F00001"])]
    row = _classify(recs, gold)["classification"]["rows"][0]
    assert row["run_record_path"] == "run-R7/run_record.json"
    assert row["file_id"] == "F00004"
    assert row["locator"] == "L2-L6"
    assert row["locator_source"] == "ANSWER_CANDIDATE"


def test_locator_falls_back_to_rule_only_derived():
    recs = [_rec("O-DERIVED", "MATCH", ["F00001"], 0.5, locator="")]
    gold = [_gold("O-DERIVED", "MATCH", ["F00001", "F00002"])]
    row = _classify(recs, gold)["classification"]["rows"][0]
    assert row["locator_source"] == "RULE_ONLY_DERIVED"
    assert row["locator"] == "主体甲/a.txt"     # 由 meta 的 relative_path 派生


def test_expected_entity_source_priority():
    """Gold 字段 → expected_files 的唯一值 → 推不出（UNDETERMINED）。"""
    recs = [_rec("O-A", "MATCH", ["F00001"], 0.5), _rec("O-B", "MATCH", ["F00001"], 0.5),
            _rec("O-C", "MATCH", ["F00001"], 0.5)]
    gold = [_gold("O-A", "MATCH", ["F00001"], expected_entity="主体丙"),
            _gold("O-B", "MATCH", ["F00001"]),
            _gold("O-C", "MATCH", ["F00001", "F00002"])]
    rows = {r["obligation_id"]: r for r in _classify(recs, gold)["classification"]["rows"]}
    assert rows["O-A"]["expected_entity"] == "主体丙"
    assert rows["O-A"]["expected_entity_source"] == "GOLD_FIELD"
    assert rows["O-B"]["expected_entity"] == "主体甲"
    assert rows["O-B"]["expected_entity_source"] == "DERIVED_FROM_EXPECTED_FILES"
    assert rows["O-C"]["expected_entity"] == "主体甲"     # 两件同主体 ⇒ 仍是唯一值
    # 跨主体 ⇒ 推不出
    gold2 = [_gold("O-D", "MATCH", ["F00001", "F00008"])]
    recs2 = [_rec("O-D", "MATCH", ["F00001"], 0.5)]
    row = _classify(recs2, gold2)["classification"]["rows"][0]
    assert row["expected_entity"] is None
    assert row["expected_entity_source"] == "UNDETERMINED"


def test_base_scoring_semantics_are_unchanged():
    """分类层只包装，不改 score_against_gold 的语义。"""
    from cangjie_fos.services import dd_v1_semantic_retrieval_service as sem
    recs = [_rec("O-1", "MATCH", ["F00001"], 0.9)]
    gold = [_gold("O-1", "MATCH", ["F00001"])]
    base = sem.score_against_gold([r[0] for r in recs], gold)
    res = _classify(recs, gold)
    assert res["base"] == base


# ---------------- G-A4a-3 Gold 隔离

def test_gold_without_confirmation_is_not_scorable():
    gold = [{"obligation_id": "O-1", "expected_verdict": "MATCH", "expected_files": ["F00001"]}]
    assert sc.missing_confirmations(gold) == ["O-1"]
    res = sc.score_with_classification([], gold, meta=META)
    assert res["status"] == "NOT_SCORABLE"
    assert res["blocked_by"][0].startswith("GOLD_NOT_HUMAN_CONFIRMED")
    assert res["classification"] is None


def test_gold_with_empty_confirmation_is_not_scorable():
    gold = [{"obligation_id": "O-1", "expected_verdict": "MATCH", "expected_files": ["F00001"],
             "confirmed_by": "", "confirmed_at": CONFIRMED_AT}]
    res = sc.score_with_classification([], gold, meta=META)
    assert res["status"] == "NOT_SCORABLE"


def test_gold_inside_git_worktree_is_rejected(tmp_path):
    inside = REPO / "backend" / "tests" / "fixtures" / "dd-v1-fos71-a4" / "gold.json"
    assert inside.exists()
    assert sc.find_git_worktree(inside) == REPO
    with pytest.raises(sc.GoldIsolationError, match="GOLD_INSIDE_GIT_WORKTREE"):
        sc.assert_gold_not_in_git_worktree(inside)


def test_gold_outside_git_worktree_is_allowed(tmp_path):
    outside = tmp_path / "gold.json"
    outside.write_text("[]", "utf-8")
    assert sc.find_git_worktree(outside) is None
    sc.assert_gold_not_in_git_worktree(outside)     # 不抛


def test_gold_inside_material_dir_is_rejected(tmp_path):
    material = tmp_path / "material"
    material.mkdir()
    gold = material / "gold.json"
    gold.write_text("[]", "utf-8")
    with pytest.raises(PermissionError, match="GOLD_INSIDE"):
        sc.assert_gold_isolated(gold, material)


def test_cli_score_classify_refuses_gold_inside_git_repo(tmp_path):
    gold = REPO / "backend" / "tests" / "fixtures" / "dd-v1-fos71-a4" / "gold.json"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    assert lr.main(["score", "--run-dir", str(run_dir), "--gold", str(gold), "--classify",
                    "--out", str(tmp_path / "s.json")]) == 3


def test_cli_score_classify_refuses_unconfirmed_gold(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    gold = tmp_path / "gold" / "gold.json"
    gold.parent.mkdir()
    gold.write_text(json.dumps([{"obligation_id": "O-1", "expected_verdict": "MATCH",
                                 "expected_files": ["F00001"]}]), "utf-8")
    assert lr.main(["score", "--run-dir", str(run_dir), "--gold", str(gold), "--classify",
                    "--out", str(tmp_path / "s.json")]) == 3
    res = json.loads((tmp_path / "s.json").read_text("utf-8"))
    assert res["status"] == "NOT_SCORABLE"


def test_cli_score_without_classify_keeps_legacy_behaviour(tmp_path):
    """既有 score 路径逐字未改：不带 --classify 时输出结构与退出码不变。"""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    gold = tmp_path / "gold" / "gold.json"
    gold.parent.mkdir()
    gold.write_text(json.dumps([{"obligation_id": "O-1", "expected_verdict": "MATCH",
                                 "expected_files": ["F00001"]}]), "utf-8")
    assert lr.main(["score", "--run-dir", str(run_dir), "--gold", str(gold),
                    "--out", str(tmp_path / "s.json")]) == 0
    res = json.loads((tmp_path / "s.json").read_text("utf-8"))
    assert "rows" in res and "classification" not in res
