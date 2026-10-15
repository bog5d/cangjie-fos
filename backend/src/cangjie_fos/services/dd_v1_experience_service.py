"""DD-V1 纠错经验、回归数据集与自动化评分接口（WP5）。

三块内容，一个共同纪律：**分数和经验都必须来自可核查证据，不来自 AI 自述。**

## 一、纠错经验四层分级

```
feedback  人工修改的原始留痕（一次修改永远从这里开始，永不自动向上）
   ↓ 需独立复核
candidate 经验候选
   ↓ 需 Gate 通过（gate_by / gate_at / gate_result 必填）
approved  正式经验，可在同类尽调中优先调用
   ↓ 需配套回归用例
regression 回归用例（进回归数据集，每次变更必跑）
```

**一次人工修改不得无条件升级为全局规则。**
`record_feedback()` 写入的 tier 恒为 ``feedback``，且 ``scope_entity`` 必填；
任何晋级都必须显式调用对应的 `promote_*` 并留下 Gate 痕迹。

## 二、复用前必须复验

``validate_experience_scope()`` 对主体、期间、文件类型、机构、模板五项做校验。
**主体或期间发生变化时必须重新验证**——这是对治旧 ``dd_decision_memory``
「写而不读、跨主体自动锁定」的老毛病。

## 三、自动化评分接口

按 Goal Contract 冻结的五项 metric（合计 100 分）逐项打分，口径固定：

- **必须有回归数据集（gold set）才可能得分。** 没有 gold set 就全是 UNKNOWN/0 分，
  **绝不因为「跑通了」而自评高分**。
- 每一分都要能指回**具体义务**的具体判定。
- **硬门槛独立于总分**：HG1 越权披露 / HG2 主体冒充 / HG3 虚假完整，
  任一 FAIL 即整体不可判 PASS，**不允许被高总分稀释**。
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from pathlib import Path

from cangjie_fos.services import dd_v1_match_service as ms
from cangjie_fos.services import dd_v1_manifest_service as mf
from cangjie_fos.services import dd_v1_requirement_service as rq

logger = logging.getLogger(__name__)

# 经验分层
T_FEEDBACK = "feedback"
T_CANDIDATE = "candidate"
T_APPROVED = "approved"
T_REGRESSION = "regression"

_DDL = """
CREATE TABLE IF NOT EXISTS dd_v1_experience (
    exp_id           TEXT PRIMARY KEY,
    library_id       TEXT NOT NULL,
    tier             TEXT NOT NULL DEFAULT 'feedback',
    requirement_norm TEXT NOT NULL DEFAULT '',
    obligation_id    TEXT NOT NULL DEFAULT '',
    rule_json        TEXT NOT NULL DEFAULT '{}',
    reason           TEXT NOT NULL DEFAULT '',
    edited_by        TEXT NOT NULL DEFAULT '',
    institution      TEXT NOT NULL DEFAULT '',
    template         TEXT NOT NULL DEFAULT '',
    scope_entity     TEXT NOT NULL DEFAULT '',
    created_at       REAL NOT NULL,
    promoted_by      TEXT NOT NULL DEFAULT '',
    promoted_at      REAL,
    gate_result      TEXT NOT NULL DEFAULT '',
    version          TEXT NOT NULL DEFAULT 'v1'
);
CREATE INDEX IF NOT EXISTS idx_dd_v1_exp_lib ON dd_v1_experience(library_id, tier);
CREATE INDEX IF NOT EXISTS idx_dd_v1_exp_norm ON dd_v1_experience(requirement_norm);

