#!/usr/bin/env python3
"""DD-V1 **考试台**（自动考试环境 · 自动 Gold 评分 · 交付门禁）。

对应施工令 DD-V1｜自动化测试体系重建：
- **WP1** 隔离自动考试环境（独立数据面 / 独立库 / 固定清单 / 合成 Gold / 日志 / 成绩单）；
- **WP2** 三层自动考试的一键执行器（L1 程序层走 pytest；L2 模拟模型；L3 真实模型）；
- **WP4** 自动 Gold 评分（考试 A/B/C 三套合成卷 ⇒ 逐题明细 + 分层指标 + 成绩单）；
- **WP5** 自动交付门禁（G1—G7，阈值**考试前冻结**，不因结果事后修改）。

★ **三条硬纪律**：
1. **测试数据不碰真实业务库**：数据面固定在 ``DDV1_EXAM_PLANE``（默认 ``~/.cangjie-ddv1-exams``），
   绝不落在 ``backend/data/dd_v1``。
2. **标准答案与系统同源**：Gold 的义务标识**从库侧权威契约导出**（不手写 ID），
   且同时写**内容派生的稳定键** ``obligation_key`` ⇒ 换快照仍能绑定。
3. **证据留痕**：每次考试落一份**运行清单**（Git SHA / 环境 / 模型 / 是否真实参与 /
   数据版本 / Gold 版本 / 成绩 / 失败项），供独立复核者复跑。

**用法**::

    python tools/dd_v1_exam_suite.py list
    python tools/dd_v1_exam_suite.py run --exam A
    python tools/dd_v1_exam_suite.py run --exam B --agent prebaked --agent-result <reply.json>
    python tools/dd_v1_exam_suite.py run --exam C --agent dsh --allow-local-dsh
    python tools/dd_v1_exam_suite.py gate --runs <目录>
    python tools/dd_v1_exam_suite.py coverage --runs <目录>
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
FIXTURES = BACKEND / "tests" / "fixtures" / "dd-v1-exam-suite"
EXAMS_DIR = FIXTURES / "exams"

#: 考试台数据面（**默认在仓库之外** ⇒ 合成数据绝不污染真实业务库）
PLANE = Path(os.environ.get("DDV1_EXAM_PLANE")
             or (Path.home() / ".cangjie-ddv1-exams"))
#: 冻结门禁阈值（**考试前冻结**；不随结果改）
GATE_SPEC = BACKEND / "config" / "dd_v1_delivery_gate.v1.json"
#: 验收项清单（**覆盖率的分母**；机算覆盖率与通过率的唯一依据）
ACCEPTANCE_SPEC = BACKEND / "config" / "dd_v1_acceptance_items.v1.json"

EXAM_IDS = ("A", "B", "C")

# ★ 运行模式常量（施工令 V3.0 §6）—— 门禁判定也要用 ⇒ 提到**模块级**
sys.path.insert(0, str(BACKEND / "src"))
from cangjie_fos.services import dd_v1_run_modes as rm  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _git_sha() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                             capture_output=True, text=True, timeout=20)
        return out.stdout.strip() or "UNKNOWN"
    except Exception:  # noqa: BLE001
        return "UNKNOWN"


def _git_dirty() -> bool:
    """工作区是否有**未提交变更**（只看**被测代码**，不看证据目录）。

    ★ **语义**（独立 Reviewer 指出）：本字段要回答的是
      「**测的代码**是否等于 HEAD 的代码」。
      ⇒ 证据目录（``.audit/``）里的产物在跑门禁时**本来就在变**
      （报告本身就是产物）⇒ 若把它算进去，dirty 永远是 true，
      反而**淹没了真正的信号**（代码改了没提交）。
    ⇒ 这里**排除证据目录**，只对代码/测试/配置的未提交变更报警。
    """
    try:
        out = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                             capture_output=True, text=True, timeout=30)
        for line in (out.stdout or "").splitlines():
            path = line[3:].strip().strip('"')
            if not path:
                continue
            if path.startswith(".audit/") or path.startswith("docs/dd-v1-fos71/ddv1-auto-test-suite/"):
                continue   # ★ 证据/文档产物，不影响「被测代码 == HEAD」
            return True
        return False
    except Exception:  # noqa: BLE001
        return False


def _sha256_file(p: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def _spec(exam: str) -> dict[str, Any]:
    p = EXAMS_DIR / exam / "spec.json"
    if not p.is_file():
        raise SystemExit(f"EXAM_NOT_FOUND:{p}")
    return json.loads(p.read_text("utf-8"))


# ─────────────────────────────────────────────────────────────────────────────
# 1. 考试台数据面（WP1）
# ─────────────────────────────────────────────────────────────────────────────

def exam_plane(exam: str) -> Path:
    return PLANE / exam


def _prepare_plane(exam: str, *, reset: bool) -> Path:
    """建/复用考试数据面（★ 绝不落在仓库里）。"""
    d = exam_plane(exam)
    if reset and d.exists():
        shutil.rmtree(d)
    (d / "data").mkdir(parents=True, exist_ok=True)
    (d / "runs").mkdir(parents=True, exist_ok=True)
    return d


def _bind_data_plane(data_dir: Path) -> None:
    """把 DD-V1 数据面指到考试台（**必须在 import 服务模块之前**）。"""
    os.environ["CANGJIE_DD_V1_DATA_DIR"] = str(data_dir)


# ─────────────────────────────────────────────────────────────────────────────
# 2. 跑一场考试（WP2 / WP4）
# ─────────────────────────────────────────────────────────────────────────────

def write_exam_policy(exam: str, plane: Path) -> Path:
    """写**考场披露口径**（★ 只对**合成**材料生效；不动生产策略）。

    ★ **为什么必须有它**（#108 刘江实测阻塞③）：
      生产披露策略只放开「营业执照」一类（业务授权：董事长 2026-10-21 只放开
      营业执照/资质证照/工商公开登记信息）⇒ 审计报告等九类默认 ``RESTRICTED``
      ⇒ **任何版本、任何模型跑 42 题都会是 0 交付**（与模型能力无关）。
      ⇒ **每座考场必须有自己的披露口径**；本函数写的是**合成考场**的口径
        （材料全是虚构合成件 ⇒ 放开不涉任何真实客户材料）。
      ⇒ **真实考场仍须业务方（波总）给口径** —— 那是 BLOCKED 项，不是机器能定的。

    ★ 安全侧不放松：``default_level`` 仍是最严（``RESTRICTED``），
      未列入授权的类型（章程/出资/决议/知产/劳动/合同）**仍然不可外发**
      ⇒ 考试里刻意放了**合同类干扰材料** ⇒ 验证「受限材料不得进交付包」。
    """
    policy = {
        "policy_version": f"ddv1-exam-policy-{exam}-v1",
        "default_level": "RESTRICTED",
        "sendable_doc_types": ["license", "audit_report", "tax", "financial_statement"],
        "sensitivity_defaults": {
            "audit_report": "PUBLIC", "financial_statement": "PUBLIC",
            "tax": "PUBLIC", "license": "PUBLIC",
            "charter": "RESTRICTED", "capital": "RESTRICTED",
            "resolution": "RESTRICTED", "ip": "RESTRICTED",
            "labor": "RESTRICTED", "contract": "RESTRICTED",
        },
        "public_defaults_authorized": ["audit_report", "financial_statement",
                                       "tax", "license"],
        "levels": {
            "PUBLIC": {"externally_sendable": True, "requires_review": True,
                       "description": "合成考场口径：可对外交付（仍须逐件复核＋最终人工批准）"},
            "INTERNAL": {"externally_sendable": False, "requires_review": True,
                         "description": "内部使用"},
            "CONFIDENTIAL": {"externally_sendable": False, "requires_review": True,
                             "description": "涉商业秘密"},
            "RESTRICTED": {"externally_sendable": False, "requires_review": True,
                           "description": "一律不对外发送（安全默认）"},
        },
        "rules": [
            {"id": "R-CHARTER", "doc_type": "charter", "level": "RESTRICTED"},
            {"id": "R-CAPITAL", "doc_type": "capital", "level": "RESTRICTED"},
            {"id": "R-RESOLUTION", "doc_type": "resolution", "level": "RESTRICTED"},
            {"id": "R-IP", "doc_type": "ip", "level": "RESTRICTED"},
            {"id": "R-LABOR", "doc_type": "labor", "level": "RESTRICTED"},
            {"id": "R-CONTRACT", "doc_type": "contract", "level": "RESTRICTED"},
        ],
        "_provenance": {
            "scope": "SYNTHETIC_EXAM_ONLY",
            "note": ("★ 本文件只对**合成考场**生效（材料全部虚构）；"
                     "生产策略 `backend/config/dd_v1_disclosure_policy.json` **一字未改**。"
                     "真实考场的披露口径仍须业务方给（#108 阻塞③）。"),
        },
    }
    p = plane / f"exam-policy-{exam}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(policy, ensure_ascii=False, indent=2), "utf-8")
    os.environ["CANGJIE_DD_V1_POLICY"] = str(p)
    return p


def disclosure_assertions(out: Path, policy: dict[str, Any],
                          data_dir: Path | None = None) -> dict[str, Any]:
    """披露闸**负例**断言：受限材料**不得**出现在交付清单里。

    ★ 这是安全闸的**正向证明**（不是「没出事就算过」）：
      交付清单里出现任何**不可外发**等级/类型的材料 ⇒ 立刻 FAIL。

    ★★ **fail-closed**（防「假绿」）：**找不到交付清单 ⇒ FAIL**，不报 PASS。
      （找不到就等于「没验过」；报 PASS 就是在制造假绿 —— 本轮审计里
        正是这类「断言找不到输入却返回 PASS」的写法最危险。）
    """
    sendable = set(policy.get("sendable_doc_types") or [])
    levels = {k: bool((v or {}).get("externally_sendable"))
              for k, v in (policy.get("levels") or {}).items()}
    manifests = sorted(out.rglob("组包manifest.tsv"))
    if not manifests and data_dir is not None:
        manifests = sorted(Path(data_dir).rglob("组包manifest.tsv"))
    if not manifests:
        return {
            "delivered_rows": 0, "blocked_materials": 0, "violations": 0,
            "violation_detail": [], "status": "FAIL",
            "reason": "NO_DELIVERY_MANIFEST：找不到交付清单 ⇒ **没验过** ⇒ 不报 PASS",
            "policy_sendable_doc_types": sorted(sendable),
            "note": "★ fail-closed：找不到清单＝无法证明披露闸生效。",
        }
    delivered_rows: list[dict[str, str]] = []
    if manifests:
        import csv
        with manifests[-1].open(encoding="utf-8") as fh:
            delivered_rows = [dict(r) for r in csv.DictReader(fh, delimiter="\t")]
    violations: list[dict[str, Any]] = []
    for r in delivered_rows:
        lvl = str(r.get("披露_敏感等级") or "").strip().upper()
        if lvl and not levels.get(lvl, False):
            violations.append({"file": r.get("原始材料路径"), "level": lvl,
                               "reason": "已交付材料的敏感等级不可外发"})
    blocked_files = sorted(Path(data_dir or out).rglob("被拦截清单.json")) \
        or sorted(out.rglob("被拦截清单.json"))
    blocked_count = 0
    if blocked_files:
        try:
            data = json.loads(blocked_files[-1].read_text("utf-8"))
            if isinstance(data, list):
                blocked_count = len(data)
            elif isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, list):
                        blocked_count += len(v)
        except Exception:  # noqa: BLE001
            blocked_count = 0
    return {
        "delivered_rows": len(delivered_rows),
        "delivered_files": len({str(r.get("file_id") or "") for r in delivered_rows}),
        "manifest_path": str(manifests[-1]) if manifests else "",
        "blocked_materials": blocked_count,
        "violations": len(violations),
        "violation_detail": violations[:20],
        "status": "PASS" if not violations else "FAIL",
        "policy_sendable_doc_types": sorted(sendable),
        "note": ("★ 受限材料若出现在交付清单 ⇒ 安全闸失效 ⇒ 断言 FAIL；"
                 "「被拦了多少件」如实记账（拦截不是失败，是设计）。"),
    }


def build_gold(exam: str, contract: dict[str, Any], meta: list[dict[str, Any]],
               expectations: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """由**库侧权威契约** ＋ **声明式期望** 生成标准答案包清单。

    ★ 为什么不在夹具里手写 ``obligation_id``：
      库内主键是 ``uuid4``（**每次建库都变**）⇒ 手写 ID 的标准答案**换快照即失效**，
      且是**静默**失效（逐题全落空、分数恒 0）。
      ⇒ 这里从契约导出 ``obligation_id``，并**同时**写内容派生的稳定键 ``obligation_key``
        ⇒ 阅卷时用稳定键绑回本库主键（见 ``exam_service.bind_gold_to_library``）。

    ★ 期望 → 义务的落位规则（可解释、可复核）：
      ① 按**题号**（canonical）找到该题的**全部**库侧义务；
      ② 一题多义务（如「审计报告和营业执照」）⇒ 按**材料类型**把期望材料分给各条义务；
      ③ 义务**判不出类型** ⇒ 期望材料全给该条（并记 ``EXPECTED_ALL``）。
    """
    by_path = {str(m.get("relative_path") or ""): m for m in meta}
    q_expect = expectations.get("questions") or {}
    items: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    for qid, exp in q_expect.items():
        paths = [str(p) for p in (exp.get("expect_paths") or [])]
        exp_files_all = []
        for p in paths:
            m = by_path.get(p)
            if not m:
                notes.append({"question": qid, "path": p,
                              "note": "EXPECTED_PATH_NOT_IN_LIBRARY"})
                continue
            exp_files_all.append({
                "sha256": str(m.get("sha256") or ""),
                "relative_path": str(m.get("relative_path") or ""),
                "entity": str(m.get("entity") or ""),
                "period": str(m.get("period") or ""),
                "doc_type": str(m.get("doc_type") or ""),
            })
        obl_rows = [o for o in (contract.get("obligations") or [])
                    if str(o.get("question_id") or o.get("item_no") or "") == str(qid)
                    or str(o.get("item_no") or "") == str(qid)]
        if not obl_rows:
            notes.append({"question": qid, "note": "NO_OBLIGATION_IN_CONTRACT"})
            continue
        for o in obl_rows:
            dt = str(o.get("doc_type") or "")
            if len(obl_rows) > 1 and dt:
                picked = [f for f in exp_files_all if f.get("doc_type") == dt]
                if not picked:
                    picked = exp_files_all
                    notes.append({"question": qid, "obligation_id": o.get("obligation_id"),
                                  "note": "DOC_TYPE_NO_MATCH_USED_ALL"})
            else:
                picked = exp_files_all
            items.append({
                "obligation_id": str(o.get("obligation_id") or ""),
                # ★ 内容派生的稳定键（跨机/跨快照一致）⇒ 阅卷时按它绑定本库主键
                "obligation_key": str(o.get("obligation_key") or ""),
                "item_no": str(o.get("item_no") or qid),
                "expected_verdict": str(exp.get("verdict") or "MATCH"),
                "expected_files": [{k: v for k, v in f.items() if k != "doc_type"}
                                   for f in picked],
                "confirmed_by": str((expectations.get("meta") or {}).get("confirmed_by") or ""),
                "confirmed_at": str((expectations.get("meta") or {}).get("confirmed_at") or ""),
            })
    manifest = {
        "schema_version": "dd_v1_gold_manifest.v1",
        "gold_pack_id": f"GOLD-SYN-{exam}",
        "exam_id": _spec(exam).get("exam_id") or f"DDV1-SYN-{exam}",
        "checklist": {"checklist_id": f"CL-SYN-{exam}", "sha256": "",
                      "item_count": len(q_expect)},
        "library": {"library_id": _spec(exam).get("library_id") or "",
                    "fingerprint": "", "material_count": 0},
        "confirmed_by": str((expectations.get("meta") or {}).get("confirmed_by") or "合成测试（非人工批准）"),
        "confirmed_at": str((expectations.get("meta") or {}).get("confirmed_at") or ""),
        "items": items,
    }
    return manifest, {"notes": notes, "items": len(items),
                      "questions": len(q_expect)}


def run_exam(exam: str, *, agent: str = "none", agent_result: str = "",
             allow_local_dsh: bool = False, reset: bool = True,
             out_dir: str = "", keep_gold: bool = False,
             run_mode: str = "RULE_ONLY",
             codex_persist_session: bool = False,
             agent_timeout: float | None = None,
             agent_max_calls: int = 2) -> dict[str, Any]:
    """跑一场完整考试 ⇒ 返回运行清单（含成绩与失败项）。

    ★ ``run_mode``：**请求的运行模式**（RULE_ONLY / AGENT_REQUIRED / AUTO）
      —— 施工令 V3.0 §6。**请求的模式**与**实际执行路径**在运行清单里**分列**，
      两者不同 ⇒ 就是「降级」，如实记录，**不冒充 AI 成绩**。
    """
    _req_mode = rm.normalize_mode(run_mode)
    # ★ AGENT_REQUIRED ⇒ **必须**有 Agent；没给 Agent 直接拒绝（fail-loud，不静默跑规则）
    if _req_mode == rm.MODE_AGENT_REQUIRED and str(agent or "none") == "none":
        raise SystemExit(
            "❌ --run-mode AGENT_REQUIRED 要求真实 Agent，但没给 --agent。\n"
            "   可选：dsh（真实 DeepSeek Harness）｜codex｜pi\n"
            "   ⇒ **不允许**在 AGENT_REQUIRED 下静默跑成规则考试。")
    spec = _spec(exam)
    plane = _prepare_plane(exam, reset=reset)
    data_dir = plane / "data"
    _bind_data_plane(data_dir)
    # ★ 考场披露口径（**只对合成材料生效**；生产策略一字未改）
    policy_path = write_exam_policy(exam, plane)
    policy = json.loads(policy_path.read_text("utf-8"))
    # ★ 重新绑定：服务模块在 import 时读环境变量 ⇒ 必须在 import 之前设好
    for mod in [m for m in list(sys.modules) if m.startswith("cangjie_fos")
                or m.startswith("dd_team_channel") or m.startswith("dd_v1_local_run")]:
        del sys.modules[mod]
    sys.path.insert(0, str(BACKEND / "src"))
    sys.path.insert(0, str(REPO / "tools"))

    from cangjie_fos.services import (dd_v1_bridge_service as br,
                                      dd_v1_card_service as cs,
                                      dd_v1_exam_service as ex,
                                      dd_v1_gold_service as gold_svc,
                                      dd_v1_manifest_service as mf,
                                      dd_v1_parser_service as ps,
                                      dd_v1_requirement_service as rq)
    import dd_team_channel as tc

    lib_id = str(spec.get("library_id") or "")
    materials = (EXAMS_DIR / exam / str(spec.get("materials_dir") or "materials")).resolve()
    checklist = EXAMS_DIR / exam / str(spec.get("checklist_file") or "checklist.tsv")
    expectations = json.loads(
        (EXAMS_DIR / exam / str(spec.get("expectations_file") or "expectations.json")).read_text("utf-8"))

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(out_dir) if out_dir else (plane / "runs" / run_id)
    # ★★ **fail-closed：--out 不得撞数据面**（独立 Reviewer 第 2 轮 MINOR）
    #   事故机制：`--out` 若**等于数据面本身**（或它的祖先）⇒ 下面的 `shutil.rmtree(out)`
    #   会把**刚写下的考场披露策略**（exam-policy-<exam>.json）一起删掉
    #   ⇒ 回落到**生产默认策略**（最严 RESTRICTED）⇒ 全部材料被拦
    #   ⇒ **0 件交付 ⇒ 总分被强制为 0**，而且**全程不报错、退出码 0、状态仍显示 SCORED**。
    #   ⇒ 这是一个「静默毁面」陷阱：**用错命令 ⇒ 静默的假分数**。
    #   ⇒ 这里**直接拒绝执行**并说明正确用法（fail-loud）。
    try:
        _out_r = out.resolve()
        _plane_r = plane.resolve()
    except OSError:
        _out_r, _plane_r = out, plane
    if _out_r == _plane_r or _plane_r.is_relative_to(_out_r):
        raise SystemExit(
            "❌ --out 与考试数据面冲突，已拒绝执行。\n"
            f"   数据面（本场）: {_plane_r}\n"
            f"   --out 解析为  : {_out_r}\n"
            "   原因：--out 指向数据面本身或它的祖先时，运行前的清理会删掉"
            "**考场披露策略文件**，导致披露闸回落到生产默认（最严）策略 ⇒\n"
            "        全部材料被拦 ⇒ 0 件交付 ⇒ 总分被强制为 0，**且不报错**。\n"
            "   正确用法：--out 指向**数据面之外**的目录；"
            "或干脆不传 --out（默认写到 <数据面>/runs/<run_id>）。"
        )
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    # ── 步骤 1：建库（登记 → 扫描 → 抽取 → 认知卡） ─────────────────────────
    mf.register_library(lib_id, str(materials), authorized_by="自动考试（合成材料）",
                        display_name=str(spec.get("title") or exam))
    scan = mf.build_manifest(lib_id, mode="full")
    parsed = ps.parse_pending_batch(lib_id, limit=5000)
    cards = cs.build_cards_for_library(lib_id)
    # ── 步骤 2：登记权威主体（**必须在首次摄取/组包前**） ────────────────────
    for e in (spec.get("entities") or []):
        rq.register_entity(lib_id, str(e.get("id") or ""), str(e.get("name") or ""),
                           relation=str(e.get("relation") or "other"),
                           parent_id=str(e.get("parent") or ""),
                           is_group_root=bool(e.get("group_root")),
                           source_ref=str(e.get("source") or "合成登记（自动考试专用）"))
    # ── 步骤 3：走**真实入口**跑完整链路（清单 → 匹配 → 组包 → 桥接） ───────
    run_args = ["run", "--library", lib_id, "--root", str(materials),
                "--checklist", str(checklist), "--by", "自动考试（合成授权人）",
                "--name", str(spec.get("title") or exam),
                "--institution", str(spec.get("institution") or ""),
                "--anchor-year", str(spec.get("anchor_year") or ""),
                "--package", "--approved-by", "自动考试（合成批准人）",
                "--out", str(out / "run")]
    if agent and agent != "none":
        run_args += ["--agent", agent]
    # ★ P5：分 Agent 超时预算/重试预算（不给 ⇒ 按框架用实测预算）
    if agent and agent != "none":
        run_args += ["--agent-max-calls", str(int(agent_max_calls or 2))]
        if agent_timeout is not None:
            run_args += ["--agent-timeout", str(float(agent_timeout))]
    if codex_persist_session:
        run_args += ["--codex-persist-session"]
    if agent_result:
        run_args += ["--agent-result", str(agent_result)]
    if agent == "dsh" and allow_local_dsh:
        run_args += ["--allow-real-material"]
    rc_run = tc.main(run_args)
    # ── 步骤 4：库侧权威契约（**唯一权威拆解**） ────────────────────────────
    contract = rq.export_obligation_contract(lib_id)
    meta, _stats = br.build_meta(lib_id)
    # ── 步骤 5：生成标准答案（★ Gold 在**仓库之外** ⇒ 与考生面物理分离） ────
    gold_manifest, gold_build = build_gold(exam, contract, meta, expectations)
    gold_dir = plane / "gold"
    gold_dir.mkdir(parents=True, exist_ok=True)
    gold_path = gold_dir / f"gold-{exam}.json"
    gold_path.write_text(json.dumps(gold_manifest, ensure_ascii=False, indent=2), "utf-8")
    # ── 步骤 6：机器答卷（答卷侧**不读** Gold） ────────────────────────────
    run_js = sorted((out / "run").glob("尽调结果-*.json"))
    answer_dir = out / "answer"
    answer_dir.mkdir(parents=True, exist_ok=True)
    answer_args = ["answer", "--out", str(answer_dir),
                   "--exam-id", str(spec.get("exam_id") or ""),
                   "--run-mode", _req_mode]
    if run_js:
        answer_args += ["--bridge-json", str(run_js[-1])]
    manifest_tsv = sorted((out / "run").rglob("组包manifest.tsv"))
    if manifest_tsv:
        answer_args += ["--delivered", str(manifest_tsv[-1])]
    rc_answer = tc.main(answer_args)
    sheets = sorted(answer_dir.glob("机器答卷-*.json"))
    sheet_path = sheets[-1] if sheets else None
    # ── 步骤 7：隔离阅卷（★ 逐题明细 + 0—100 成绩单） ──────────────────────
    grade_dir = out / "grade"
    grade_dir.mkdir(parents=True, exist_ok=True)
    rc_grade = 2
    card: dict[str, Any] = {}
    if sheet_path:
        rc_grade = tc.main(["grade", "--answer", str(sheet_path), "--gold", str(gold_path),
                            "--library", lib_id, "--out", str(grade_dir)])
        cards_ = sorted(grade_dir.glob("成绩单-*.json"))
        if cards_:
            card = json.loads(cards_[0].read_text("utf-8"))

    _rp = dict(card.get("run_provenance") or {})
    # ★ MINOR-1：降级原因**也**在答卷里（examinee.degrade_reason）⇒ 一并取，避免只查一处
    _degrade_reason_from_sheet = ""
    if sheet_path:
        try:
            _sh = json.loads(Path(sheet_path).read_text("utf-8"))
            _degrade_reason_from_sheet = str((_sh.get("examinee") or {}).get("degrade_reason") or "")
        except Exception:  # noqa: BLE001 —— 取不到就留空，**不猜**
            _degrade_reason_from_sheet = ""
    model_participation = {
        "agent_spec": agent,
        "agent_result_file": agent_result or "",
        "examinee_mode": str(card.get("examinee_mode") or "UNKNOWN"),
        # ★ **回执口径**的参与标记（成绩单的 17 项账里那一项）⇒
        #   成绩单**没有** `examinee` 块（那是答卷的），读错字段 ⇒ 永远 False（⇒ 假绿）。
        "participated": bool(_rp.get("model_participated")),
        # ★★ 施工令 V3.0 §6：请求的模式 ＋ 实际执行路径 ＋ 模型身份（**分列**）
        "requested_mode": _req_mode,
        "execution_path": str((card.get("run_provenance") or {}).get("execution_path") or ""),
        "actual_model": str((card.get("run_provenance") or {}).get("actual_model") or "UNKNOWN"),
        "model_identity_verified": bool((card.get("run_provenance") or {}).get("model_identity_verified")),
        "model_identity": dict((card.get("run_provenance") or {}).get("model_identity") or {}),
        "examinee_framework": str((card.get("run_provenance") or {}).get("examinee_framework") or ""),
        "examinee_provider": str((card.get("run_provenance") or {}).get("examinee_provider") or ""),
        # ★★ MINOR-1 修复：施工令 §6 要求「**降级原因**」必须记录 ——
        #   此前只在**答卷**里有，运行清单（门禁读的那份）**恒为空** ⇒ 复核者只看清单看不出为什么降级。
        "degrade_reason": str((card.get("run_provenance") or {}).get("degrade_reason")
                              or _degrade_reason_from_sheet or ""),
        # ★ 成绩两列（规则基线分 vs AI 系统分）—— 模型缺席时 AI 列 NOT_SCORED
        "score_split": dict(card.get("score_split") or {}),
    }
    # ★★ 施工令 V3.0 §6：**考试状态**由「实际执行路径」决定（不是只看阅卷状态）
    _exec_path = str(model_participation.get("execution_path") or "")
    _exam_status = rm.exam_status_for(_exec_path, str(card.get("status") or "NO_SCORECARD"))

    manifest = {
        "schema_version": "dd_v1_exam_run_manifest.v1",
        "run_id": run_id,
        "exam": exam,
        "exam_id": str(spec.get("exam_id") or ""),
        "title": str(spec.get("title") or ""),
        "started_at": _now(),
        "finished_at": _now(),
        "elapsed_s": round(time.time() - t0, 2),
        "git_sha": _git_sha(),
        "git_dirty": _git_dirty(),
        "environment": {
            "platform": sys.platform,
            "python": sys.version.split()[0],
            "data_plane": str(data_dir),
            "out_dir": str(out),
            "note": "★ 数据面在仓库之外 ⇒ 合成考试数据不污染真实业务库",
        },
        "model": model_participation,
        "test_data_version": {
            "fixture": str((EXAMS_DIR / exam).relative_to(REPO)),
            "materials": len(meta),
            "questions": len(expectations.get("questions") or {}),
            "contract_obligations": (contract.get("counts") or {}).get("obligations"),
            "contract_questions": (contract.get("counts") or {}).get("questions"),
        },
        "gold_version": {
            "path": str(gold_path),
            "items": gold_build["items"],
            "fingerprint": gold_svc.gold_fingerprint(gold_manifest),
        },
        "results": {
            "rc_run": rc_run, "rc_answer": rc_answer, "rc_grade": rc_grade,
            # ★★ 施工令 V3.0 §6：AGENT_REQUIRED 且模型没参与 ⇒ **考试状态 FAIL**
            #   （**不是**降级成规则考试，也不是把规则分当 AI 分）
            "status": _exam_status,
            "scorecard_status": str(card.get("status") or "NO_SCORECARD"),
            "scores": card.get("scores"),
            "score_split": dict(card.get("score_split") or {}),
            "run_provenance": dict(card.get("run_provenance") or {}),
            "safety_gate": card.get("safety_gate"),
            "counts": card.get("counts"),
            "exam_coverage": card.get("exam_coverage"),
            "gold_library_binding": card.get("gold_library_binding"),
            "gold_scorable": card.get("gold_scorable"),
            "gold_gaps": card.get("gold_gaps"),
            "blocked_by": card.get("blocked_by") or [],
        },
        "failures": _collect_failures(card),
        "disclosure": disclosure_assertions(out, policy, data_dir=data_dir),
        "artifacts": {
            "answer_sheet": str(sheet_path or ""),
            "scorecard_dir": str(grade_dir),
            "run_report_dir": str(out / "run"),
            "gold_manifest": str(gold_path),
        },
    }
    (out / "运行清单.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")
    if not keep_gold:
        pass  # ★ Gold 留在仓库外的数据面（隔离原则），不复制进仓
    return manifest


def _collect_failures(card: dict[str, Any]) -> list[dict[str, Any]]:
    """把成绩单里的**逐题未达成项**汇总成失败清单（供失败驱动修复）。"""
    fails: list[dict[str, Any]] = []
    for r in (card.get("rows") or []):
        if str(r.get("outcome") or "") in ("CORRECT", "EXPECTED_NONE"):
            continue
        fails.append({
            "obligation_id": r.get("obligation_id"),
            "item_no": r.get("item_no"),
            "outcome": r.get("outcome"),
            "missed": r.get("missed"),
            "extra": r.get("extra"),
            "hit": r.get("hit"),
            "agent_verdict": r.get("agent_verdict"),
            "expected_verdict": r.get("expected_verdict"),
            "resolution_state": r.get("resolution_state"),
            "cluster_ids": r.get("cluster_ids"),
        })
    return fails


# ─────────────────────────────────────────────────────────────────────────────
# 3. 交付门禁（WP5）
# ─────────────────────────────────────────────────────────────────────────────

def load_gate_spec() -> dict[str, Any]:
    return json.loads(GATE_SPEC.read_text("utf-8"))


def evaluate_gate(runs_dir: str, gate_spec: dict[str, Any] | None = None) -> dict[str, Any]:
    """按**冻结阈值**判定 G1—G7。任一关键门槛失败 ⇒ 不得宣布开发完成。"""
    spec = gate_spec or load_gate_spec()
    gates = spec.get("gates") or {}
    runs_dir = Path(runs_dir)
    runs = sorted(runs_dir.glob("*/运行清单.json"))
    if not runs:
        return {"status": "BLOCKED", "reason": "NO_RUN_MANIFEST",
                "gates": {k: {"status": "UNKNOWN", "reason": "NO_RUN"} for k in gates}}
    latest: dict[str, dict[str, Any]] = {}
    all_manifests: list[dict[str, Any]] = []
    runs_by_exam: dict[str, list[dict[str, Any]]] = {}
    for p in runs:
        m = json.loads(p.read_text("utf-8"))
        all_manifests.append(m)
        exam_key = str(m.get("exam") or p.parent.name)
        runs_by_exam.setdefault(exam_key, []).append(m)
    # ═══════════════════════════════════════════════════════════════════════
    # ★ **绑定确定性**（amendment A4）：同一场考试**可能有多次运行**
    #   （规则基线 ＋ 若干次真实模型）。原来按**路径排序**取最后一个
    #   ⇒ 换一个目录名就可能换掉被判定的那一次 ⇒ **判定结果与证据目录名耦合**。
    #   ⇒ 现在：**按考试绑定的门槛（G2/G4/G5 等）一律绑定到该考试的「规则基线」运行**
    #     （``requested_mode == RULE_ONLY``；同键多条时取 ``run_id`` 字典序最大者，
    #      仍并列则取路径序最大者 ⇒ 完全确定性）。
    #   ★ **G3 / G8 仍然看** ``all_manifests``（**全部**运行，含真实模型运行）
    #     ⇒ **没有任何门槛被放松**；只是「同一考试绑定哪一次」不再随机。
    # ═══════════════════════════════════════════════════════════════════════
    for exam_key, ms in runs_by_exam.items():
        base = [m for m in ms
                if str((m.get("model") or {}).get("requested_mode") or "RULE_ONLY") == "RULE_ONLY"]
        pool = base or ms
        latest[exam_key] = sorted(pool, key=lambda m: (str(m.get("run_id") or ""),
                                                       str(m.get("exam") or "")))[-1]
    out: dict[str, Any] = {}
    for gid, g in gates.items():
        exam = str(g.get("exam") or "")
        m = latest.get(exam)
        if m is None and str(g.get("check") or "") not in (
                "pytest_report", "reviewer_report", "artifact_exists",
                "real_model_participated", "model_participation_mode"):
            out[gid] = {"status": "FAIL", "reason": f"NO_RUN_FOR_EXAM_{exam}",
                        "gate": gid, "title": g.get("title")}
            continue
        status, reason = _gate_check(g, m, runs_dir=runs_dir, manifests=all_manifests)
        out[gid] = {"status": status, "reason": reason, "gate": gid,
                    "title": g.get("title"), "exam": exam or None,
                    "run_id": (m or {}).get("run_id"), "git_sha": (m or {}).get("git_sha")}
    key_fail = [g for gid, g in out.items()
                if g.get("status") == "FAIL" and gid in (spec.get("key_gates") or [])]
    # ★ **observations：把实际读数原样摊开**。
    #   门禁 PASS 只说明「**门槛**过了」，**不等于**各项指标都完美。
    #   ⇒ 这里把理解率/交付件数/置信度标注等原样列出，避免 PASS 掩盖读数。
    observations: dict[str, Any] = {}
    for exam, m in latest.items():
        res = m.get("results") or {}
        sc = res.get("scores") or {}
        cov = res.get("exam_coverage") or {}
        sg = res.get("safety_gate") or {}
        cnt = res.get("counts") or {}
        observations[exam] = {
            "run_id": m.get("run_id"),
            "status": res.get("status"),
            "total_score": sc.get("total_score"),
            "question_understanding_coverage": sc.get("question_understanding_coverage"),
            "question_answer_coverage": sc.get("question_answer_coverage"),
            "material_recall": sc.get("material_recall"),
            "selection_precision": sc.get("selection_precision"),
            "complete_delivery_ratio": sc.get("complete_delivery_ratio"),
            "miss_rate": sc.get("miss_rate"),
            "wrong_rate": sc.get("wrong_rate"),
            "questions_processed": cov.get("questions_processed"),
            "questions_total": cov.get("questions_total"),
            "verifiable_coverage": cov.get("verifiable_coverage"),
            "delivered_files": cnt.get("delivered_files"),
            "delivered_files_attributed": cnt.get("delivered_files_attributed"),
            "safety_status": sg.get("status"),
            "safety_violations": sg.get("violations"),
            "model_participated": bool((m.get("model") or {}).get("participated")),
            "agent_spec": (m.get("model") or {}).get("agent_spec"),
            "examinee_mode": (m.get("model") or {}).get("examinee_mode"),
        }
    return {
        "schema_version": "dd_v1_gate_report.v1",
        "evaluated_at": _now(),
        "git_sha": _git_sha(),
        "git_dirty": _git_dirty(),
        "gate_spec_id": str(spec.get("spec_id") or ""),
        "gate_spec_frozen_at": str(spec.get("frozen_at") or ""),
        "gate_spec_path": str(GATE_SPEC),
        "gate_spec_amendments": spec.get("amendments") or [],
        "gate_spec_chronology": spec.get("chronology") or {},
        "gates": out,
        "observations": observations,
        # ★★ **全部运行清单**（amendment A4）：同一场考试可能有多次运行
        #   （规则基线 ＋ 真实模型）⇒ 这里**如实列出每一次**，
        #   避免「observations 只显示被绑定的那一次」看起来像只有一次。
        "all_runs": [
            {
                "exam": str(m.get("exam") or ""),
                "run_id": str(m.get("run_id") or ""),
                "git_sha": str(m.get("git_sha") or ""),
                "requested_mode": str((m.get("model") or {}).get("requested_mode") or ""),
                "execution_path": str((m.get("model") or {}).get("execution_path") or ""),
                "agent_spec": str((m.get("model") or {}).get("agent_spec") or ""),
                "participated": bool((m.get("model") or {}).get("participated")),
                "model_identity_verified": bool((m.get("model") or {}).get("model_identity_verified")),
                "actual_model": str((m.get("model") or {}).get("actual_model") or ""),
                "total_score": ((m.get("results") or {}).get("scores") or {}).get("total_score"),
                "status": (m.get("results") or {}).get("status"),
                "score_name": str(((m.get("model") or {}).get("score_split") or {}).get("score_name") or ""),
            }
            for m in sorted(all_manifests, key=lambda x: (str(x.get("exam") or ""),
                                                          str(x.get("run_id") or "")))
        ],
        "status": "PASS" if not key_fail else "FAIL",
        "failed_key_gates": [g["gate"] for g in key_fail],
        "note": ("★ 阈值来自**考试前冻结**的门禁文件；"
                 "结果不得反过来改阈值（改阈值必须换版本并留差异说明）。"
                 "★ observations 里的**实际读数**才是真相：门禁 PASS ≠ 指标完美"
                 "（例：考试A 理解率 0.667 源于材料类型词表覆盖缺口，"
                 "属**已知能力边界**，未掩盖、已留证）。"),
    }


def _gate_check(g: dict[str, Any], m: dict[str, Any] | None, *,
                runs_dir: Path | None = None,
                manifests: list[dict[str, Any]] | None = None) -> tuple[str, str]:
    """单个门槛的判定（口径写在冻结文件里 ⇒ 代码不藏阈值）。"""
    kind = str(g.get("check") or "")
    res = (m or {}).get("results") or {}
    if kind == "composite":
        parts = []
        for sub in (g.get("checks") or []):
            st, rs = _gate_check(sub, m, runs_dir=runs_dir, manifests=manifests)
            parts.append(f"{sub.get('check')}={st}({rs})")
            if st != "PASS":
                return "FAIL", "; ".join(parts)
        return "PASS", "; ".join(parts)
    if kind == "pytest_report":
        p = (runs_dir or Path(".")) / str(g.get("file") or "g1_pytest.json")
        if not p.is_file():
            return "FAIL", f"NO_PYTEST_REPORT:{p.name}"
        try:
            rep = json.loads(p.read_text("utf-8"))
        except Exception as exc:  # noqa: BLE001
            return "FAIL", f"PYTEST_REPORT_UNREADABLE:{exc}"
        failed = int(rep.get("failed") or 0)
        passed = int(rep.get("passed") or 0)
        total = int(rep.get("total") or 0)
        # ★★ **fail-closed ①**：报告自己说「计数没拿到」⇒ FAIL（不许静默 0 通过）
        #   ★ **键缺失也判 FAIL**（独立 Reviewer 实测：旧实现用 `is False`，
        #     `counting_ok` 键**缺失**时 get 返回 None ≠ False ⇒ 绕过这道闸 ⇒ 判 PASS）。
        #     ⇒ 改成 `is not True`：**只有显式 true 才放行**，缺失/None/false 一律 FAIL。
        if rep.get("counting_ok") is not True:
            return "FAIL", (f"COUNTING_NOT_OK:{rep.get('counting_parse_error') or 'see report'}"
                            f" (counting_ok={rep.get('counting_ok')!r})")
        # ★★ **fail-closed ②**：一条测试都没跑到 ⇒ FAIL（防止「空跑＝全绿」）
        if total <= 0:
            return "FAIL", f"pytest total=0 (未收集到任何测试，exit={rep.get('exit_code')})"
        if int(rep.get("exit_code") or 0) != 0:
            return "FAIL", (f"pytest exit_code={rep.get('exit_code')} "
                            f"passed={passed} failed={failed} total={total}")
        if g.get("require_failed_zero") and failed > 0:
            return "FAIL", f"pytest failed={failed} passed={passed}"
        return "PASS", (f"pytest passed={passed} failed={failed} "
                        f"skipped={rep.get('skipped')} total={total}")
    if kind == "reviewer_report":
        p = (runs_dir or Path(".")) / str(g.get("file") or "g6_reviewer.json")
        if not p.is_file():
            return "FAIL", f"NO_REVIEWER_REPORT:{p.name}"
        try:
            rep = json.loads(p.read_text("utf-8"))
        except Exception as exc:  # noqa: BLE001
            return "FAIL", f"REVIEWER_REPORT_UNREADABLE:{exc}"
        st = str(rep.get("verdict") or "").upper()
        if st not in ("PASS", "CONDITIONAL"):
            return "FAIL", f"reviewer verdict={st or 'MISSING'}"
        return "PASS", f"reviewer verdict={st}"
    if kind == "artifact_exists":
        raw = str(g.get("path") or "handoff")
        # ★ **两处解析**：① 相对 runs_dir（本地证据目录里的临时产物）
        #   ② 相对**仓库根**（正式交接包要进版本控制，不能只躺在 .audit 里）
        #   ⇒ 交接包既能进仓、又能被门禁认到。
        cands = [Path(raw)]
        if not Path(raw).is_absolute():
            cands.append((runs_dir or Path(".")) / raw)
            cands.append(REPO / raw)
        hit = None
        for c in cands:
            try:
                if c.exists() and (not c.is_dir() or any(c.iterdir())):
                    hit = c
                    break
            except OSError:
                continue
        if hit is None:
            return "FAIL", f"NO_ARTIFACT:{raw} (checked {len(cands)} paths)"
        return "PASS", f"artifact={hit.name} path={hit}"
    if kind == "real_model_participated":
        hits = []
        others = []
        for mm in (manifests or []):
            mp = mm.get("model") or {}
            spec = str(mp.get("agent_spec") or "")
            if spec in ("dsh", "deepseek", "deepseek-harness") and bool(mp.get("participated")):
                hits.append(mm.get("run_id"))
            # ★ MINOR-4 修复：G3 的**判定口径一字未改**（仍以 dsh 为准），
            #   但 reason **如实补上**本批其它真实模型考生
            #   （否则读这一行会以为「只跑了一个模型」）。
            elif str(mp.get("execution_path") or "") == rm.EXEC_PATH_REAL_MODEL:
                others.append(f"{spec or '?'}:{mm.get('run_id')}")
        reason = f"real_model_runs={hits}"
        if others:
            reason += f" | 另有真实模型考生 {others}（见 all_runs / G8）"
        return ("PASS", reason) if hits else \
            ("FAIL", "NO_REAL_MODEL_RUN_WITH_PARTICIPATION"
             + (f"（但本批另有真实模型考生 {others}）" if others else ""))
    if kind == "model_participation_mode":
        # ═══════════════════════════════════════════════════════════════════
        # ★★ **G8：真实模型参与门禁（按运行模式判定）**（施工令 V3.0 §7.2）
        #   ★ **读真实考试产物**（运行清单里的 model 块），**不**依赖人工填写的说明字段。
        #   ★ 三种模式**分别**判（这是本门禁与 G3 的根本区别）：
        #     · AGENT_REQUIRED ⇒ 必须 ``execution_path == REAL_MODEL``
        #       （真模型参与 **且** 身份核实过）⇒ 否则 **FAIL**
        #       （模型参与了但身份核实不出来 ⇒ ``MODEL_ID_UNKNOWN`` ⇒ 同样 FAIL）
        #     · RULE_ONLY      ⇒ 模型没参与是**预期行为** ⇒ **不**因此判 FAIL
        #     · AUTO           ⇒ **按实际执行路径分类**：
        #         REAL_MODEL ⇒ 计入；DEGRADED ⇒ 如实记为降级（**不**算 AI 成绩，
        #         但**不**因此判 FAIL —— 降级本身是 AUTO 的合法行为）
        #   ★ 另外要求：**存在**至少一场真实模型参与的考试
        #     （否则「整批证据里一条真模型都没跑」⇒ 整门禁 FAIL）。
        # ═══════════════════════════════════════════════════════════════════
        all_m = list(manifests or [])
        if not all_m:
            return "FAIL", "NO_EXAM_MANIFEST_TO_JUDGE"
        real_runs: list[str] = []
        required_bad: list[str] = []
        degraded: list[str] = []
        rule_only: list[str] = []
        mock_runs: list[str] = []
        identity_unknown: list[str] = []
        for mm in all_m:
            mp = mm.get("model") or {}
            exam = str(mm.get("exam") or "")
            rid = str(mm.get("run_id") or "")
            req = str(mp.get("requested_mode") or "RULE_ONLY")
            path = str(mp.get("execution_path") or "")
            ident_ok = bool(mp.get("model_identity_verified"))
            if path == rm.EXEC_PATH_REAL_MODEL:
                real_runs.append(f"{exam}:{rid}")
            elif path == rm.EXEC_PATH_MODEL_ID_UNKNOWN:
                identity_unknown.append(f"{exam}:{rid}")
            elif path == rm.EXEC_PATH_MOCK_MODEL:
                mock_runs.append(f"{exam}:{rid}")
            elif path == rm.EXEC_PATH_DEGRADED:
                degraded.append(f"{exam}:{rid}")
            else:
                rule_only.append(f"{exam}:{rid}")
            if req == rm.MODE_AGENT_REQUIRED and path != rm.EXEC_PATH_REAL_MODEL:
                required_bad.append(f"{exam}:{rid}(req={req},path={path or 'UNKNOWN'})")
        parts = [f"real_model={len(real_runs)}", f"rule_only={len(rule_only)}",
                 f"degraded={len(degraded)}", f"mock={len(mock_runs)}",
                 f"identity_unknown={len(identity_unknown)}"]
        if required_bad:
            return "FAIL", ("; ".join(parts) + f" | AGENT_REQUIRED_WITHOUT_REAL_MODEL={required_bad}")
        # ★★ NIT-1 修复（**加严**）：「真模型参与了、但**身份核实不出来**」的运行
        #   ⇒ 它**不得**通过「模型身份」门禁（施工令 §6 明写）。
        #   ⇒ 此前 AUTO 模式下这种运行只是被计数、**不拦** ⇒ 现改为 **FAIL**。
        if identity_unknown:
            return "FAIL", ("; ".join(parts) +
                            f" | MODEL_ID_UNKNOWN_NOT_ACCEPTED={identity_unknown}"
                            "（真模型参与但身份核实不出来 ⇒ 不得通过模型身份门禁）")
        if not real_runs:
            return "FAIL", ("; ".join(parts) +
                            " | NO_REAL_MODEL_RUN_AT_ALL（整批证据里一条真模型都没跑）")
        return "PASS", "; ".join(parts) + f" | real={real_runs}"
    if kind == "rc_zero":
        rc = res.get("rc_run")
        return ("PASS", f"rc_run={rc}") if rc == 0 else ("FAIL", f"rc_run={rc}")
    if kind == "status_scored":
        # ★ **语义修正（冻结文件 amendment A1）**：本检查问的是
        #   「这次考试**出了分数**吗」，不是「置信度标注是啥」。
        #   评分规范原文：「义务条数 < 30 ⇒ status = LOW_CONFIDENCE
        #   （**分数仍给**，但标注样本量不足）」⇒ LOW_CONFIDENCE 是
        #   **已评分**状态，把它判 FAIL 会产生**假 FAIL**（考试A 实际
        #   总分 96.67、安全闸 PASS、rc=0）。
        #   真正「未评分」只有 NOT_SCORABLE（HR-2/HR-3：Gold 未提供/未映射/
        #   未人工确认/检测到泄漏）⇒ 必须 FAIL。
        # ★ 同时**加严**：除状态外还要求 total_score **真的存在**
        #   （防止「状态对但没分数」这种半吊子蒙过去）。
        st = str(res.get("status") or "")
        scores = res.get("scores") or {}
        if st not in ("SCORED", "SCORED_PARTIAL", "LOW_CONFIDENCE"):
            return "FAIL", f"status={st or 'MISSING'}"
        if scores.get("total_score") is None:
            return "FAIL", f"status={st} but NO_TOTAL_SCORE"
        return "PASS", f"status={st} total_score={scores.get('total_score')}"
    if kind == "min_total_score":
        thr = float(g.get("threshold") or 0)
        scores = res.get("scores") or {}
        got = scores.get("total_score")
        if got is None:
            return "FAIL", "NO_TOTAL_SCORE"
        return ("PASS", f"total_score={got} >= {thr}") if float(got) >= thr else \
            ("FAIL", f"total_score={got} < {thr}")
    if kind == "min_understanding":
        thr = float(g.get("threshold") or 0)
        scores = res.get("scores") or {}
        got = scores.get("question_understanding_coverage")
        if got is None:
            return "FAIL", "NO_UNDERSTANDING"
        return ("PASS", f"understanding={got} >= {thr}") if float(got) >= thr else \
            ("FAIL", f"understanding={got} < {thr}")
    if kind == "safety_pass":
        sg = res.get("safety_gate") or {}
        st = str(sg.get("status") or "")
        return ("PASS", f"safety={st}") if st == "PASS" else ("FAIL", f"safety={st}")
    if kind == "no_blocked":
        blocked = res.get("blocked_by") or []
        return ("PASS", "not blocked") if not blocked else ("FAIL", f"blocked_by={blocked}")
    if kind == "coverage_full":
        cov = res.get("exam_coverage") or {}
        thr = float(g.get("threshold") or 0)
        got = cov.get("verifiable_coverage")
        if got is None:
            return "FAIL", "NO_COVERAGE"
        return ("PASS", f"coverage={got} >= {thr}") if float(got) >= thr else \
            ("FAIL", f"coverage={got} < {thr}")
    if kind == "questions_processed":
        cov = res.get("exam_coverage") or {}
        thr = int(g.get("threshold") or 0)
        got = int(cov.get("questions_processed") or 0)
        return ("PASS", f"processed={got} >= {thr}") if got >= thr else \
            ("FAIL", f"processed={got} < {thr}")
    if kind == "model_participated":
        mp = (m or {}).get("model") or {}
        ok = bool(mp.get("participated")) and str(mp.get("examinee_mode") or "") != "RULE_ONLY"
        return ("PASS", f"participated={mp.get('participated')} mode={mp.get('examinee_mode')}") \
            if ok else ("FAIL", f"participated={mp.get('participated')} mode={mp.get('examinee_mode')}")
    if kind == "no_failures":
        fails = (m or {}).get("failures") or []
        return ("PASS", "no failures") if not fails else ("FAIL", f"{len(fails)} failures")
    return "UNKNOWN", f"UNKNOWN_CHECK:{kind}"


# ─────────────────────────────────────────────────────────────────────────────
# 4. 覆盖率报告（目标 A）
# ─────────────────────────────────────────────────────────────────────────────

def _junit_case_index(xml_path: Path) -> dict[str, str]:
    """从 JUnit XML 重建「pytest node id → 状态」索引。

    ★ pytest 的 junitxml 里 ``classname`` 形如 ``tests.test_mod`` 或
      ``tests.test_mod.TestClass``，``name`` 是函数名（参数化时带 ``[param]``）。
    ★ 重建出的 node id 与命令行 ``pytest --collect-only -q`` 的形式一致，
      于是**验收项清单里的 test_refs 可以直接机检**（不是人工抄的证据）。
    """
    import xml.etree.ElementTree as ET
    idx: dict[str, str] = {}
    if not xml_path.is_file():
        return idx
    try:
        root = ET.parse(str(xml_path)).getroot()
    except Exception:  # noqa: BLE001
        return idx
    for tc in root.iter("testcase"):
        cn = (tc.get("classname") or "").split(".")
        name = tc.get("name") or ""
        if len(cn) < 2 or not name:
            continue
        mod = "tests/" + cn[1] + ".py"
        cls = cn[2] if len(cn) > 2 else ""
        node = f"{mod}::{cls}::{name}" if cls else f"{mod}::{name}"
        if list(tc.findall("failure")) or list(tc.findall("error")):
            idx[node] = "failed"
        elif list(tc.findall("skipped")):
            idx[node] = "skipped"
        else:
            idx[node] = "passed"
    return idx


def _match_ref(idx: dict[str, str], ref: str) -> tuple[str, str]:
    """把清单里的 test_ref 匹配到 JUnit 节点 ⇒ (状态, 实际节点)。

    ★ 匹配顺序：**完全相等** → **参数化前缀**（``node[param]``）。
      匹配不到 ⇒ ``("not_found", "")`` ⇒ 该验收项记 NOT_AUTOMATED（如实暴露）。
    """
    if ref in idx:
        return idx[ref], ref
    for node, st in idx.items():
        if node.startswith(ref + "[") or node.startswith(ref + "::"):
            return st, node
    return "not_found", ""


def _dig(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def _cmp_ok(got: Any, op: str, want: Any) -> bool:
    try:
        if op == "==":
            return abs(float(got) - float(want)) < 1e-9 if isinstance(got, (int, float)) and isinstance(want, (int, float)) else got == want
        if op == ">=":
            return float(got) >= float(want)
        if op == "<=":
            return float(got) <= float(want)
        if op == ">":
            return float(got) > float(want)
    except (TypeError, ValueError):
        return False
    return False


def acceptance_coverage(runs_dir: Path, manifests: dict[str, dict[str, Any]],
                        case_index: dict[str, str],
                        gate_report: dict[str, Any] | None = None) -> dict[str, Any]:
    """★ **机算**自动化覆盖率与通过率（不是人工填的数字）。

    - 覆盖率分子 ＝ automatable 且本轮能由机器复算出 PASS 的项数
    - 通过率分母 ＝ 本轮**实际执行**了断言的自动化项数（ref 存在且未被 skip）
    - ref 找不到 ⇒ NOT_AUTOMATED（**不当通过**）
    - ref 被 skip ⇒ BLOCKED（用例存在但本轮不可复算，**不充数**）

    证据三类：
    - ``test_refs``：pytest node id ⇒ 对 JUnit XML 的**实际执行结果**求值
    - ``exam_refs``：某场考试的指标路径 ⇒ 对运行清单求值
    - ``gate_refs``：某个门禁（G1…G7）⇒ 对门禁报告求值
    """
    spec = json.loads(ACCEPTANCE_SPEC.read_text("utf-8"))
    items = spec.get("items") or []
    gates = ((gate_report or {}).get("gates") or {})
    rows: list[dict[str, Any]] = []
    for it in items:
        aid = str(it.get("id") or "")
        title = str(it.get("title") or "")
        automatable = bool(it.get("automatable"))
        refs = list(it.get("test_refs") or [])
        erefs = list(it.get("exam_refs") or [])
        grefs = list(it.get("gate_refs") or [])
        status = "PASS"
        evidence: list[str] = []
        detail = ""
        if not automatable:
            status = "MANUAL"
            detail = str(it.get("manual_reason") or "")
        elif refs:
            seen = set()
            for ref in refs:
                st, node = _match_ref(case_index, ref)
                seen.add(st)
                evidence.append(f"{ref} [{st}]")
            if "failed" in seen:
                status = "FAIL"
            elif "not_found" in seen:
                status = "NOT_AUTOMATED"
                detail = "证据引用在 JUnit XML 里找不到（用例不存在或改名了）"
            elif "skipped" in seen:
                status = "BLOCKED"
                detail = str(it.get("blocked_by") or "用例被 skip（本轮不可复算）")
        elif erefs:
            for er in erefs:
                exam = str(er.get("exam") or "")
                m = manifests.get(exam) or {}
                got = _dig(m, str(er.get("metric") or ""))
                op = str(er.get("op") or "==")
                want = er.get("value")
                ok = got is not None and _cmp_ok(got, op, want)
                evidence.append(f"{exam}.{er.get('metric')}={got} {op} {want} → {'OK' if ok else 'BAD'}")
                if not ok:
                    status = "FAIL"
                    detail = f"{exam}.{er.get('metric')}={got} 不满足 {op} {want}"
                    break
        elif grefs:
            for gid in grefs:
                g = gates.get(str(gid)) or {}
                st = str(g.get("status") or "UNKNOWN")
                evidence.append(f"gate {gid}={st}")
                if st != "PASS":
                    status = "FAIL"
                    detail = f"门禁 {gid}={st}（{g.get('reason') or ''}）"
                    break
        else:
            status = "NOT_AUTOMATED"
            detail = "既无 test_refs 也无 exam_refs"
        rows.append({
            "id": aid, "group": it.get("group"), "title": title,
            "automatable": automatable, "status": status, "detail": detail,
            "evidence": evidence, "owner": it.get("owner"),
            "blocked_by": it.get("blocked_by"),
        })
    automatable_rows = [r for r in rows if r["automatable"]]
    manual_rows = [r for r in rows if not r["automatable"]]
    covered = [r for r in automatable_rows if r["status"] == "PASS"]
    executed = [r for r in automatable_rows if r["status"] in ("PASS", "FAIL")]
    passed = [r for r in executed if r["status"] == "PASS"]
    total_a = len(automatable_rows)
    return {
        "spec_id": spec.get("spec_id"),
        "spec_path": str(ACCEPTANCE_SPEC),
        "spec_frozen_at": spec.get("frozen_at"),
        "验收项总数": len(rows),
        "可自动化项数": total_a,
        "已自动化且可重复执行": len(covered),
        "本轮实际执行": len(executed),
        "本轮通过": len(passed),
        "自动化覆盖率": round(len(covered) / total_a, 4) if total_a else 0.0,
        "自动化测试通过率": round(len(passed) / len(executed), 4) if executed else 0.0,
        "未自动化但可自动化": [
            {"id": r["id"], "title": r["title"], "status": r["status"],
             "reason": r["detail"], "owner": r["owner"], "blocked_by": r["blocked_by"]}
            for r in automatable_rows if r["status"] != "PASS"],
        "人工不可替代": [
            {"id": r["id"], "title": r["title"], "reason": r["detail"],
             "owner": r["owner"], "blocked_by": r["blocked_by"]}
            for r in manual_rows],
        "items": rows,
    }


def coverage_report(runs_dir: str, gate_report: dict[str, Any] | None = None) -> dict[str, Any]:
    """自动化覆盖率报告（★ 保留原始分母；不得通过缩分母提高成绩）。"""
    runs = sorted(Path(runs_dir).glob("*/运行清单.json"))
    rows = []
    manifests: dict[str, dict[str, Any]] = {}
    for p in runs:
        m = json.loads(p.read_text("utf-8"))
        manifests[str(m.get("exam") or "")] = m
        res = m.get("results") or {}
        scores = res.get("scores") or {}
        cov = res.get("exam_coverage") or {}
        rows.append({
            "exam": m.get("exam"), "run_id": m.get("run_id"), "git_sha": m.get("git_sha"),
            # ★ 独立 Reviewer 第 2 轮 NIT：runs[] 也要带 dirty
            #   （否则单看这一层无法自证「这场考试跑的是不是当前代码」）
            "git_dirty": m.get("git_dirty"),
            "status": res.get("status"),
            "total_score": scores.get("total_score"),
            "understanding": scores.get("question_understanding_coverage"),
            "recall": scores.get("material_recall"),
            "precision": scores.get("selection_precision"),
            "complete_ratio": scores.get("complete_delivery_ratio"),
            "safety": (res.get("safety_gate") or {}).get("status"),
            "questions_total": cov.get("questions_total"),
            "questions_processed": cov.get("questions_processed"),
            "questions_correct": cov.get("questions_correct"),
            "failures": len(m.get("failures") or []),
        })
    rd = Path(runs_dir)
    xml = rd / "g1_pytest.xml"
    case_index = _junit_case_index(xml)
    gate = gate_report
    if gate is None:
        gp = rd / "门禁报告.json"
        if gp.is_file():
            try:
                gate = json.loads(gp.read_text("utf-8"))
            except Exception:  # noqa: BLE001
                gate = None
    acc = acceptance_coverage(rd, manifests, case_index, gate)
    return {
        "schema_version": "dd_v1_coverage_report.v1",
        "generated_at": _now(),
        # ★ 独立 Reviewer 第 2 轮 NIT：顶层也要带 sha/dirty
        #   （否则单看覆盖率报告这一份文件，无法自证「这份覆盖率是用哪个 commit 的代码算出来的」）
        "git_sha": _git_sha(),
        "git_dirty": _git_dirty(),
        "runs_dir": str(runs_dir),
        "runs": rows,
        "gate": gate or {},
        "自动化覆盖率统计": acc,
        "junit_cases_indexed": len(case_index),
        "note": ("★ 覆盖率与通过率**分列**，均由**机算**得出"
                 "（test_refs 对 JUnit XML 的实际执行结果 ＋ exam_refs 对运行清单"
                 "＋ gate_refs 对门禁报告）；ref 找不到 ⇒ NOT_AUTOMATED、"
                 "ref 被 skip ⇒ BLOCKED，两者都**不充数**。"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="DD-V1 考试台")
    sub = p.add_subparsers(dest="cmd", required=True)

    lp = sub.add_parser("list", help="列出考试")
    lp.set_defaults(func=cmd_list)

    rp = sub.add_parser("run", help="跑一场考试（隔离数据面 + 真实入口 + 自动评分）")
    rp.add_argument("--exam", required=True, choices=list(EXAM_IDS))
    rp.add_argument("--agent", default="none",
                    help="none（纯规则）｜prebaked（预置回执＝模拟模型）｜dsh（真实 DeepSeek Harness）")
    rp.add_argument("--agent-result", default="", help="预置回执 JSON 路径（--agent prebaked）")
    rp.add_argument("--allow-local-dsh", action="store_true", help="显式打开本机 dsh（真实模型）")
    rp.add_argument("--agent-timeout", type=float, default=None,
                    help="P5：单次 Agent 调用硬超时秒数（不给 ⇒ 按框架实测预算 dsh300/pi120/codex300）")
    rp.add_argument("--agent-max-calls", type=int, default=2,
                    help="P5：最多调用次数（含重试；默认 2）")
    rp.add_argument("--run-mode", default="RULE_ONLY",
                    help="★ 请求的运行模式（施工令 V3.0 §6）："
                         "RULE_ONLY（规则基线，成绩名 RULE_BASELINE_SCORE）｜"
                         "AGENT_REQUIRED（必须真模型，否则考试 FAIL、AI 成绩 NOT_SCORED）｜"
                         "AUTO（可降级，降级如实记录，不得记为 AI 成绩）")
    rp.add_argument("--codex-persist-session", action="store_true",
                    help="让 codex 落盘执行记录 ⇒ **模型身份可核实**（合成考场可开）")
    rp.add_argument("--out", default="", help="输出目录（默认在考试台数据面下）")
    rp.add_argument("--keep-db", action="store_true", help="保留本次数据面（默认重建）")
    rp.set_defaults(func=cmd_run)

    gp = sub.add_parser("gate", help="按冻结阈值判定 G1—G7")
    gp.add_argument("--runs", required=True, help="运行清单目录")
    gp.add_argument("--out", default="", help="门禁报告输出路径")
    gp.set_defaults(func=cmd_gate)

    cp = sub.add_parser("compare-runs",
                        help="P3 对照：多份运行清单横向比（考生|真实模型|模式|总分|相对规则增量|安全门禁）")
    cp.add_argument("--manifests", nargs="+", required=True, help="运行清单 JSON 路径（多个）")
    cp.add_argument("--out", default="", help="对照报告输出路径")
    cp.set_defaults(func=cmd_compare_runs)

    cp = sub.add_parser("coverage", help="自动化覆盖率报告")
    cp.add_argument("--runs", required=True)
    cp.add_argument("--out", default="")
    cp.set_defaults(func=cmd_coverage)

    pp = sub.add_parser("pytest-report", help="跑后端测试并写成门禁可读的机读报告（G1）")
    pp.add_argument("--out", required=True, help="报告输出路径（如 <runs>/g1_pytest.json）")
    pp.add_argument("--tests", default="tests/", help="pytest 目标（默认 tests/）")
    pp.set_defaults(func=cmd_pytest_report)

    a = p.parse_args(argv)
    return int(a.func(a))


def _proxy_sanitized_env(base: dict[str, str]) -> tuple[dict[str, str], str]:
    """把代理环境整理成「**不随操作员设置漂移**」的口径 ⇒ 返回 (env, 口径说明)。

    ★★ **为什么不是「直接 unset」**（本轮实测）：
      ``httpx`` 的 ``trust_env`` 会回落到 **macOS 系统代理**
      （``urllib.request.getproxies()`` 读 SystemConfiguration）⇒ 系统代理若是 **SOCKS**，
      客户端在**构造阶段**就抛 ``ImportError: Using SOCKS proxy, but 'socksio' is not installed``
      ⇒ 6 条 DD 精判用例在**与业务无关**的地方红（假红）。
      ⇒ 口径：**SOCKS 改写成同端口的 http 代理**；改写不了才清空。
    """
    env = dict(base)
    http_proxy = (env.get("https_proxy") or env.get("HTTPS_PROXY")
                  or env.get("http_proxy") or env.get("HTTP_PROXY") or "")
    for k in ("all_proxy", "ALL_PROXY", "http_proxy", "HTTP_PROXY",
              "https_proxy", "HTTPS_PROXY"):
        env.pop(k, None)
    if http_proxy.startswith(("http://", "https://")):
        for k in ("all_proxy", "ALL_PROXY", "http_proxy", "HTTP_PROXY",
                  "https_proxy", "HTTPS_PROXY"):
            env[k] = http_proxy
        return env, f"SOCKS_PROXY_OVERRIDDEN_TO_HTTP:{http_proxy}"
    return env, ("PROXY_VARS_CLEARED（无可用 http 代理；注意：macOS 系统代理若为 SOCKS "
                 "仍会导致 httpx 构造失败 ⇒ 6 条 DD 精判用例会假红）")


def cmd_pytest_report(a) -> int:
    """跑 pytest ⇒ 机读报告（G1 门禁只认机读证据）。

    ★ **环境口径**（两条，都**如实记进报告**，不是隐藏失败）：
      ① **代理口径**：本机 ``all_proxy`` 是 SOCKS 代理，而 ``httpx`` 未装
         ``socks`` 扩展 ⇒ SDK 客户端**在构造阶段**就抛错 ⇒ 6 条 DD 精判用例
         在**与业务无关**的地方红（**假红**）。
         ★★ **本轮实测修正**：**单纯清空代理变量并不够** —— ``httpx`` 的 ``trust_env``
         会回落到 **macOS 系统代理**（同样是 SOCKS）⇒ 照样构造失败。
         ⇒ 现在的口径是：**把 SOCKS 改写成同端口的 http 代理**（改写不了才清空），
         并把**实际生效的口径**写进报告的 ``env_hygiene.proxy_policy``。
         ⇒ 测试结果**不应随操作员的代理设置漂移**。
      ② **排除 ``tests/test_doctor_script.py``**：它要求仓内有 ``.env`` 与
         ``frontend/node_modules``（本机与沙箱都没有）⇒ **生产 CI 同样排除**
         （见 ``.github/workflows/ci.yml``）⇒ 口径与 CI 一致，**不是**为了让门禁变绿。
    """
    import subprocess
    backend = REPO / "backend"
    py = str(backend / ".venv" / "bin" / "python")
    if not Path(py).is_file():
        py = sys.executable
    env = dict(os.environ)
    # ★★ **代理口径（本轮实测修正过一次）**
    #   原做法：把 all_proxy/http_proxy/... 全部 **unset**。
    #   ★ **在本机这条不成立**：`httpx` 的 `trust_env` 会回落到 **macOS 系统代理**
    #     （`urllib.request.getproxies()` 读 SystemConfiguration）⇒ 系统代理是 **SOCKS** ⇒
    #     客户端在**构造阶段**就抛 `ImportError: Using SOCKS proxy, but 'socksio' is not installed`
    #     ⇒ 6 条 DD 精判用例在**与业务无关**的地方红（假红）。
    #   ⇒ 现在：**把 SOCKS 代理改写成同端口的 http 代理**（能连上就都走 http 通道），
    #     改写不了才 unset；并把**实际生效的代理口径**写进报告（不隐藏）。
    env, _proxy_note = _proxy_sanitized_env(os.environ)
    # ★ **绝对路径**：pytest 的 cwd 是 ``backend``，相对路径会被解析到
    #   ``backend/.audit/...``（目录不存在）⇒ **XML 静默不生成**
    #   ⇒ 计数回落成 total=0 却 exit=0 ⇒ **假绿**（本轮实测踩过）。
    out_path = Path(a.out).resolve()
    xml_path = out_path.with_suffix(".xml")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [py, "-m", "pytest", "-q", a.tests,
           "--ignore=tests/test_doctor_script.py",
           "--junitxml", str(xml_path)]
    proc = subprocess.run(cmd, cwd=backend, capture_output=True, text=True,
                          env=env, timeout=3600)
    out = proc.stdout or ""
    passed = failed = errors = skipped = 0
    failed_list: list[str] = []
    parse_error = ""
    attr_cross_check = ""
    # ★ 计数走 **JUnit XML**（机器可读，不靠解析终端摘要行）
    # ★★ **逐个 <testcase> 统计**，不靠 testsuite 属性：
    #    pytest 的 junitxml **不写 `passed` 属性**（只写 tests/failures/errors/skipped）
    #    ⇒ `s.get("passed")` 恒为 None ⇒ 只统计到 skipped ⇒ passed=0 的假象（本轮实测踩过）
    try:
        import xml.etree.ElementTree as ET
        if not xml_path.is_file():
            raise FileNotFoundError(f"junit xml 未生成: {xml_path}")
        root = ET.parse(str(xml_path)).getroot()
        n_case = 0
        for tc in root.iter("testcase"):
            n_case += 1
            if list(tc.findall("failure")):
                failed += 1
                failed_list.append(f"{tc.get('classname')}::{tc.get('name')}")
            elif list(tc.findall("error")):
                errors += 1
                failed_list.append(f"{tc.get('classname')}::{tc.get('name')} (error)")
            elif list(tc.findall("skipped")):
                skipped += 1
            else:
                passed += 1
        # 交叉校验：与 testsuite 的 tests 属性对账，不一致 ⇒ 记为解析异常
        attr_tests = 0
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        for s in suites:
            attr_tests += int(s.get("tests") or 0)
        if attr_tests and attr_tests != n_case:
            attr_cross_check = (f"testcase 逐个统计 n={n_case} 与 testsuite tests={attr_tests} 不一致")
    except Exception as exc:  # noqa: BLE001
        parse_error = f"{type(exc).__name__}: {exc}"
        failed_list = [ln for ln in out.splitlines() if ln.startswith("FAILED")]
        import re
        for line in out.splitlines():
            m = re.search(r"(\d+) passed", line)
            if m:
                passed = int(m.group(1))
            m = re.search(r"(\d+) failed", line)
            if m:
                failed = int(m.group(1))
    total = passed + failed + errors + skipped
    # ★★ **fail-closed**：计数拿不到 ⇒ **判失败**，不许「静默 0 条 ⇒ 通过」。
    #   本轮实证：junitxml 相对路径被解析到 backend/ 下 ⇒ XML 未生成
    #   ⇒ 旧实现 total=0 / exit=0 ⇒ G1 判「passed=0 failed=0」= **假绿**。
    #   第二处实证：pytest junitxml 无 `passed` 属性 ⇒ 只统计到 skipped。
    exit_code = proc.returncode
    counting_ok = (not parse_error) and (not attr_cross_check) and total > 0
    if not counting_ok:
        exit_code = exit_code or 97
        if parse_error:
            failed_list.append(f"__COUNTING_FAILED__:{parse_error}")
        elif attr_cross_check:
            failed_list.append(f"__COUNTING_FAILED__:{attr_cross_check}")
        else:
            failed_list.append("__COUNTING_FAILED__:total=0(未收集到任何测试)")
    report = {
        "schema_version": "dd_v1_pytest_report.v1",
        "generated_at": _now(),
        "git_sha": _git_sha(),
        # ★★ **溯源完整性**（独立 Reviewer 指出）：光记 SHA 不够 ——
        #   若生成报告时工作区是**脏的**，那么「测的代码」≠「HEAD 的代码」。
        #   ⇒ 必须把 dirty 状态**一并落盘**，否则证据无法自证对应哪份代码。
        "git_dirty": _git_dirty(),
        "git_dirty_note": ("★ git_dirty=true ⇒ 本次测试跑的是**工作区代码**，"
                           "与 HEAD **可能不一致** ⇒ 证据只能对应工作区，不能对应某个 commit。"),
        "command": " ".join(cmd),
        "env_hygiene": {
            "proxy_vars_cleared": True,
            "proxy_policy": _proxy_note,
            "proxy_policy_note": ("★ 本轮实测修正：单纯 unset 代理变量**不够** —— "
                                  "httpx 的 trust_env 会回落到 macOS 系统代理（可能是 SOCKS），"
                                  "而本机未装 socksio ⇒ SDK 客户端在构造阶段就抛 ImportError ⇒ "
                                  "6 条 DD 精判用例在**与业务无关**的地方红（假红）。"
                                  "⇒ 现在把 SOCKS 改写成同端口的 http 代理；"
                                  "改写不了才 unset，并在此如实记录。"),
            "excluded_tests": ["tests/test_doctor_script.py"],
            "exclusion_reason": ("该文件要求仓内有 .env 与 frontend/node_modules；"
                                 "生产 CI 同样排除（见 .github/workflows/ci.yml）"),
            "note": "★ 两条环境口径**都写在这里**，不隐藏任何失败条目。",
        },
        "exit_code": exit_code,
        "pytest_exit_code": proc.returncode,
        "counting_ok": counting_ok,
        "counting_parse_error": parse_error,
        "counting_cross_check": attr_cross_check,
        "junit_xml": str(xml_path),
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "total": total,
        "failed_list": failed_list,
        "tail": out[-4000:],
        "note": ("★ **分母不许缩**：本报告保留全部失败条目；"
                 "已知的环境类失败**照实列出**，由门禁与复核者判断，不由本工具隐藏。"),
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({k: report[k] for k in ("passed", "failed", "errors", "skipped",
                                             "total", "exit_code", "counting_ok")},
                     ensure_ascii=False))
    return 0 if exit_code == 0 else 1


def cmd_list(a) -> int:
    for e in EXAM_IDS:
        s = _spec(e)
        exp = json.loads((EXAMS_DIR / e / "expectations.json").read_text("utf-8"))
        mats = sum(1 for _ in (EXAMS_DIR / e / "materials").rglob("*") if _.is_file())
        print(json.dumps({"exam": e, "title": s.get("title"),
                          "questions": len(exp.get("questions") or {}),
                          "materials": mats,
                          "entities": len(s.get("entities") or [])},
                         ensure_ascii=False))
    return 0


def cmd_run(a) -> int:
    m = run_exam(a.exam, agent=a.agent, agent_result=a.agent_result,
                 allow_local_dsh=a.allow_local_dsh, reset=not a.keep_db,
                 out_dir=a.out, run_mode=str(getattr(a, "run_mode", "") or "RULE_ONLY"),
                 codex_persist_session=bool(getattr(a, "codex_persist_session", False)),
                 agent_timeout=getattr(a, "agent_timeout", None),
                 agent_max_calls=int(getattr(a, "agent_max_calls", 2) or 2))
    # ★ 独立 Reviewer 第 2 轮建议：0 件交付要**显式醒目告警**。
    #   否则「跑挂了（0 交付）」与「跑通了但分低」在摘要里长得一样（都是 SCORED/LOW_CONFIDENCE），
    #   容易被当成正常读数。
    _cnt = (m["results"].get("counts") or {})
    _delivered = int(_cnt.get("delivered_files") or 0)
    if _delivered == 0:
        print("🚨 警告：**本场 0 件交付** —— 总分被强制为 0（HR-1）。"
              "请先确认：① 考场披露策略文件是否还在（`exam-policy-*.json`）；"
              "② 材料是否被判成受限；③ `--out` 是否误指向了数据面。",
              flush=True)
    print(json.dumps({"exam": m["exam"], "run_id": m["run_id"], "status": m["results"]["status"],
                      "scores": m["results"]["scores"],
                      "delivered_files": _delivered,
                      "delivered_files_attributed": _cnt.get("delivered_files_attributed"),
                      "safety": (m["results"].get("safety_gate") or {}).get("status"),
                      "failures": len(m["failures"]),
                      "manifest": str(Path(a.out or (exam_plane(a.exam) / "runs" / m["run_id"]))
                                     / "运行清单.json")},
                     ensure_ascii=False, indent=2))
    # ★ 退出码口径（与门禁 `status_scored` **同一语义**，别再分叉）：
    #   SCORED / SCORED_PARTIAL / LOW_CONFIDENCE = **已评分**（分数照给）⇒ 退出码 0
    #   ★ LOW_CONFIDENCE 只表示「义务条数 < 30、样本量不足」的**标注**，
    #     评分规范原文就是「**分数仍给**」⇒ 让它退出码非 0 会让交接方
    #     按文档跑完看到 exit=1 却拿到 96.67 分 ⇒ **误判为失败**。
    #   NOT_SCORABLE（未评分）/ DIAGNOSTIC_ONLY（只诊断）⇒ 退出码非 0（**真的没出分**）。
    return 0 if m["results"]["status"] in ("SCORED", "SCORED_PARTIAL", "LOW_CONFIDENCE") else 1


def cmd_gate(a) -> int:
    rep = evaluate_gate(a.runs)
    text = json.dumps(rep, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text, "utf-8")
    print(text)
    return 0 if rep.get("status") == "PASS" else 1


# ═══════════════════════════════════════════════════════════════════════════
# P3 对照：同一份冻结题 + Gold，多名考生（规则基线 / 真模型）横向比
# ═══════════════════════════════════════════════════════════════════════════

def compare_runs(manifest_paths: list[str]) -> dict[str, Any]:
    """把多份**运行清单**横向对比（施工令 V3.0 §8 要求的表）。

    表头：**考生 | 真实模型 | 模式 | 总分 | 相对规则增量 | 安全门禁**

    ★ **规则基线是参照系**：第一个 ``RULE_ONLY`` 的场次即基线；
      其它场次给出「相对规则增量」= 本场 AI 分 − 规则基线分。
    ★ ★ **增量不是因果贡献**（§8 明文）：两场运行不是受控对照实验
      （环境/时序/材料快照都可能不同）⇒ 这里只给数，**不给因果结论**。
    ★ 三列成绩**永远分列**：模型缺席时 AI 列 NOT_SCORED（**不是** 0）。
    """
    rows: list[dict[str, Any]] = []
    for raw in manifest_paths:
        p = Path(raw)
        m = json.loads(p.read_text("utf-8"))
        mp = dict(m.get("model") or {})
        res = dict(m.get("results") or {})
        split = dict(res.get("score_split") or {})
        safety = dict(res.get("safety_gate") or {})
        rows.append({
            "source": str(p),
            "exam": str(m.get("exam") or ""),
            "run_id": str(m.get("run_id") or ""),
            "git_sha": str(m.get("git_sha") or ""),
            "candidate": str(mp.get("agent_spec") or "none"),
            "actual_model": str(mp.get("actual_model") or "UNKNOWN"),
            "model_identity_verified": bool(mp.get("model_identity_verified")),
            "requested_mode": str(mp.get("requested_mode") or "RULE_ONLY"),
            "execution_path": str(mp.get("execution_path") or ""),
            "score_name": str(split.get("score_name") or ""),
            "total_score": (res.get("scores") or {}).get("total_score"),
            "rule_baseline_score": split.get("rule_baseline_score"),
            "ai_system_score": split.get("ai_system_score"),
            "ai_system_score_status": split.get("ai_system_score_status"),
            "safety_gate": str(safety.get("status") or ""),
            "elapsed_s": (m.get("elapsed_s")),
        })
    # ★ 规则基线：第一个 ``RULE_ONLY`` 场次（**参照系**）
    baseline = next((r for r in rows if r["execution_path"] in
                     (rm.EXEC_PATH_RULE_ONLY, rm.EXEC_PATH_DEGRADED)
                     and isinstance(r.get("total_score"), (int, float))), None)
    base_score = baseline.get("total_score") if baseline else None
    for r in rows:
        ts = r.get("total_score")
        r["delta_vs_rule_baseline"] = (round(float(ts) - float(base_score), 2)
                                       if isinstance(ts, (int, float))
                                       and isinstance(base_score, (int, float)) else None)
    return {
        "schema_version": "dd_v1_exam_comparison.v1",
        "generated_at": _now(),
        "rule_baseline": {
            "source": (baseline or {}).get("source", ""),
            "run_id": (baseline or {}).get("run_id", ""),
            "total_score": base_score,
            "git_sha": (baseline or {}).get("git_sha", ""),
        },
        "rows": rows,
        "table_header": ["考生", "真实模型", "模式", "总分", "相对规则增量", "安全门禁"],
        "note": ("★ **增量不是因果贡献**：各场次不是受控对照实验"
                 "（环境/时序/快照可能不同）⇒ 要归因须走**错误分类 ＋ 消融测试**。\n"
                 "★ **规则基线分与 AI 系统分分列**：模型缺席时 AI 列 = NOT_SCORED（**不是** 0 分）。\n"
                 "★ 若某模型方案**不优于**规则基线 ⇒ **如实报告**（不因用了 AI 就默认更先进）。"),
    }


def cmd_compare_runs(a) -> int:
    rep = compare_runs(list(a.manifests or []))
    text = json.dumps(rep, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text, "utf-8")
    # 人看的表
    print("考生 | 真实模型 | 模式 | 总分 | 相对规则增量 | 安全门禁")
    for r in rep["rows"]:
        print(f"{r['candidate']} | {r['actual_model']}"
              f"{'' if r['model_identity_verified'] else '(身份未核实)'}"
              f" | {r['requested_mode']}→{r['execution_path']}"
              f" | {r['total_score']} | {r['delta_vs_rule_baseline']} | {r['safety_gate']}")
    print()
    print(rep["note"])
    return 0


def cmd_coverage(a) -> int:
    rep = coverage_report(a.runs)
    text = json.dumps(rep, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text, "utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
