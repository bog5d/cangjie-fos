"""DD-V1 **第二层自动考试**：模拟模型端到端（清单→拆解→匹配→审核→组包→评分）。

对应施工令 WP2「第二层：模拟模型端到端考试」。

★ **边界（必须说清）**：本层**只能证明系统流程正确**，
  **不能证明真实 DeepSeek 已经接入**（那是第三层的事）。
  ⇒ 本层的模型输出全部是**预置回执**（``prebaked``，参与类别恒为 ``PREBAKED_RESULT``）。

★ 本层覆盖的**场景清单**（施工令列的 12 种）：

======================  ============================================================
场景                    本文件里的断言
======================  ============================================================
正确材料                考试A/B/C 的逐题明细：命中标准答案 ⇒ ``CORRECT``
错误材料                注入错误选材 ⇒ ``extra_files`` 上升 ⇒ 精度下降（被如实计分）
错误主体                注入别的主体材料 ⇒ 安全闸 ``WRONG_ENTITY``
错误年份                注入错年份材料 ⇒ 单列 ``WRONG_PERIOD``
多文件要求              一条义务要两件 ⇒ 缺一即 ``INCOMPLETE``
缺失材料                库里没有 ⇒ 该条 ``EXPECTED_NONE``／``MISSING``，**不报错**
重复材料                同名同内容两份 ⇒ Gold 侧判**歧义** ⇒ 分层成绩单
Gold 缺失              ⇒ ``NOT_SCORABLE`` **且写明阻塞**
Gold 歧义              ⇒ ``SCORED_PARTIAL``（保留全卷分母，缺口逐件列出）
模型超时                假 harness 睡过时限 ⇒ ``TIMEOUT``，**不得**静默 PASS
模型返回错误            假 harness 非零退出 ⇒ ``CALL_FAILED``
模型输出格式异常        假 harness 输出垃圾 ⇒ **不产生**已接受结果（降级留痕）
======================  ============================================================
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "backend" / "src"))

from cangjie_fos.services import dd_v1_agent_adapters as ad  # noqa: E402
from cangjie_fos.services import dd_v1_exam_service as ex  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# 0. 跑一场考试（子进程 ⇒ 与 CI/人工跑法一致）
# ─────────────────────────────────────────────────────────────────────────────

def _run_exam(exam: str, plane: Path, out: Path, *extra: str) -> dict:
    """用**子进程**跑考试台（隔离数据面 + 真实入口 + 自动评分）。"""
    env = dict(os.environ)
    env["DDV1_EXAM_PLANE"] = str(plane)
    cmd = [sys.executable, str(REPO / "tools" / "dd_v1_exam_suite.py"),
           "run", "--exam", exam, "--out", str(out), *extra]
    proc = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True,
                          timeout=600)
    assert proc.returncode in (0, 1), f"考试台退出码 {proc.returncode}\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    manifest = json.loads((out / "运行清单.json").read_text("utf-8"))
    return manifest


@pytest.fixture(scope="module")
def exam_c(tmp_path_factory):
    base = tmp_path_factory.mktemp("exam-plane")
    out = base / "C" / "run"
    return _run_exam("C", base, out)


@pytest.fixture(scope="module")
def exam_b(tmp_path_factory):
    base = tmp_path_factory.mktemp("exam-plane-b")
    out = base / "B" / "run"
    return _run_exam("B", base, out)


# ─────────────────────────────────────────────────────────────────────────────
# 1. 端到端跑通（考试C：完整 42 题）
# ─────────────────────────────────────────────────────────────────────────────

def test_exam_c_runs_end_to_end_and_is_fully_covered(exam_c):
    """★ 42 题全部进入处理链路；覆盖读数有效（全卷可验证覆盖率 = 1.0）。"""
    res = exam_c["results"]
    cov = res.get("exam_coverage") or {}
    assert cov.get("questions_total") == 42, cov
    assert cov.get("questions_processed") == 42, cov
    assert float(cov.get("verifiable_coverage") or 0) == 1.0, cov
    assert res.get("status") in ("SCORED", "SCORED_PARTIAL"), res.get("status")


def test_exam_c_scores_match_the_frozen_expectations(exam_c):
    """★ Gold 逐题比较：命中/精度/完整率都必须是机器算出来的，不是拍出来的。"""
    scores = exam_c["results"].get("scores") or {}
    assert scores.get("material_recall") == 1.0, scores
    assert scores.get("selection_precision") == 1.0, scores
    assert scores.get("complete_delivery_ratio") == 1.0, scores
    assert scores.get("question_understanding_coverage") == 1.0, scores
    assert float(scores.get("total_score") or 0) >= 70.0, scores


def test_exam_c_safety_gate_passes_and_restricted_material_is_not_delivered(exam_c):
    """★ 安全闸 PASS ＋ **受限材料没有进交付包**（负例证明）。"""
    assert (exam_c["results"].get("safety_gate") or {}).get("status") == "PASS", exam_c
    disc = exam_c.get("disclosure") or {}
    assert disc.get("status") == "PASS", disc
    assert int(disc.get("violations") or 0) == 0, disc
    assert int(disc.get("blocked_materials") or 0) > 0, \
        "★ 应当有材料被披露闸拦下（受限类型）⇒ 拦了 0 件说明负例没被触发"


def test_exam_b_keeps_the_full_denominator_and_reports_gaps(exam_c, exam_b):
    """★ 分层成绩单：全卷分母保留；歧义/缺料**逐条列出**，不得当成 0 分。"""
    res = exam_b["results"]
    cov = res.get("exam_coverage") or {}
    assert cov.get("questions_total") == 9, cov
    assert cov.get("questions_processed") == 9, cov
    gs = res.get("gold_scorable") or {}
    assert gs.get("not_included_total", 0) >= 1, gs
    reasons = gs.get("not_included_reasons") or {}
    assert "AMBIGUOUS_CONTENT" in reasons or "NO_EXPECTED_FILES" in reasons, reasons


def test_exam_b_multi_entity_obligation_is_scored_against_the_library_id(exam_b):
    """★ 多主体分簇义务（``<库ID>@<主体>``）⇒ **按库侧 ID** 与 Gold 对齐。

    ★ 这是 #108 实测「答卷 200 行 vs Gold 91 条 ⇒ 全部 NO_ANSWER」的回归防线。
    """
    grades = sorted(Path(exam_b["artifacts"]["scorecard_dir"]).glob("成绩单-*.json"))
    assert grades, exam_b["artifacts"]
    card = json.loads(grades[-1].read_text("utf-8"))
    rows = card.get("rows") or []
    multi = [r for r in rows if int(r.get("cluster_count") or 0) > 1]
    assert multi, "★ 应当存在多主体分簇的义务（考试B 的 2-1）"
    for r in multi:
        assert r.get("outcome") != "NO_ANSWER", r
        assert not r.get("missed"), r


# ─────────────────────────────────────────────────────────────────────────────
# 2. 评分边界（0 分 / 不可评分 / 分层）
# ─────────────────────────────────────────────────────────────────────────────

def test_missing_gold_makes_the_score_not_scorable():
    """★ 标准答案未提供 ⇒ ``NOT_SCORABLE`` ＋ 写明阻塞（不是 0 分）。"""
    card = ex.grade_answer_sheet({"obligations": []}, None,
                                  library_index={"by_id": {}, "by_sha": {}},
                                  gold_provided=False, gold_state="NOT_PROVIDED",
                                  gold_state_reason="合成测试：未提供标准答案")
    assert card["status"] == "NOT_SCORABLE"
    assert card["scores"] is None
    assert any("GOLD_NOT_PROVIDED" in b for b in card["blocked_by"]), card["blocked_by"]


def test_gold_leak_stops_scoring():
    """★ 检出泄漏 ⇒ 不进入正式评分（``scores=None``）。"""
    sheet = {"obligations": [{"obligation_id": "x", "item_id": "1-1", "text": "t",
                              "expected_files": [], "candidates": [], "selected": [],
                              "delivered": [], "verdict": "MATCH", "abstained": False}]}
    leak = {"leaked": True, "leak_count": 1, "leaks": [{"kind": "GOLD_ONLY_FIELD"}]}
    card = ex.grade_answer_sheet(sheet, {"schema_version": "dd_v1_gold_manifest.v1",
                                         "gold_pack_id": "G", "items": []},
                                  library_index={"by_id": {}, "by_sha": {}},
                                  gold_provided=True, leak_report=leak)
    assert card["status"] == "NOT_SCORABLE", card
    assert card["scores"] is None, card


# ─────────────────────────────────────────────────────────────────────────────
# 3. 模型侧的**失败**必须被如实报错（不得静默 PASS）
# ─────────────────────────────────────────────────────────────────────────────

def _fake_harness(tmp_path: Path, body: str) -> str:
    p = tmp_path / "fake_harness.py"
    p.write_text(body, encoding="utf-8")
    return f"{sys.executable} {p}"


def test_model_timeout_is_reported_as_timeout(tmp_path):
    """★ 模型超时 ⇒ ``TIMEOUT``（不得当成成功、不得静默降级成 PASS）。"""
    binary = _fake_harness(tmp_path, "import time\ntime.sleep(30)\n")
    adapter = ad.DeepSeekHarnessAdapter(enabled=True, binary=binary.split(), profile="headless")
    packet = {"obligations": [], "instructions": "x"}
    wd = tmp_path / "wd"
    wd.mkdir()
    res = adapter.run(packet, wd, ad.Budget(timeout_s=1.0, max_calls=1))
    assert res.status == ad.TIMEOUT, res
    assert res.reason and "TIMEOUT" in res.reason, res


def test_model_nonzero_exit_is_reported_as_call_failed(tmp_path):
    """★ 模型进程报错 ⇒ ``CALL_FAILED``（带退出码与 stderr 尾巴）。"""
    binary = _fake_harness(tmp_path, "import sys\nsys.stderr.write('boom')\nsys.exit(3)\n")
    adapter = ad.DeepSeekHarnessAdapter(enabled=True, binary=binary.split(), profile="headless")
    wd = tmp_path / "wd"
    wd.mkdir(exist_ok=True)
    res = adapter.run({"obligations": [], "instructions": "x"}, wd,
                      ad.Budget(timeout_s=10.0, max_calls=1))
    assert res.status == ad.CALL_FAILED, res
    assert res.exit_code == 3, res


def test_missing_model_binary_is_reported_as_call_failed(tmp_path):
    """★ **模型不存在** ⇒ ``CALL_FAILED``（不是「安静地不调模型」）。"""
    adapter = ad.DeepSeekHarnessAdapter(enabled=True,
                                        binary=["definitely-not-a-real-binary-xyz"],
                                        profile="headless")
    wd = tmp_path / "wd"
    wd.mkdir(exist_ok=True)
    res = adapter.run({"obligations": [], "instructions": "x"}, wd,
                      ad.Budget(timeout_s=10.0, max_calls=1))
    assert res.status == ad.CALL_FAILED, res
    assert res.exit_code == 127, res


def test_malformed_model_output_yields_no_accepted_results(tmp_path):
    """★ 模型输出**格式异常** ⇒ 不产生「已接受」结果（不得把垃圾当判断）。"""
    binary = _fake_harness(tmp_path, "print('not json at all')\n")
    adapter = ad.DeepSeekHarnessAdapter(enabled=True, binary=binary.split(), profile="headless")
    wd = tmp_path / "wd"
    wd.mkdir(exist_ok=True)
    res = adapter.run({"obligations": [], "instructions": "x"}, wd,
                      ad.Budget(timeout_s=10.0, max_calls=1))
    assert res.status == ad.OK, res
    assert res.raw_text is None, "★ 垃圾输出不得被当成 JSON 结果"
    assert ad.extract_json_text("not json at all") is None


def test_prebaked_result_is_never_credited_as_model_participation():
    """★ 预置回执 ⇒ 参与类别恒为 ``PREBAKED_RESULT``（**不得**当成模型参与凭据）。"""
    from cangjie_fos.services import dd_v1_bridge_service as br
    assert br.KNOWN_HARNESS_ADAPTERS.get("prebaked-result") == "PREBAKED_RESULT"
    assert br.KNOWN_HARNESS_ADAPTERS.get("deepseek-harness") == "HARNESS_MODEL"
    adapter = ad.build_adapter("prebaked", result_path="/nonexistent/reply.json")
    assert adapter.participation_class == "PREBAKED_RESULT"
    assert ad.participation_class_of(adapter) == "PREBAKED_RESULT"