-- 回归数据集（gold mappings）：历史人工交付包 / 机构原件
CREATE TABLE IF NOT EXISTS dd_v1_regression_cases (
    case_id       TEXT PRIMARY KEY,
    library_id    TEXT NOT NULL,
    source_ref    TEXT NOT NULL,
    item_no       TEXT NOT NULL DEFAULT '',
    raw_text      TEXT NOT NULL,
    expected_json TEXT NOT NULL DEFAULT '{}',
    created_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dd_v1_rc_lib ON dd_v1_regression_cases(library_id);
"""

_NORM_PUNCT_RE = re.compile(r"[\s　，,。.、；;：:（）()【】\[\]“”\"'’]+")


def _ensure(conn) -> None:
    conn.executescript(_DDL)
    conn.commit()


def _conn(db_path: Path | None = None):
    conn = mf._connect(db_path)
    _ensure(conn)
    rq._ensure_schema(conn)
    ms._ensure_schema(conn)
    # HG1 要读审核单状态，评分接口必须能看到 WP4 的表，
    # 否则「只评分不做组包」这条路径会因缺表崩掉。
    from cangjie_fos.services.dd_v1_package_service import _ensure as _pkg_ensure
    _pkg_ensure(conn)
    return conn


def normalize_requirement(raw: str) -> str:
    """需求归一化：去标点空白、去掉具体年份与编号，便于同类经验复用。"""
    s = _NORM_PUNCT_RE.sub("", raw or "")
    s = re.sub(r"\d{4}", "#", s)
    s = re.sub(r"[一二三四五六七八九十两\d]+年", "#年", s)
    return s.strip()


# ── 一、经验留痕与晋级 ────────────────────────────────────────────────────
def record_feedback(
    library_id: str,
    raw_requirement: str,
    reason: str,
    edited_by: str,
    obligation_id: str = "",
    machine_verdict: str = "",
    candidates: list | None = None,
    corrected: list | None = None,
    scope_entity: str = "",
    institution: str = "",
    template: str = "",
    db_path: Path | None = None,
) -> dict:
    """记录一次人工修改。**tier 恒为 feedback，绝不自动晋级。**"""
    if not edited_by.strip():
        raise ValueError("edited_by 不能为空：纠错必须可追责")
    if not reason.strip():
        raise ValueError("reason 不能为空：纠错必须写明原因")
    if not scope_entity.strip():
        raise ValueError("scope_entity 不能为空：没有适用主体的经验不得入库")

    conn = _conn(db_path)
    exp_id = uuid.uuid4().hex
    rule = {
        "machine_verdict": machine_verdict,
        "candidates": candidates or [],
        "corrected": corrected or [],
    }
    conn.execute(
        """INSERT INTO dd_v1_experience
           (exp_id, library_id, tier, requirement_norm, obligation_id, rule_json,
            reason, edited_by, institution, template, scope_entity, created_at, version)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'v1')""",
        (exp_id, library_id, T_FEEDBACK, normalize_requirement(raw_requirement),
         obligation_id, json.dumps(rule, ensure_ascii=False), reason, edited_by,
         institution, template, scope_entity, time.time()),
    )
    conn.commit()
    return {
        "exp_id": exp_id, "tier": T_FEEDBACK,
        "auto_promoted": False,
        "requires": "独立复核后方可 promote_to_candidate",
    }


def promote(
    exp_id: str,
    to_tier: str,
    promoted_by: str,
    gate_result: str,
    db_path: Path | None = None,
) -> dict:
    """晋级经验。**必须留 Gate 痕迹**，且不得跳级。"""
    if to_tier not in (T_CANDIDATE, T_APPROVED, T_REGRESSION):
        raise ValueError(f"非法目标层级：{to_tier}")
    if not promoted_by.strip() or not gate_result.strip():
        raise ValueError("promoted_by 与 gate_result 均为必填：晋级必须有 Gate 痕迹")

    conn = _conn(db_path)
    row = conn.execute(
        "SELECT * FROM dd_v1_experience WHERE exp_id=?", (exp_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"经验不存在：{exp_id}")
    order = [T_FEEDBACK, T_CANDIDATE, T_APPROVED, T_REGRESSION]
    cur = row["tier"]
    if order.index(to_tier) != order.index(cur) + 1:
        raise ValueError(f"不得跳级晋级：{cur} → {to_tier}")

    conn.execute(
        """UPDATE dd_v1_experience SET tier=?, promoted_by=?, promoted_at=?,
           gate_result=? WHERE exp_id=?""",
        (to_tier, promoted_by, time.time(), gate_result, exp_id),
    )
    conn.commit()
    return {"exp_id": exp_id, "tier": to_tier, "promoted_by": promoted_by}


def validate_experience_scope(
    exp: dict,
    current_entity: str = "",
    current_period: tuple[int, int] | None = None,
    current_doctype: str = "",
    institution: str = "",
    template: str = "",
) -> tuple[bool, str]:
    """复用前复验。**主体/期间/文件类型/机构/模板任一不符即拒绝。**

    对治旧 ``dd_decision_memory``「把 institution 写进去却从不在 lookup 读」
    导致的跨主体自动锁定。
    """
    scope = (exp.get("scope_entity") or "").strip()
    if not scope:
        return False, "经验无适用主体，不得跨主体复用"
    if current_entity and current_entity != scope:
        return False, f"主体不符：经验适用={scope} 当前={current_entity}"

    rule = {}
    try:
        rule = json.loads(exp.get("rule_json") or "{}")
    except (ValueError, TypeError):
        rule = {}
    if current_period:
        yrs = rule.get("years")
        if yrs:
            if not all(current_period[0] <= int(y) <= current_period[1] for y in yrs):
                return False, f"期间不符：经验年份 {yrs} 不在 {current_period}"
    if current_doctype:
        dt = rule.get("doc_type")
        if dt and dt != current_doctype:
            return False, f"材料类型不符：经验={dt} 当前={current_doctype}"
    if institution and exp.get("institution") and institution != exp["institution"]:
        return False, f"机构不符：经验={exp['institution']} 当前={institution}"
    if template and exp.get("template") and template != exp["template"]:
        return False, f"模板不符：经验={exp['template']} 当前={template}"
    return True, "通过"


def recall_experience(
    library_id: str,
    raw_requirement: str,
    current_entity: str = "",
    current_period: tuple[int, int] | None = None,
    institution: str = "",
    template: str = "",
    db_path: Path | None = None,
) -> dict:
    """召回同类已批准经验，并**逐条复验适用范围**。复验不通过的直接丢弃。"""
    conn = _conn(db_path)
    rows = [dict(r) for r in conn.execute(
        """SELECT * FROM dd_v1_experience
           WHERE library_id=? AND tier IN (?,?)
           ORDER BY created_at DESC""",
        (library_id, T_APPROVED, T_REGRESSION))]
    norm = normalize_requirement(raw_requirement)
    out, rejected = [], []
    for r in rows:
        if r["requirement_norm"] != norm:
            continue
        ok, why = validate_experience_scope(r, current_entity, current_period,
                                             institution=institution,
                                             template=template)
        if ok:
            out.append({"exp_id": r["exp_id"], "tier": r["tier"],
                        "rule": r["rule_json"], "scope_entity": r["scope_entity"]})
        else:
            rejected.append({"exp_id": r["exp_id"], "reason": why})
    return {"matched": len(out), "experiences": out, "rejected": rejected}


# ── 二、回归数据集 ────────────────────────────────────────────────────────
def add_regression_case(
    library_id: str,
    raw_text: str,
    source_ref: str,
    item_no: str = "",
    expected_verdict: str = "",
    expected_files: list | None = None,
    note: str = "",
    db_path: Path | None = None,
) -> dict:
    """录入回归用例。

    ``source_ref`` 必填：**来源不明的 gold set 不准入回归数据集**——
    否则会把错误答案固化成「标准答案」。
    """
    if not source_ref.strip():
        raise ValueError("source_ref 不能为空：回归用例必须有出处（历史人工交付包/机构原件）")
    if not raw_text.strip():
        raise ValueError("raw_text 不能为空")
    conn = _conn(db_path)
    case_id = uuid.uuid4().hex
    conn.execute(
        """INSERT INTO dd_v1_regression_cases
           (case_id, library_id, source_ref, item_no, raw_text, expected_json, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (case_id, library_id, source_ref, item_no, raw_text,
         json.dumps({"verdict": expected_verdict, "files": expected_files or [],
                     "note": note}, ensure_ascii=False), time.time()),
    )
    conn.commit()
    return {"case_id": case_id, "library_id": library_id, "source_ref": source_ref}


