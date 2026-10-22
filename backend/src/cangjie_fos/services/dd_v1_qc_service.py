"""DD-V1 五维齐套判定（G-A3-3 · A3）。

## 为什么要有这一层

A2 的判定层算的是**四维覆盖率**（主体 / 期间 / 材料类型 / 必备附件）。
「齐套」要回答的却是**五维**：

    主体（哪些主体各需什么） × 年度（哪几年） × 材料类型 × 必备附件 × **份数**

A3（G-A3-1）把「应有几份」升成正式维度 ⇒ 这一层补上第五维，
并统一产出**「缺哪一维」**的结论，而不是让各处各写各的。

## 单一来源纪律（红线）

★ 本模块**不重算**任何覆盖率。
  主体 / 期间 / 类型 / 附件的覆盖率由判定层
  （``dd_v1_match_service.judge``）算好后作为**入参**传进来。
  本模块只做三件事：

  ① 判断每个维度**是否构成门槛**（required）——「清单压根没提」≠「提到了但缺」；
  ② 判断每个维度**是否可判定**（determinable）；
  ③ 产出**指名缺哪一维**的缺口文案。

⇒ 仓内**不会出现第二份覆盖率规则表**（这正是 A2 消灭的病）。

## 份数维的三态（A3-1）

| ``expected_count`` | 含义 | 本层判定 |
|---|---|---|
| ``0`` | 清单**未规定**份数 | 该维**不构成门槛**（与「期间未提」同规格） |
| ``None`` | 清单**提及**份数但**解析不出** | 该维**不可判定** ⇒ 必须给 UNCERTAIN + 人工确认 |
| ``N > 0`` | 权威份数 N | 该维构成门槛：可交付份数 < N ⇒ 缺份数 |

★ **不得默认 1 份**——「解析不出」与「规定就是 1 份」是两件事。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── 五个维度（顺序固定，便于逐条核对）──────────────────────────────────────
DIM_ENTITY = "entity"
DIM_PERIOD = "period"
DIM_DOCTYPE = "doctype"
DIM_ATTACHMENT = "attachment"
DIM_COUNT = "count"

DIMENSIONS = (DIM_ENTITY, DIM_PERIOD, DIM_DOCTYPE, DIM_ATTACHMENT, DIM_COUNT)

#: 维度 → 中文标签（缺口文案里**指名缺哪一维**用）
DIM_LABELS = {
    DIM_ENTITY: "主体",
    DIM_PERIOD: "期间",
    DIM_DOCTYPE: "材料类型",
    DIM_ATTACHMENT: "必备附件",
    DIM_COUNT: "份数",
}

#: 「这一维没提 / 不构成门槛」时统一口径
NOT_REQUIRED = "清单未就该维度提出要求（不构成门槛）"


def dim_label(dim: str) -> str:
    return DIM_LABELS.get(dim, str(dim))


def count_dimension(obl: dict, available: int) -> dict:
    """份数维度的齐套状态。

    ``available`` = **同一「主体 × 期间」格子里可交付的份数**
    （不是候选池总数——那会把「5 份不同年份的审计报告」误当成「一式五份」）。

    ★ 三态语义见模块 docstring。
    """
    # ★ 「键不存在」= 这条义务**早于份数维度**（旧库/旧数据）⇒ 不构成门槛；
    #   「键存在但值为 None」= **提及了份数但解析不出** ⇒ 不可判定。
    #   这两件事**必须**分开：混为一谈 ⇒ 旧库上的全部义务被误判 UNCERTAIN。
    raw = obl.get("expected_count", 0)
    base = {
        "dimension": DIM_COUNT,
        "label": DIM_LABELS[DIM_COUNT],
        "available": int(available or 0),
    }
    if raw is None:
        return {
            **base,
            "required": True,
            "determinable": False,
            "expected": None,
            "ok": False,
            "basis": str(obl.get("expected_count_basis") or "UNKNOWN"),
            "detail": "份数不可判定（维度：份数）：清单原文提及份数但无法解析出权威份数，"
                      "需人工确认；不得默认 1 份",
        }
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return {
            **base,
            "required": False,
            "determinable": True,
            "expected": 0,
            "ok": True,
            "basis": str(obl.get("expected_count_basis") or "UNKNOWN"),
            "detail": f"{NOT_REQUIRED}（维度：份数）",
        }
    ok = base["available"] >= n
    detail = (f"份数齐备（维度：份数）：应有 {n} 份，同一主体×期间可交付 "
              f"{base['available']} 份"
              if ok else
              f"份数缺 {n - base['available']}/{n} 份（维度：份数）："
              f"应有 {n} 份，同一主体×期间可交付 {base['available']} 份")
    return {
        **base,
        "required": True,
        "determinable": True,
        "expected": n,
        "ok": ok,
        "basis": str(obl.get("expected_count_basis") or "UNKNOWN"),
        "detail": detail,
    }


def _covered_dimension(dim: str, covered: int, total: int) -> dict:
    """由判定层**已算好的**覆盖数组装一个维度状态。"""
    covered = int(covered or 0)
    total = int(total or 0)
    required = total > 0
    ok = (not required) or covered >= total
    if dim == DIM_ENTITY:
        detail = (f"主体缺 {total - covered}/{total} 家（维度：主体）"
                  if not ok else f"主体齐备（{covered}/{total} 家）")
    elif dim == DIM_PERIOD:
        detail = (f"期间缺 {total - covered}/{total} 年（维度：期间）"
                  if not ok else f"期间齐备（{covered}/{total} 年）")
    elif dim == DIM_DOCTYPE:
        detail = (f"材料类型缺 {total - covered}/{total} 份（维度：材料类型）"
                  if not ok else f"材料类型齐备（{covered}/{total} 份）")
    else:
        detail = ("必备附件缺失（维度：必备附件）"
                  if not ok else f"必备附件齐备（{covered}/{total} 份）")
    return {
        "dimension": dim,
        "label": DIM_LABELS[dim],
        "required": required,
        "determinable": True,
        "covered": covered,
        "total": total,
        "expected": total,
        "ok": ok,
        "detail": detail if required else f"{NOT_REQUIRED}（维度：{DIM_LABELS[dim]}）",
    }


def build_completeness(obl: dict, cov: dict, available: int) -> dict:
    """五维齐套组装层。

    ``cov`` 由判定层传入，形如
    ``{"entity": {"covered": n, "total": m}, "period": {...}, ...}``
    —— **本模块不重算覆盖率**。
    """
    cov = cov or {}
    dims = [
        _covered_dimension(dim, (cov.get(dim) or {}).get("covered", 0),
                           (cov.get(dim) or {}).get("total", 0))
        for dim in (DIM_ENTITY, DIM_PERIOD, DIM_DOCTYPE, DIM_ATTACHMENT)
    ]
    dims.append(count_dimension(obl, available))
    missing = [d for d in dims if d["required"] and not d["ok"]]
    undeterminable = [d for d in dims if not d["determinable"]]
    return {
        "dimensions": dims,
        "by_dimension": {d["dimension"]: d for d in dims},
        "missing": missing,
        "undeterminable": undeterminable,
        "missing_labels": [d["label"] for d in missing],
        "undeterminable_labels": [d["label"] for d in undeterminable],
        "complete": not missing and not undeterminable,
    }


def completeness_summary(qc: dict) -> str:
    """把五维状态压成一行人可读摘要（写进状态记录与核对表）。"""
    if not qc:
        return ""
    parts = []
    for d in qc.get("dimensions", []):
        if not d.get("required"):
            continue
        mark = "齐备" if d.get("ok") else (
            "不可判定" if not d.get("determinable") else "缺")
        parts.append(f"{d.get('label')}：{mark}")
    return "；".join(parts)
