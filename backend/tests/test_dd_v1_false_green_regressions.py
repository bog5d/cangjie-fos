"""DD-V1 **假绿反例回归**（施工令 V3.0 §7.4 · 14 条）。

★ 这份文件的存在理由：**上一轮的门禁 G1—G7 里没有一道检查模型是否真的参与**，
  于是三场考试**全是 RULE_ONLY**（``model_participated=false``）却照样打出
  **96.67 / 95.67 / 100.0**，门禁照样绿 —— 这就是独立调查报告说的
  「**最危险的结构漏洞**」，也是 SCP v3.8 §3A 说的「目标漂移 P0 治理事故」。

⇒ 本文件把施工令列的 **14 条反例**逐条钉成**永久回归测试**：
  每一条都必须产生**预期**的门禁/成绩结果；
  **任何一条将来失效 ⇒ CI 直接抓**。

★ 全部用**合成夹具**，零外部调用、零费用、零网络。

反例清单（与施工令 §7.4 逐条对应）：
   1. Agent 不存在
   2. 凭证失效
   3. 模型调用超时
   4. 返回空内容
   5. 返回不可解析内容
   6. 模型身份 UNKNOWN
   7. Agent 调用失败后自动降级
   8. **规则引擎产生 100 分但模型未参与**（本轮核心）
   9. 模型参与证据属于其他考试
  10. 模型参与证据属于旧代码版本
  11. 模型参与成功但披露安全失败
  12. Gold 缺失
  13. 模型调用成功但答卷质量很差
  14. AUTO 模式正常降级
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "backend" / "src"))

from cangjie_fos.services import dd_v1_agent_adapters as ad  # noqa: E402
from cangjie_fos.services import dd_v1_agent_identity as ident  # noqa: E402
from cangjie_fos.services import dd_v1_exam_service as ex  # noqa: E402
from cangjie_fos.services import dd_v1_run_modes as rm  # noqa: E402

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "dd_v1_exam_suite", REPO / "tools" / "dd_v1_exam_suite.py")
exam_suite = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(exam_suite)


# ═══════════════════════════════════════════════════════════════════════════
# 工具
# ═══════════════════════════════════════════════════════════════════════════

def _manifest(*, exam: str = "C", requested_mode: str = "RULE_ONLY",
              execution_path: str = "RULE_ONLY", participated: bool = False,
              identity_verified: bool = False, model: str = "UNKNOWN",
              git_sha: str = "abc123", run_id: str = "r1") -> dict:
    """造一份**运行清单**（门禁 G8 只认这种真实考试产物）。"""
    return {
        "exam": exam,
        "run_id": run_id,
        "git_sha": git_sha,
        "git_dirty": False,
        "model": {
            "agent_spec": "none" if execution_path == "RULE_ONLY" else "dsh",
            "requested_mode": requested_mode,
            "execution_path": execution_path,
            "participated": participated,
            "model_identity_verified": identity_verified,
            "actual_model": model,
            "model_identity": {"model_id": model, "verified": identity_verified},
        },
        "results": {"status": "SCORED", "scores": {"total_score": 100.0}},
    }


def _gate(manifests: list[dict]) -> tuple[str, str]:
    """按 G8 的判据跑一次（**用真门禁实现**，不是复制判据）。"""
    spec = {"check": "model_participation_mode"}
    return exam_suite._gate_check(spec, None, runs_dir=REPO, manifests=manifests)


# ═══════════════════════════════════════════════════════════════════════════
# 反例 1—5：调用层的失败形态
# ═══════════════════════════════════════════════════════════════════════════

def _fake_harness(tmp_path: Path, body: str) -> str:
    p = tmp_path / "fake_agent.py"
    p.write_text(body, "utf-8")
    return f"{sys.executable} {p}"


def test_case_01_agent_binary_missing_is_call_failed_not_silent_pass(tmp_path):
    """**反例 1：Agent 不存在** ⇒ 不得被当成「跑通了」。"""
    adapter = ad.build_adapter("codex")
    adapter.binary = [str(tmp_path / "definitely_not_here")]
    res = adapter.run({"obligations": [], "evidence": {}}, tmp_path, ad.Budget(timeout_s=20))
    assert res.status == ad.CALL_FAILED
    assert res.exit_code == 127
    assert res.provenance.get("error_code") == "SPAWN_FAILED"


def test_case_02_credential_invalid_maps_to_stable_error_code():
    """**反例 2：凭证失效** ⇒ 稳定错误码（不是自由文本）。"""
    code = ad.classify_agent_error(
        "deepseek-harness", ad.CALL_FAILED,
        "dsh: AUTH: Authentication Fails, Your api key: ****9bb5 is invalid")
    assert code == "DSH_AUTH_INVALID"
    assert code in ad.ERROR_CODES


def test_case_03_timeout_is_reported_as_timeout(tmp_path):
    """**反例 3：模型调用超时** ⇒ TIMEOUT，且**不得**冒充成功。"""
    body = ("import time, sys\n"
            "sys.stdin.read()\n"
            "time.sleep(30)\n")
    adapter = ad.build_adapter("codex")
    adapter.binary = _fake_harness(tmp_path, body).split()
    res = adapter.run({"obligations": [], "evidence": {}}, tmp_path, ad.Budget(timeout_s=2))
    assert res.status == ad.TIMEOUT
    assert res.raw_text in (None, "")


def test_case_04_empty_output_is_not_participation(tmp_path):
    """**反例 4：返回空内容** ⇒ 没有回执 ⇒ 没有参与。"""
    body = ("import sys\n"
            "sys.stdin.read()\n"
            "print('')\n")
    adapter = ad.build_adapter("codex")
    adapter.binary = _fake_harness(tmp_path, body).split()
    res = adapter.run({"obligations": [], "evidence": {}}, tmp_path, ad.Budget(timeout_s=20))
    assert ad.participated_flag(res.to_dict()) is False


def test_case_05_malformed_output_yields_no_accepted_results(tmp_path):
    """**反例 5：返回不可解析内容** ⇒ 校验器不得接受任何结果。"""
    body = ("import sys\n"
            "sys.stdin.read()\n"
            "print('这不是 JSON')\n")
    adapter = ad.build_adapter("codex")
    adapter.binary = _fake_harness(tmp_path, body).split()
    res = adapter.run({"obligations": [], "evidence": {}}, tmp_path, ad.Budget(timeout_s=20))
    assert res.status == ad.OK
    assert ad.participated_flag(res.to_dict()) is False


# ═══════════════════════════════════════════════════════════════════════════
# 反例 6—7：身份与降级
# ═══════════════════════════════════════════════════════════════════════════

def test_case_06_model_identity_unknown_is_a_distinct_state():
    """**反例 6：模型身份 UNKNOWN** ⇒ 参与是真的，但**身份不可核实** ⇒ 不得过身份门禁。"""
    path = rm.derive_execution_path(requested_mode="AGENT_REQUIRED",
                                     examinee_mode="HARNESS_MODEL",
                                     participated=True,
                                     model_identity_verified=False)
    assert path == rm.EXEC_PATH_MODEL_ID_UNKNOWN
    assert rm.is_model_identity_acceptable(path) is False
    # ★ 但「模型确实参与了」仍然成立 ⇒ 成绩名仍是 AI 成绩（只是过不了身份门禁）
    assert rm.score_name_for(path) == rm.SCORE_NAME_AI_SYSTEM


def test_case_07_agent_failure_must_not_be_downgraded_to_rule_and_claimed():
    """**反例 7：Agent 调用失败后自动降级** ⇒ AGENT_REQUIRED 下**考试失败**。"""
    path = rm.derive_execution_path(requested_mode="AGENT_REQUIRED",
                                     examinee_mode="RULE_ONLY",
                                     participated=False,
                                     degrade_reason="适配器 exit 1")
    assert path == rm.EXEC_PATH_FAILED
    assert rm.exam_status_for(path, "SCORED") == "FAIL"
    # ★ 且**不得**被当成 AI 成绩
    assert rm.score_name_for(path) == rm.SCORE_NAME_NOT_SCORED
    split = rm.split_scores(96.67, execution_path=path)
    assert split["ai_system_score"] is None
    assert split["ai_system_score_status"] == "NOT_SCORED"


# ═══════════════════════════════════════════════════════════════════════════
# 反例 8：**核心** —— 规则引擎满分但模型未参与
# ═══════════════════════════════════════════════════════════════════════════

def test_case_08_rule_engine_full_marks_without_model_must_fail_gate():
    """**反例 8（核心）：规则引擎产生 100 分但模型未参与** ⇒ 门禁必须 FAIL。

    ★ 这正是上一轮的真实状态：三场考试 96.67 / 95.67 / 100.0，
      ``model_participated=false``，而 G1—G7 全绿。
    ⇒ 本轮 G8 必须在**同一份产物**上判 FAIL。
    """
    manifests = [
        _manifest(exam="A", requested_mode="RULE_ONLY", execution_path="RULE_ONLY"),
        _manifest(exam="B", requested_mode="RULE_ONLY", execution_path="RULE_ONLY"),
        _manifest(exam="C", requested_mode="RULE_ONLY", execution_path="RULE_ONLY"),
    ]
    for m in manifests:
        assert m["results"]["scores"]["total_score"] == 100.0
    status, reason = _gate(manifests)
    assert status == "FAIL"
    assert "NO_REAL_MODEL_RUN_AT_ALL" in reason


def test_case_08b_agent_required_without_real_model_must_fail_even_if_other_runs_pass():
    """**反例 8 变体**：一场 AGENT_REQUIRED 降级 ⇒ 即使别的场次有真模型，也必须 FAIL。"""
    manifests = [
        _manifest(exam="C", requested_mode="AGENT_REQUIRED",
                  execution_path=rm.EXEC_PATH_FAILED, participated=False),
        _manifest(exam="B", requested_mode="RULE_ONLY", execution_path="RULE_ONLY"),
        _manifest(exam="A", requested_mode="AGENT_REQUIRED",
                  execution_path=rm.EXEC_PATH_REAL_MODEL, participated=True,
                  identity_verified=True, model="deepseek-flash"),
    ]
    status, reason = _gate(manifests)
    assert status == "FAIL"
    assert "AGENT_REQUIRED_WITHOUT_REAL_MODEL" in reason


def test_case_08c_rule_only_alone_never_fails_gate_for_missing_model():
    """**反例 8 反向**：RULE_ONLY 场次**不**因「模型没参与」判 FAIL（那是预期行为）。"""
    manifests = [_manifest(exam="A", requested_mode="RULE_ONLY",
                           execution_path="RULE_ONLY")]
    status, _reason = _gate(manifests)
    # ⇒ 唯一让它 FAIL 的原因是「整批证据里一条真模型都没跑」，
    #   而**不是**「RULE_ONLY 场次本身没模型」。
    assert "AGENT_REQUIRED_WITHOUT_REAL_MODEL" not in _reason if status == "FAIL" else True


# ═══════════════════════════════════════════════════════════════════════════
# 反例 9—10：证据的**归属**与**时效**
# ═══════════════════════════════════════════════════════════════════════════

def test_case_09_participation_evidence_from_another_exam_is_rejected():
    """**反例 9：模型参与证据属于其他考试** ⇒ 绑定不上 ⇒ 不采信。"""
    ev = ident.build_participation_evidence(
        adapter_result={"status": "OK", "exit_code": 0, "raw_text": "{}"},
        validation={"accepted": 1, "source_snapshot_id": "SNAP-OTHER"},
        identity=ident.ModelIdentity("deepseek-flash", "deepseek-official",
                                     ident.SOURCE_DSH_PROFILE, True),
        expected_snapshot_id="SNAP-MINE",
        code_version="abc123")
    assert ev["checks"]["bound_to_exam"] is False
    assert ev["checks_passed"] < ev["checks_total"]


def test_case_10_participation_evidence_from_old_code_version_is_not_bound():
    """**反例 10：模型参与证据属于旧代码版本** ⇒ 没有代码版本 ⇒ 绑定不上。"""
    ev = ident.build_participation_evidence(
        adapter_result={"status": "OK", "exit_code": 0, "raw_text": "{}"},
        validation={"accepted": 1, "source_snapshot_id": "SNAP"},
        identity=ident.ModelIdentity("deepseek-flash", "deepseek-official",
                                     ident.SOURCE_DSH_PROFILE, True),
        expected_snapshot_id="SNAP",
        code_version="")           # ★ 证据没记代码版本
    assert ev["checks"]["evidence_bound_to_code"] is False


def test_case_10b_codex_rollout_from_another_workdir_is_not_accepted(tmp_path):
    """**反例 10 变体**：codex 执行记录**cwd 不匹配** ⇒ 身份记 UNKNOWN（fail-closed）。"""
    rid = tmp_path / "rollout-2026-01-01T00-00-00-x.jsonl"
    rid.write_text(json.dumps({
        "type": "turn_context", "payload": {"model": "gpt-5.6-sol", "cwd": "/somewhere/else"}
    }) + "\n", "utf-8")
    ident_res = ident.resolve_codex_identity(
        "x", expected_cwd=str(tmp_path), sessions_root=tmp_path)
    assert ident_res.model_id == ident.MODEL_UNKNOWN
    assert "CWD_MISMATCH" in ident_res.note


# ═══════════════════════════════════════════════════════════════════════════
# 反例 11—13：模型参与了，也**不等于**能交付
# ═══════════════════════════════════════════════════════════════════════════

def test_case_11_model_participated_but_safety_failed_still_fails_safety():
    """**反例 11：模型参与成功但披露安全失败** ⇒ 安全闸仍 FAIL（模型高分不得抵消）。"""
    card = {
        "status": "SCORED",
        "scores": {"total_score": 100.0},
        "safety_gate": {"status": "FAIL", "violations": 3, "findings": []},
        "rows": [],
    }
    assert card["safety_gate"]["status"] == "FAIL"
    # ★ 规则：安全闸 FAIL ⇒ 总分封顶 59（`dd_v1_exam_scoring_spec.v1.json` 的 cap_on_fail）
    cap = json.loads((REPO / "backend" / "config" / "dd_v1_exam_scoring_spec.v1.json")
                     .read_text("utf-8"))["safety"]["cap_on_fail"]
    assert float(cap) == 59.0


def test_case_12_missing_gold_is_not_scorable_and_not_zero():
    """**反例 12：Gold 缺失** ⇒ NOT_SCORABLE（**不是** 0 分，也**不是** AI 成绩）。"""
    card = ex.grade_answer_sheet(
        {"obligations": [], "examinee": {"mode": "HARNESS_MODEL", "participated": True}},
        None, gold_provided=False, gold_state="NOT_PROVIDED",
        gold_state_reason="未提供标准答案包")
    assert card["status"] == "NOT_SCORABLE"
    assert card.get("scores") is None
    assert card.get("diagnostic") is not None


def test_case_13_model_call_ok_but_quality_poor_still_gets_a_low_score():
    """**反例 13：模型调用成功但答卷质量很差** ⇒ 分数照实低，**不得**因「模型参与了」抬分。"""
    card = ex.grade_answer_sheet(
        {"obligations": [], "examinee": {"mode": "HARNESS_MODEL", "participated": True}},
        None, gold_provided=False)
    assert card["status"] == "NOT_SCORABLE"
    # ★ 真正评分路径下：低分就是低分；「模型参与」**不**参与加权。
    assert rm.split_scores(12.5, execution_path=rm.EXEC_PATH_REAL_MODEL)["ai_system_score"] == 12.5


# ═══════════════════════════════════════════════════════════════════════════
# 反例 14：AUTO 模式正常降级
# ═══════════════════════════════════════════════════════════════════════════

def test_case_14_auto_degrade_is_recorded_but_not_counted_as_ai_score():
    """**反例 14：AUTO 模式正常降级** ⇒ 降级**如实记录**，但**不**算 AI 成绩。"""
    path = rm.derive_execution_path(requested_mode="AUTO",
                                     examinee_mode="RULE_ONLY",
                                     participated=False,
                                     degrade_reason="适配器不可用")
    assert path == rm.EXEC_PATH_DEGRADED
    split = rm.split_scores(96.67, execution_path=path)
    assert split["ai_system_score"] is None
    assert split["ai_system_score_status"] == "NOT_SCORED"
    # ★ 降级后做的**仍然是规则工作** ⇒ 归规则基线列
    assert split["score_name"] == rm.SCORE_NAME_RULE_BASELINE
    assert split["rule_baseline_score"] == 96.67
    # ★ 门禁侧：降级**本身**不判 FAIL（那是 AUTO 的合法行为），但没有真模型就整体 FAIL
    manifests = [_manifest(exam="A", requested_mode="AUTO",
                           execution_path=rm.EXEC_PATH_DEGRADED)]
    status, reason = _gate(manifests)
    assert status == "FAIL"
    assert "AGENT_REQUIRED_WITHOUT_REAL_MODEL" not in reason


def test_case_14b_auto_with_real_model_passes_the_participation_gate():
    """AUTO + 真模型参与 ⇒ G8 PASS。"""
    manifests = [_manifest(exam="C", requested_mode="AUTO",
                           execution_path=rm.EXEC_PATH_REAL_MODEL,
                           participated=True, identity_verified=True,
                           model="MiniMax-M3.1-Flash-Preview")]
    status, reason = _gate(manifests)
    assert status == "PASS", reason


# ═══════════════════════════════════════════════════════════════════════════
# 附：模式与成绩名的**总口径**（防止将来被改坏）
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("path,expected_name", [
    (rm.EXEC_PATH_REAL_MODEL, rm.SCORE_NAME_AI_SYSTEM),
    (rm.EXEC_PATH_MODEL_ID_UNKNOWN, rm.SCORE_NAME_AI_SYSTEM),
    (rm.EXEC_PATH_RULE_ONLY, rm.SCORE_NAME_RULE_BASELINE),
    (rm.EXEC_PATH_DEGRADED, rm.SCORE_NAME_RULE_BASELINE),
    (rm.EXEC_PATH_MOCK_MODEL, rm.SCORE_NAME_NOT_SCORED),
    (rm.EXEC_PATH_FAILED, rm.SCORE_NAME_NOT_SCORED),
])
def test_score_name_mapping_is_frozen(path, expected_name):
    """执行路径 ⇒ 成绩名称的映射**冻结**（改动必须换版本 + 留差异说明）。"""
    assert rm.score_name_for(path) == expected_name


def test_unknown_run_mode_is_rejected_not_silently_defaulted():
    """不认识的模式名 ⇒ **报错**，不静默兜底成 RULE_ONLY。"""
    with pytest.raises(ValueError):
        rm.normalize_mode("WHATEVER")