def list_regression_cases(library_id: str, db_path: Path | None = None) -> list[dict]:
    conn = _conn(db_path)
    out = []
    for r in conn.execute(
            "SELECT * FROM dd_v1_regression_cases WHERE library_id=?", (library_id,)):
        d = dict(r)
        d["expected"] = json.loads(d.pop("expected_json") or "{}")
        out.append(d)
    return out


# ── 三、自动化评分接口 ────────────────────────────────────────────────────
def score_library(library_id: str, db_path: Path | None = None) -> dict:
    """按冻结的五项权重打分。

    ## 「不可评分」与「评分为 0」是两件事，绝不混同

    SCP v3.8 防误判回归第 9 条：**任何重大结论缺足够证据应为 UNKNOWN，
    不能自动降级成 FAIL/0。** 因此本接口显式区分三种测量状态：

    ==============================  =====================  ==========================
    measurement_state                verified_points       含义
    ==============================  =====================  ==========================
    ``NOT_SCORABLE``                 0（**不代表质量差**）    无 gold set 或无可测义务，
                                                          **根本无法测量**
    ``MEASURED`` / ``LOW_CONFIDENCE``  实测值                 有 gold set 且逐条比对完成，
                                                          分数有意义
    ==============================  =====================  ==========================

    调用方**必须**读 ``measurement_state`` 判断分数是否有意义，
    **不得**把 ``NOT_SCORABLE`` 的 0 读成「测过了、不达标」。
    """
    conn = _conn(db_path)
    cases = list_regression_cases(library_id, db_path=db_path)
    has_gold = bool(cases)

    n_obligations = conn.execute(
        "SELECT COUNT(*) c FROM dd_v1_obligations WHERE library_id=?",
        (library_id,)).fetchone()["c"]

    gates = compute_hard_gates(library_id, db_path=db_path)
    # 只有**数据派生的硬门槛**能阻断终局判定。
    # HG4「不虚称自主」是常驻声明（GM 基线 G01/G08 FAIL + 无持久调度器），
    # 若把它也算作阻断门槛，goal_state 会永远是 BLOCKED_BY_HARD_GATE，
    # 反而使 HG1/2/3 的信号失效。HG4 照常如实上报，但单独标注。
    blocking = [g for g in gates if g["id"] != "HG4_不虚称自主"]
    gate_fail = any(g["status"] == "FAIL" for g in blocking)

    metrics = _metric_definitions()
    detail: list = []
    total = 0.0
    if has_gold:
        detail, total = _score_against_gold(library_id, cases, metrics, db_path)
        measurement_state = "MEASURED" if detail else "NOT_SCORABLE"
    else:
        measurement_state = "NOT_SCORABLE"

    if measurement_state == "NOT_SCORABLE":
        reason = ("无回归数据集（gold set），无法测量该项达成度。"
                  "此处的 0 表示「不可评分」，**不是**「测过了不达标」。"
                  if not has_gold else
                  "有 gold set，但无与之对应的义务，无法逐条比对。"
                  "此处的 0 表示「不可评分」，不是「测过了不达标」。")
        for m in metrics:
            m["verified_points"] = 0
            m["status"] = "UNKNOWN"
            m["measurement_state"] = "NOT_SCORABLE"
            m["points_are_meaningful"] = False
            m["not_scorable_reason"] = reason
            m["evidence_refs"] = []
        total = 0.0

    if gate_fail:
        goal_state = "BLOCKED_BY_HARD_GATE"
    elif measurement_state == "NOT_SCORABLE":
        goal_state = "NOT_SCORABLE"
    elif total >= 100:
        goal_state = "MET"
    else:
        goal_state = "NOT_MET"

    return {
        "library_id": library_id,
        "scored_on": "regression_gold_set" if has_gold else "NO_GOLD_SET",
        "measurement_state": measurement_state,
        "scorable": measurement_state != "NOT_SCORABLE",
        "regression_cases": len(cases),
        "obligations": n_obligations,
        "metrics": metrics,
        "verified_points": total,
        "total_points": 100,
        "goal_state": goal_state,
        "hard_gates": gates,
        "reading_guide": (
            "goal_state=NOT_SCORABLE 表示当前无法评分，**不得**解读为质量不达标；"
            "要有意义的分数，需先录入带 source_ref 的回归用例。"
            "goal_state=BLOCKED_BY_HARD_GATE 表示硬门槛失败，**总分再高也不可判通过**。"
        ),
        "self_report_prohibited": (
            "本分数由可核查的逐条义务判定算出，不接受 LLM 自评；"
            "无回归数据集时标 NOT_SCORABLE 而非计 0 分。"
        ),
    }


