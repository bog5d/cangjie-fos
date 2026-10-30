"""交付门禁的**绑定确定性**回归（amendment A4）。

★ 要防的坑：**判定结果与证据目录名耦合** ——
同一场考试（`exam` 字段相同）可能有多次运行（规则基线 ＋ 若干次真实模型），
若按「路径排序取最后一个」，换个目录名就可能换掉被判定的那一次。

覆盖：
- exam 级门槛**恒**绑定到该考试的**规则基线**运行（确定性）；
- **G3 / G8 仍然看全部运行清单**（真实模型运行照样参与判定 ⇒ 没有门槛被放松）；
- 门禁报告的 `all_runs` 如实列出**每一次**运行；
- 目录名**不影响**判定结果。

不调用真实模型、不联网：用**手写的运行清单**喂门禁判定。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "backend" / "src"))

import dd_v1_exam_suite as suite  # noqa: E402

GATE_SPEC = json.loads((REPO / "backend" / "config" / "dd_v1_delivery_gate.v1.json").read_text("utf-8"))


def _manifest(exam: str, run_id: str, *, mode: str, path: str, score: float = 96.67,
              participated: bool = False, verified: bool = False,
              agent: str = "", status: str = "LOW_CONFIDENCE") -> dict:
    return {
        "exam": exam, "run_id": run_id, "git_sha": "deadbeef" * 5, "git_dirty": False,
        "model": {
            "agent_spec": agent, "requested_mode": mode, "execution_path": path,
            "participated": participated, "model_identity_verified": verified,
            "actual_model": ("deepseek-flash" if agent == "dsh" else ""),
            "score_split": {"score_name": "AI_SYSTEM_SCORE" if participated else "RULE_BASELINE_SCORE"},
        },
        "results": {
            "status": status, "rc_run": 0, "total_score": score,
            "scores": {"total_score": score, "question_understanding_coverage": 0.667,
                       "material_recall": 1.0, "selection_precision": 1.0,
                       "complete_delivery_ratio": 1.0, "miss_rate": 0.0, "wrong_rate": 0.0},
            "exam_coverage": {"questions_processed": 3, "questions_total": 3, "verifiable_coverage": 1.0},
            "counts": {"delivered_files": 2, "delivered_files_attributed": 2},
            "safety_gate": {"status": "PASS", "violations": 0},
        },
    }


def _write(tmp_path: Path, manifests: dict[str, dict]) -> Path:
    for sub, m in manifests.items():
        d = tmp_path / sub
        d.mkdir(parents=True, exist_ok=True)
        (d / "运行清单.json").write_text(json.dumps(m, ensure_ascii=False, indent=2), "utf-8")
    return tmp_path


def _gate(tmp_path: Path) -> dict:
    return suite.evaluate_gate(str(tmp_path), gate_spec=GATE_SPEC)


def test_exam_gates_bind_to_rule_baseline_not_directory_order(tmp_path):
    """★ 规则基线 + 真实模型**同一场考试** ⇒ exam 级门槛必须绑到**规则基线**那次。"""
    runs = _write(tmp_path, {
        "A": _manifest("A", "20261030T010000Z", mode="RULE_ONLY", path="RULE_ONLY", score=96.67),
        # 真实模型运行放在**排序更靠后**的目录名上（原实现会取到它）
        "A-dsh": _manifest("A", "20261030T020000Z", mode="AGENT_REQUIRED",
                                   path="REAL_MODEL", score=77.5, participated=True,
                                   verified=True, agent="dsh"),
    })
    rep = _gate(runs)
    g2 = rep["gates"]["G2"]
    assert g2["status"] == "PASS", g2
    assert g2["run_id"] == "20261030T010000Z", f"G2 绑错了运行：{g2}"


def test_directory_name_does_not_change_verdict(tmp_path):
    """★ 同一批运行换目录名 ⇒ 判定结果**必须逐位一致**（原来会变）。"""
    base = _manifest("A", "20261030T010000Z", mode="RULE_ONLY", path="RULE_ONLY", score=96.67)
    agent = _manifest("A", "20261030T020000Z", mode="AGENT_REQUIRED", path="REAL_MODEL",
                      score=77.5, participated=True, verified=True, agent="dsh")
    r1 = _gate(_write(tmp_path / "x", {"A": base, "A-dsh": agent}))
    r2 = _gate(_write(tmp_path / "y", {"A": base, "A-agent": agent}))
    for gid in ("G2", "G3", "G8"):
        assert r1["gates"][gid]["status"] == r2["gates"][gid]["status"], (gid, r1["gates"][gid], r2["gates"][gid])
    assert r1["gates"]["G2"]["run_id"] == r2["gates"]["G2"]["run_id"]


def test_g3_and_g8_still_see_real_model_runs(tmp_path):
    """★ 真实模型运行**照样**参与 G3/G8 判定 ⇒ A4 没有放松任何门槛。"""
    runs = _write(tmp_path, {
        "A": _manifest("A", "20261030T010000Z", mode="RULE_ONLY", path="RULE_ONLY"),
        "A-dsh": _manifest("A", "20261030T020000Z", mode="AGENT_REQUIRED", path="REAL_MODEL",
                                participated=True, verified=True, agent="dsh"),
    })
    rep = _gate(runs)
    assert rep["gates"]["G3"]["status"] == "PASS", rep["gates"]["G3"]
    assert rep["gates"]["G8"]["status"] == "PASS", rep["gates"]["G8"]


def test_g8_still_fails_when_only_rule_only_evidence_exists(tmp_path):
    """★ 反例：证据里**全是 RULE_ONLY** ⇒ G8 必须 FAIL（哪怕分数漂亮）。"""
    runs = _write(tmp_path, {
        "A": _manifest("A", "20261030T010000Z", mode="RULE_ONLY", path="RULE_ONLY", score=100.0),
    })
    rep = _gate(runs)
    assert rep["gates"]["G8"]["status"] == "FAIL", rep["gates"]["G8"]
    assert "NO_REAL_MODEL_RUN_AT_ALL" in rep["gates"]["G8"]["reason"]


def test_g8_fails_when_agent_required_run_degraded(tmp_path):
    """★ AGENT_REQUIRED 却降级 ⇒ G8 FAIL（不许静默降级后算 AI 成绩）。"""
    runs = _write(tmp_path, {
        "A": _manifest("A", "20261030T010000Z", mode="RULE_ONLY", path="RULE_ONLY"),
        "A-dsh": _manifest("A", "20261030T020000Z", mode="AGENT_REQUIRED", path="DEGRADED",
                                participated=False, verified=False, agent="dsh"),
    })
    rep = _gate(runs)
    assert rep["gates"]["G8"]["status"] == "FAIL", rep["gates"]["G8"]
    assert "AGENT_REQUIRED_WITHOUT_REAL_MODEL" in rep["gates"]["G8"]["reason"]


def test_all_runs_lists_every_run(tmp_path):
    """★ 门禁报告必须**如实列出每一次运行**（不只显示被绑定的那一次）。"""
    runs = _write(tmp_path, {
        "A": _manifest("A", "20261030T010000Z", mode="RULE_ONLY", path="RULE_ONLY"),
        "A-dsh": _manifest("A", "20261030T020000Z", mode="AGENT_REQUIRED", path="REAL_MODEL",
                                participated=True, verified=True, agent="dsh"),
        "A-pi": _manifest("A", "20261030T030000Z", mode="AGENT_REQUIRED", path="REAL_MODEL",
                               participated=True, verified=True, agent="pi"),
    })
    rep = _gate(runs)
    runs_list = rep["all_runs"]
    assert len(runs_list) == 3, runs_list
    assert {r["requested_mode"] for r in runs_list} == {"RULE_ONLY", "AGENT_REQUIRED"}
    assert {r["agent_spec"] for r in runs_list} == {"", "dsh", "pi"}


def test_gate_spec_has_amendment_a4_recording_no_threshold_change():
    """★ 绑定规则变更必须在冻结文件里**留 amendment**，并写明阈值未改。"""
    ids = [a["id"] for a in GATE_SPEC.get("amendments") or []]
    assert "A4" in ids, ids
    a4 = next(a for a in GATE_SPEC["amendments"] if a["id"] == "A4")
    assert "thresholds_unchanged" in a4 and a4["thresholds_unchanged"]
    assert "G8" in a4["thresholds_unchanged"]


def test_key_gates_include_g8():
    assert "G8" in (GATE_SPEC.get("key_gates") or [])


# ═══════════════════════════════════════════════════════════════════════════
# 代理口径（pytest-report 的环境口径：**结果不应随操作员的代理设置漂移**）
# ═══════════════════════════════════════════════════════════════════════════

def test_proxy_policy_overrides_socks_with_http():
    """★ 本机 all_proxy 是 SOCKS ⇒ httpx 构造阶段就抛 ImportError ⇒ 6 条 DD 精判用例假红。

    ⇒ 口径：把 SOCKS **改写成同端口的 http 代理**，而不是「清空变量」
    （清空会让 httpx 回落到 macOS 系统代理，仍是 SOCKS ⇒ 照旧假红）。
    """
    base = {"all_proxy": "socks5://127.0.0.1:7897", "ALL_PROXY": "socks5://127.0.0.1:7897",
            "http_proxy": "http://127.0.0.1:7897", "HTTP_PROXY": "http://127.0.0.1:7897",
            "https_proxy": "http://127.0.0.1:7897", "HTTPS_PROXY": "http://127.0.0.1:7897",
            "PATH": "/usr/bin"}
    env, note = suite._proxy_sanitized_env(base)
    assert env["ALL_PROXY"].startswith("http://"), env["ALL_PROXY"]
    assert "socks" not in env["ALL_PROXY"].lower()
    assert note.startswith("SOCKS_PROXY_OVERRIDDEN_TO_HTTP")
    assert env["PATH"] == "/usr/bin", "非代理变量不得被动"


def test_proxy_policy_clears_when_no_http_proxy_available():
    """★ 没有 http 代理可用 ⇒ 至少要把 SOCKS **清掉**（不许把 SOCKS 传下去）。"""
    base = {"all_proxy": "socks5://127.0.0.1:7897", "ALL_PROXY": "socks5://127.0.0.1:7897"}
    env, note = suite._proxy_sanitized_env(base)
    assert "ALL_PROXY" not in env and "all_proxy" not in env
    assert note.startswith("PROXY_VARS_CLEARED")


def test_proxy_policy_is_deterministic_across_calls():
    """★ 同一输入 ⇒ 同一输出（**结果不随调用次数/环境漂移**）。"""
    base = {"ALL_PROXY": "socks5://127.0.0.1:7897", "HTTPS_PROXY": "http://127.0.0.1:7897"}
    e1, n1 = suite._proxy_sanitized_env(base)
    e2, n2 = suite._proxy_sanitized_env(base)
    assert e1 == e2 and n1 == n2


# ═══════════════════════════════════════════════════════════════════════════
# NIT-1（AUTO + 身份 UNKNOWN 不许放行）＋ MINOR-4（G3 reason 补全参与面）
# ═══════════════════════════════════════════════════════════════════════════

def test_g8_fails_when_any_run_has_unverified_model_identity(tmp_path):
    """★ AUTO + ``MODEL_ID_UNKNOWN`` ⇒ **G8 FAIL**（施工令 §6：不得通过模型身份门禁）。

    ★ 此前（NIT-1）它只是被计数、**不拦** ⇒ 批次里有一次已核实真模型就能整体 PASS
      ⇒ 现改为**加严**：只要有「真模型参与但身份核实不出来」的运行 ⇒ FAIL。
    """
    runs = _write(tmp_path, {
        "A": _manifest("A", "20261030T010000Z", mode="RULE_ONLY", path="RULE_ONLY"),
        "A-dsh": _manifest("A", "20261030T020000Z", mode="AGENT_REQUIRED", path="REAL_MODEL",
                           participated=True, verified=True, agent="dsh"),
        "A-auto": _manifest("A", "20261030T030000Z", mode="AUTO", path="MODEL_ID_UNKNOWN",
                            participated=True, verified=False, agent="pi"),
    })
    rep = _gate(runs)
    assert rep["gates"]["G8"]["status"] == "FAIL", rep["gates"]["G8"]
    assert "MODEL_ID_UNKNOWN_NOT_ACCEPTED" in rep["gates"]["G8"]["reason"]


def test_g3_reason_lists_other_real_model_examinees(tmp_path):
    """★ MINOR-4：G3 的 reason 必须如实带上**本批其它真实模型考生**（判定口径不变）。"""
    runs = _write(tmp_path, {
        "A": _manifest("A", "20261030T010000Z", mode="RULE_ONLY", path="RULE_ONLY"),
        "A-dsh": _manifest("A", "20261030T020000Z", mode="AGENT_REQUIRED", path="REAL_MODEL",
                           participated=True, verified=True, agent="dsh"),
        "A-pi": _manifest("A", "20261030T030000Z", mode="AGENT_REQUIRED", path="REAL_MODEL",
                          participated=True, verified=True, agent="pi"),
    })
    rep = _gate(runs)
    g3 = rep["gates"]["G3"]
    assert g3["status"] == "PASS", g3
    assert "pi" in g3["reason"], g3["reason"]
    assert "codex" not in g3["reason"], g3["reason"]


def test_gate_spec_has_amendment_a5_alignment():
    """★ A5：实现与冻结评分规范对齐（错年度进闸）必须在冻结文件里留 amendment。"""
    a5 = next(a for a in GATE_SPEC["amendments"] if a["id"] == "A5")
    assert "WRONG_PERIOD" in a5["change"] or "错年度" in a5["change"]
    assert "thresholds_unchanged" in a5 and a5["thresholds_unchanged"]
