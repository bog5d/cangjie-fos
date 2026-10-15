"""DD-V1 纠错经验、回归数据集与评分接口测试（WP5）。

红线：
1. **一次人工修改不得无条件升级为全局规则**——tier 恒从 feedback 起，晋级须留 Gate 痕迹。
2. **无回归数据集 → 全项 0 分 / UNKNOWN**，绝不自评高分。
3. **硬门槛独立于总分**——HG1/2/3 任一 FAIL 即 BLOCKED，不被高分稀释。
4. **主体/期间/文件类型变化时经验必须重新验证**，防止跨主体串用（HG2 的根）。
5. 回归用例必须带出处，来源不明不准入（防止把错误答案固化成标准答案）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cangjie_fos.services import dd_v1_card_service as cs
from cangjie_fos.services import dd_v1_experience_service as xs
from cangjie_fos.services import dd_v1_manifest_service as mf
from cangjie_fos.services import dd_v1_match_service as ms
from cangjie_fos.services import dd_v1_package_service as pkg
from cangjie_fos.services import dd_v1_parser_service as ps
from cangjie_fos.services import dd_v1_requirement_service as rq


# ── 披露策略夹具（WP7）─────────────────────────────────────────────────────
# WP3–WP6 时期的用例用 `sensitivity="PUBLIC"` 绕过 Gate，那正是二值判定的漏洞：
# 任意非空值都放行。WP7 改为版本化策略后，未知等级一律不可外发，
# 因此本文件统一在**已知策略**下运行。
import json as _json
from pathlib import Path as _Path

_TEST_POLICY = {
    "policy_version": "test-v1",
    "default_level": "RESTRICTED",
    "levels": {
        "PUBLIC": {"externally_sendable": True, "requires_review": True},
        "INTERNAL": {"externally_sendable": False, "requires_review": True},
        "CONFIDENTIAL": {"externally_sendable": False, "requires_review": True},
        "RESTRICTED": {"externally_sendable": False, "requires_review": True},
    },
    "rules": [],
}


def _enable_test_policy(monkeypatch, tmp_path) -> None:
    p = _Path(tmp_path) / "_policy.json"
    p.write_text(_json.dumps(_TEST_POLICY, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("CANGJIE_DD_V1_POLICY", str(p))


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CANGJIE_DD_V1_DATA_DIR", str(tmp_path / "_plane"))
    _enable_test_policy(monkeypatch, tmp_path)
    mf.close_all()
    yield
    mf.close_all()


def _db(tmp_path: Path):
    return tmp_path / "_dp" / "manifest.sqlite"


def _audit(year, entity="子公司甲"):
    return f"审计报告\n本报告为{year}年度财务审计结论，由{entity}出具。\n"


def _seed(tmp_path, files):
    lib = "lib1"
    root = tmp_path / "materials"
    root.mkdir(exist_ok=True)
    mf.register_library(lib, str(root), authorized_by="波总", db_path=_db(tmp_path))
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    mf.build_manifest(lib, db_path=_db(tmp_path))
    ps.parse_pending_batch(lib, db_path=_db(tmp_path))
    cs.build_cards_for_library(lib, db_path=_db(tmp_path))
    return lib


def _unlock(lib, db, rel, sensitivity="PUBLIC"):
    fid = mf.get_manifest_entry(lib, rel, db_path=db)["file_id"]
    conn = mf._connect(db)
    conn.execute("UPDATE dd_v1_material_cards SET sensitivity=? WHERE file_id=?",
                 (sensitivity, fid))
    conn.commit()
    return fid


# ── 1. 一次修改不得自动升级 ──────────────────────────────────────────────
def test_feedback_starts_at_feedback_and_is_never_auto_promoted(tmp_path):
    lib = _seed(tmp_path, {"子公司甲/审计报告2023.txt": _audit(2023)})
    out = xs.record_feedback(
        lib, "请提供2023年度审计报告", reason="该份为扫描件不可读", edited_by="刘江",
        machine_verdict="MATCHED", candidates=["f1"], corrected=[],
        scope_entity="子公司甲", institution="某机构", template="尽调标准模板",
        db_path=_db(tmp_path))
    assert out["tier"] == xs.T_FEEDBACK
    assert out["auto_promoted"] is False
    rows = xs._conn(_db(tmp_path)).execute(
        "SELECT tier FROM dd_v1_experience WHERE exp_id=?", (out["exp_id"],)).fetchone()
    assert rows["tier"] == xs.T_FEEDBACK


def test_feedback_requires_reviewer_reason_and_scope(tmp_path):
    lib = _seed(tmp_path, {"子公司甲/a.txt": "x"})
    with pytest.raises(ValueError, match="edited_by"):
        xs.record_feedback(lib, "r", reason="x", edited_by="", scope_entity="E",
                           db_path=_db(tmp_path))
    with pytest.raises(ValueError, match="reason"):
        xs.record_feedback(lib, "r", reason="", edited_by="刘江", scope_entity="E",
                           db_path=_db(tmp_path))
    with pytest.raises(ValueError, match="scope_entity"):
        xs.record_feedback(lib, "r", reason="x", edited_by="刘江", scope_entity="",
                           db_path=_db(tmp_path))


def test_promotion_requires_gate_trace_and_cannot_skip_levels(tmp_path):
    lib = _seed(tmp_path, {"子公司甲/a.txt": "x"})
    e = xs.record_feedback(lib, "请提供审计报告", reason="r", edited_by="刘江",
                            scope_entity="子公司甲", db_path=_db(tmp_path))
    with pytest.raises(ValueError, match="gate_result"):
        xs.promote(e["exp_id"], xs.T_CANDIDATE, promoted_by="监工", gate_result="",
                   db_path=_db(tmp_path))
    with pytest.raises(ValueError, match="不得跳级"):
        xs.promote(e["exp_id"], xs.T_APPROVED, promoted_by="监工", gate_result="PASS",
                   db_path=_db(tmp_path))
    out = xs.promote(e["exp_id"], xs.T_CANDIDATE, promoted_by="监工",
                     gate_result="独立复核通过", db_path=_db(tmp_path))
    assert out["tier"] == xs.T_CANDIDATE


# ── 2. 复用前必须复验（HG2 的根）─────────────────────────────────────────
def test_experience_rejected_for_other_entity(tmp_path):
    lib = _seed(tmp_path, {"子公司甲/a.txt": "x"})
    e = xs.record_feedback(lib, "请提供审计报告", reason="r", edited_by="刘江",
                            scope_entity="子公司甲", db_path=_db(tmp_path))
    xs.promote(e["exp_id"], xs.T_CANDIDATE, promoted_by="监工", gate_result="OK",
               db_path=_db(tmp_path))
    xs.promote(e["exp_id"], xs.T_APPROVED, promoted_by="监工", gate_result="OK",
               db_path=_db(tmp_path))

    got = xs.recall_experience(lib, "请提供审计报告", current_entity="子公司乙",
                               db_path=_db(tmp_path))
    assert got["matched"] == 0
    assert got["rejected"] and "主体不符" in got["rejected"][0]["reason"]


def test_experience_accepted_for_same_entity(tmp_path):
    lib = _seed(tmp_path, {"子公司甲/a.txt": "x"})
    e = xs.record_feedback(lib, "请提供审计报告", reason="r", edited_by="刘江",
                            scope_entity="子公司甲", institution="某机构",
                            db_path=_db(tmp_path))
    for tier in (xs.T_CANDIDATE, xs.T_APPROVED):
        xs.promote(e["exp_id"], tier, promoted_by="监工", gate_result="OK",
                   db_path=_db(tmp_path))
    got = xs.recall_experience(lib, "请提供审计报告", current_entity="子公司甲",
                               db_path=_db(tmp_path))
    assert got["matched"] == 1


def test_experience_rejected_for_other_institution_or_template(tmp_path):
    lib = _seed(tmp_path, {"子公司甲/a.txt": "x"})
    e = xs.record_feedback(lib, "请提供审计报告", reason="r", edited_by="刘江",
                            scope_entity="子公司甲", institution="机构甲",
                            template="模板A", db_path=_db(tmp_path))
    for tier in (xs.T_CANDIDATE, xs.T_APPROVED):
        xs.promote(e["exp_id"], tier, promoted_by="监工", gate_result="OK",
                   db_path=_db(tmp_path))
    got = xs.recall_experience(lib, "请提供审计报告", current_entity="子公司甲",
                               institution="机构乙", template="模板B",
                               db_path=_db(tmp_path))
    assert got["matched"] == 0
    assert any("机构不符" in r["reason"] or "模板不符" in r["reason"]
               for r in got["rejected"])


def test_requirement_normalization_ignores_year_and_punct(tmp_path):
    lib = _seed(tmp_path, {"子公司甲/a.txt": "x"})
    e = xs.record_feedback(lib, "请提供2021-2023年度审计报告，", reason="r",
                            edited_by="刘江", scope_entity="子公司甲",
                            db_path=_db(tmp_path))
    for tier in (xs.T_CANDIDATE, xs.T_APPROVED):
        xs.promote(e["exp_id"], tier, promoted_by="监工", gate_result="OK",
                   db_path=_db(tmp_path))
    got = xs.recall_experience(lib, "请提供2024-2026年度审计报告",
                               current_entity="子公司甲", db_path=_db(tmp_path))
    assert got["matched"] == 1, "同类需求换年份应能命中经验"


# ── 3. 回归数据集必须有出处 ──────────────────────────────────────────────
def test_regression_case_requires_source_ref(tmp_path):
    lib = _seed(tmp_path, {"子公司甲/a.txt": "x"})
    with pytest.raises(ValueError, match="source_ref"):
        xs.add_regression_case(lib, "请提供审计报告", source_ref="", db_path=_db(tmp_path))


def test_regression_case_roundtrip(tmp_path):
    lib = _seed(tmp_path, {"子公司甲/a.txt": "x"})
    c = xs.add_regression_case(lib, "请提供审计报告", source_ref="2023年人工交付包",
                               item_no="1", expected_verdict=ms.V_MATCHED,
                               expected_files=["f1"], db_path=_db(tmp_path))
    cases = xs.list_regression_cases(lib, db_path=_db(tmp_path))
    assert len(cases) == 1
    assert cases[0]["expected"]["verdict"] == ms.V_MATCHED
    assert cases[0]["expected"]["files"] == ["f1"]
    assert cases[0]["source_ref"] == "2023年人工交付包"


# ── 4. 评分：无 gold set 必须全 0 ────────────────────────────────────────
def test_no_gold_set_means_zero_and_unknown(tmp_path):
    lib = _seed(tmp_path, {"子公司甲/审计报告2023.txt": _audit(2023)})
    _unlock(lib, _db(tmp_path), "子公司甲/审计报告2023.txt")
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "请提供2023年度审计报告"}],
                        db_path=_db(tmp_path))
    ms.match_library(lib, db_path=_db(tmp_path))

    s = xs.score_library(lib, db_path=_db(tmp_path))
    assert s["scored_on"] == "NO_GOLD_SET"
    assert s["regression_cases"] == 0
    assert s["verified_points"] == 0
    assert all(m["status"] == "UNKNOWN" for m in s["metrics"])
    # 关键：不可评分 ≠ 质量不达标
    assert s["goal_state"] == "NOT_SCORABLE"
    assert s["scorable"] is False
    assert all(m["points_are_meaningful"] is False for m in s["metrics"])


def test_score_never_exceeds_weights(tmp_path):
    lib = _seed(tmp_path, {"子公司甲/审计报告2023.txt": _audit(2023)})
    s = xs.score_library(lib, db_path=_db(tmp_path))
    assert s["total_points"] == 100
    assert sum(m["weight"] for m in s["metrics"]) == 100
    assert 0 <= s["verified_points"] <= 100


def test_weighted_metrics_match_frozen_contract(tmp_path):
    lib = _seed(tmp_path, {"子公司甲/a.txt": "x"})
    s = xs.score_library(lib, db_path=_db(tmp_path))
    got = {m["id"]: m["weight"] for m in s["metrics"]}
    assert got == {"M1_需求理解": 20, "M2_多主体多年度覆盖": 25,
                   "M3_匹配正确性": 25, "M4_版本证据权限": 20,
                   "M5_最终组包质量": 10}


# ── 5. 硬门槛独立于总分 ──────────────────────────────────────────────────
def test_hard_gates_all_present_and_hg4_always_fail(tmp_path):
    lib = _seed(tmp_path, {"子公司甲/a.txt": "x"})
    gates = xs.compute_hard_gates(lib, db_path=_db(tmp_path))
    ids = {g["id"] for g in gates}
    assert ids == {"HG1_无越权披露", "HG2_无主体冒充", "HG3_无虚假完整", "HG4_不虚称自主"}
    hg4 = next(g for g in gates if g["id"].startswith("HG4"))
    assert hg4["status"] == "FAIL", "HG4 不得因工程进展而翻转"


def test_hg3_detects_false_completeness(tmp_path):
    """人为把覆盖改低却仍标 MATCHED → HG3 必须 FAIL。"""
    lib = _seed(tmp_path, {"子公司甲/审计报告2023.txt": _audit(2023)})
    _unlock(lib, _db(tmp_path), "子公司甲/审计报告2023.txt")
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "请提供2023年度审计报告"}],
                        db_path=_db(tmp_path))
    ms.match_library(lib, db_path=_db(tmp_path))
    conn = mf._connect(_db(tmp_path))
    conn.execute("UPDATE dd_v1_obligation_status SET entity_cov=0.5 WHERE library_id=?",
                 (lib,))
    conn.commit()

    gates = xs.compute_hard_gates(lib, db_path=_db(tmp_path))
    hg3 = next(g for g in gates if g["id"].startswith("HG3"))
    assert hg3["status"] == "FAIL"
    assert hg3["evidence_refs"]


def test_hard_gate_failure_blocks_goal_state(tmp_path):
    lib = _seed(tmp_path, {"子公司甲/审计报告2023.txt": _audit(2023)})
    _unlock(lib, _db(tmp_path), "子公司甲/审计报告2023.txt")
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "请提供2023年度审计报告"}],
                        db_path=_db(tmp_path))
    ms.match_library(lib, db_path=_db(tmp_path))
    xs.add_regression_case(lib, "请提供2023年度审计报告", source_ref="2023年人工交付包",
                           item_no="1", expected_verdict=ms.V_MATCHED,
                           db_path=_db(tmp_path))
    conn = mf._connect(_db(tmp_path))
    conn.execute("UPDATE dd_v1_obligation_status SET period_cov=0.5 WHERE library_id=?",
                 (lib,))
    conn.commit()

    s = xs.score_library(lib, db_path=_db(tmp_path))
    assert s["goal_state"] == "BLOCKED_BY_HARD_GATE"
    assert s["verified_points"] < 100, "样本量不足时不得给满分"
    assert any(m["status"] == "LOW_CONFIDENCE" for m in s["metrics"])


def test_hg1_detects_packaged_without_approver(tmp_path):
    lib = _seed(tmp_path, {"子公司甲/审计报告2023.txt": _audit(2023)})
    rev = pkg.build_review_pack(lib, db_path=_db(tmp_path))
    # 绕过 approve，直接把状态改成 packaged（模拟越权写入）
    conn = mf._connect(_db(tmp_path))
    conn.execute("UPDATE dd_v1_reviews SET status='packaged' WHERE review_id=?",
                 (rev["review_id"],))
    conn.commit()

    gates = xs.compute_hard_gates(lib, db_path=_db(tmp_path))
    hg1 = next(g for g in gates if g["id"].startswith("HG1"))
    assert hg1["status"] == "FAIL"


def test_score_output_declares_no_self_reporting(tmp_path):
    lib = _seed(tmp_path, {"子公司甲/a.txt": "x"})
    s = xs.score_library(lib, db_path=_db(tmp_path))
    assert "不接受 LLM 自评" in s["self_report_prohibited"]


# ── 7. 「不可评分」与「评分为 0」必须可区分（监工指出）──────────────────
def test_not_scorable_is_distinct_from_measured_zero(tmp_path):
    """缺 gold set 时是**不可评分**，不是「测过了得 0 分」。

    SCP v3.8 防误判回归第 9 条：缺证据应为 UNKNOWN，不能降级成 0/FAIL。
    """
    lib = _seed(tmp_path, {"子公司甲/审计报告2023.txt": _audit(2023)})
    _unlock(lib, _db(tmp_path), "子公司甲/审计报告2023.txt")
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "请提供2023年度审计报告"}],
                        db_path=_db(tmp_path))
    ms.match_library(lib, db_path=_db(tmp_path))

    s = xs.score_library(lib, db_path=_db(tmp_path))
    assert s["measurement_state"] == "NOT_SCORABLE"
    assert s["scorable"] is False
    assert s["goal_state"] == "NOT_SCORABLE"
    for m in s["metrics"]:
        assert m["verified_points"] == 0
        assert m["points_are_meaningful"] is False
        assert m["measurement_state"] == "NOT_SCORABLE"
        assert "不可评分" in m["not_scorable_reason"]
    assert "不得" in s["reading_guide"] and "NOT_SCORABLE" in s["reading_guide"]


def test_measured_score_marks_points_meaningful(tmp_path):
    """有 gold set 且有对应义务时，分数才是有意义的实测值。"""
    lib = _seed(tmp_path, {"子公司甲/审计报告2023.txt": _audit(2023)})
    _unlock(lib, _db(tmp_path), "子公司甲/审计报告2023.txt")
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "请提供2023年度审计报告"}],
                        db_path=_db(tmp_path))
    ms.match_library(lib, db_path=_db(tmp_path))
    xs.add_regression_case(lib, "请提供2023年度审计报告", source_ref="2023年人工交付包",
                           item_no="1", expected_verdict=ms.V_MATCHED,
                           db_path=_db(tmp_path))

    s = xs.score_library(lib, db_path=_db(tmp_path))
    assert s["measurement_state"] == "MEASURED"
    assert s["scorable"] is True
    for m in s["metrics"]:
        assert m["points_are_meaningful"] is True
        assert m["measurement_state"] in ("MEASURED", "LOW_CONFIDENCE")


def test_gold_set_without_matching_obligation_is_not_scorable(tmp_path):
    """gold set 的 item_no 对不上任何义务 → 同样不可评分，不是 0 分。"""
    lib = _seed(tmp_path, {"子公司甲/审计报告2023.txt": _audit(2023)})
    _unlock(lib, _db(tmp_path), "子公司甲/审计报告2023.txt")
    rq.ingest_checklist(lib, [{"item_no": "1", "raw_text": "请提供2023年度审计报告"}],
                        db_path=_db(tmp_path))
    ms.match_library(lib, db_path=_db(tmp_path))
    xs.add_regression_case(lib, "无关要求", source_ref="某历史包",
                           item_no="99", expected_verdict=ms.V_MATCHED,
                           db_path=_db(tmp_path))

    s = xs.score_library(lib, db_path=_db(tmp_path))
    assert s["measurement_state"] == "NOT_SCORABLE"
    assert s["goal_state"] == "NOT_SCORABLE"
    assert "无法逐条比对" in s["metrics"][0]["not_scorable_reason"]


def test_four_goal_states_are_distinguishable(tmp_path):
    lib = _seed(tmp_path, {"子公司甲/a.txt": "x"})
    assert xs.score_library(lib, db_path=_db(tmp_path))["goal_state"] == "NOT_SCORABLE"