def _metric_definitions() -> list[dict]:
    return [
        {"id": "M1_需求理解", "weight": 20, "verified_points": 0,
         "status": "UNKNOWN", "evidence_refs": [],
         "definition": "原子义务拆解保真度：机构原编号与原文零丢失；主体/年度/口径/签章/附件识别正确率"},
        {"id": "M2_多主体多年度覆盖", "weight": 25, "verified_points": 0,
         "status": "UNKNOWN", "evidence_refs": [],
         "definition": "主体覆盖×期间覆盖×材料类型×必备附件四维完整性正确率"},
        {"id": "M3_匹配正确性", "weight": 25, "verified_points": 0,
         "status": "UNKNOWN", "evidence_refs": [],
         "definition": "逐义务判定正确率 + 高置信误配率 + 漏检精确率"},
        {"id": "M4_版本证据权限", "weight": 20, "verified_points": 0,
         "status": "UNKNOWN", "evidence_refs": [],
         "definition": "业务有效版本判定正确率 + 证据可追溯率 + 受限文件排除率 + 经验跨主体串用率"},
        {"id": "M5_最终组包质量", "weight": 10, "verified_points": 0,
         "status": "UNKNOWN", "evidence_refs": [],
         "definition": "目录结构合规率 + hash 核验通过率 + 人工批准 Gate 实际拦截率"},
    ]


def _score_against_gold(library_id, cases, metrics, db_path):
    """逐条义务与 gold 期望比对。有 gold 才可能拿分。"""
    conn = _conn(db_path)
    by_no = {}
    for r in conn.execute(
            """SELECT o.obligation_id, i.item_no FROM dd_v1_obligations o
               LEFT JOIN dd_v1_checklist_items i ON i.item_uid=o.item_uid
               WHERE o.library_id=?""", (library_id,)):
        by_no.setdefault(r["item_no"] or "", []).append(r["obligation_id"])

    correct = total = 0
    detail = []
    for c in cases:
        exp = c["expected"]
        want = exp.get("verdict")
        for oid in by_no.get(c["item_no"] or "", []):
            st = ms.get_status(oid, db_path=db_path)
            if not st:
                continue
            total += 1
            hit = (want == st["verdict"]) if want else None
            if hit:
                correct += 1
            detail.append({"case_id": c["case_id"], "item_no": c["item_no"],
                           "expected": want, "actual": st["verdict"],
                           "hit": hit})
    acc = (correct / total) if total else 0.0
    # **样本量下限**：只看 1~2 条 gold case 就给满分是不可信的。
    # 样本不足时得分封顶在权重的 50%，与 GCCSEG 对 ISOLATED_PASS 的上限一致。
    LOW_CONFIDENCE_CAP = 0.5
    for m in metrics:
        raw_pts = round(m["weight"] * acc, 2)
        capped = raw_pts > m["weight"] * LOW_CONFIDENCE_CAP
        if capped:
            m["verified_points"] = round(m["weight"] * LOW_CONFIDENCE_CAP, 2)
            m["status"] = "LOW_CONFIDENCE"
            m["measurement_state"] = "LOW_CONFIDENCE"
            m["points_are_meaningful"] = True
        elif raw_pts > 0 and detail:
            m["verified_points"] = raw_pts
            m["status"] = "MEASURED"
            m["measurement_state"] = "MEASURED"
            m["points_are_meaningful"] = True
        else:
            m["verified_points"] = 0.0
            m["status"] = "UNKNOWN"
        m["evidence_refs"] = detail[:50] if detail else []
    return detail, round(sum(m["verified_points"] for m in metrics), 2)


def compute_hard_gates(library_id: str, db_path: Path | None = None) -> list[dict]:
    """硬门槛：**独立于总分**，任一 FAIL 即阻断「可交付/100%」宣称。

    三条对应 Goal Contract 的 HG1 / HG2 / HG3，全部从真实数据算，不靠自述。
    """
    conn = _conn(db_path)

    # HG1 未授权披露：是否存在「未批准就组包」或「受限材料进了交付目录」
    reviews = [dict(r) for r in conn.execute(
        "SELECT * FROM dd_v1_reviews WHERE library_id=?", (library_id,))]
    hg1_fail = []
    for r in reviews:
        if r["status"] == "packaged" and not (r["approved_by"] or "").strip():
            hg1_fail.append(f"review {r['review_id']} 状态 packaged 但无批准人")
    for m in conn.execute(
            """SELECT DISTINCT m.file_id, c.rel_path FROM dd_v1_matches m
               JOIN dd_v1_material_cards c ON c.file_id=m.file_id
               WHERE m.library_id=? AND m.deliverable=0""", (library_id,)):
        pass  # 受限材料被排除属正常，不算 HG1 失败；真正失败是「被纳入」
    hg1 = {
        "id": "HG1_无越权披露",
        "status": "FAIL" if hg1_fail else ("UNKNOWN" if not reviews else "PASS"),
        "evidence_refs": hg1_fail or [f"reviews={len(reviews)}"],
        "desc": "未经人工最终批准的材料不得进入可对外交付结果",
    }

    # HG2 主体冒充：不同主体的材料被当作同一主体使用
    by_file = {}
    for r in conn.execute(
            """SELECT m.obligation_id, m.file_id, c.entity, c.rel_path
               FROM dd_v1_matches m JOIN dd_v1_material_cards c ON c.file_id=m.file_id
               WHERE m.library_id=?""", (library_id,)):
        d = by_file.setdefault(r["file_id"], {"entity": r["entity"], "obligations": []})
        d["obligations"].append(r["obligation_id"])
    hg2_fail = []
    for fid, d in by_file.items():
        ents = {e for e in [d["entity"]] if e}
        if len(ents) > 1:
            hg2_fail.append(f"file {fid} 关联多个主体：{sorted(ents)}")
    hg2 = {
        "id": "HG2_无主体冒充",
        "status": "FAIL" if hg2_fail else ("UNKNOWN" if not by_file else "PASS"),
        "evidence_refs": hg2_fail or [f"matched_files={len(by_file)}"],
        "desc": "不同主体的同名材料不得互相替代；不得以错误主体文件充当正确材料",
    }

    # HG3 虚假完整：判 MATCHED 但四维覆盖未满
    hg3_fail = []
    n_matched = 0
    for r in conn.execute(
            "SELECT * FROM dd_v1_obligation_status WHERE library_id=? AND verdict=?",
            (library_id, ms.V_MATCHED)):
        n_matched += 1
        if (r["entity_cov"] < 1.0 or r["period_cov"] < 1.0 or r["doctype_cov"] < 1.0):
            hg3_fail.append(
                f"obligation {r['obligation_id']} 判 MATCHED 但覆盖不满 "
                f"(ent={r['entity_cov']}, period={r['period_cov']}, doc={r['doctype_cov']})")
    hg3 = {
        "id": "HG3_无虚假完整",
        "status": "FAIL" if hg3_fail else ("UNKNOWN" if not n_matched else "PASS"),
        "evidence_refs": hg3_fail or [f"matched_obligations={n_matched}"],
        "desc": "存在重大遗漏时不得标记为完整/已覆盖",
    }

    # HG4 不虚称自主（沿用 WP0 结论）
    hg4 = {
        "id": "HG4_不虚称自主",
        "status": "FAIL",
        "evidence_refs": ["cangjie-gm/ACCEPTANCE.md G01/G08 基线 FAIL",
                          "本会话无持久后台调度器"],
        "desc": "不得宣称无人值守自动续跑",
    }
    return [hg1, hg2, hg3, hg4]
