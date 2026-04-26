"""进化飞轮：从 review_diffs 提炼投资人偏好，写入 investor_prefs。

当前实现：纯结构化启发式规则（无需 LLM），可后续替换为 LangGraph 节点。
外部触发方式（两种）：
  1. PATCH commit 后延迟调用（BackgroundTasks）
  2. 定时批处理（future: APScheduler / celery beat）
"""
from __future__ import annotations

import logging
from typing import Any

from cangjie_fos.services.pitch_job_db import (
    db_diff_list_pending,
    db_diff_mark_extracted,
    db_pref_insert,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 启发式规则提炼
# ---------------------------------------------------------------------------

def _extract_prefs_from_diff(diff: dict[str, Any]) -> list[dict[str, Any]]:
    """从单条 diff_summary 提炼 0~N 条偏好信号。"""
    summary: dict = diff.get("diff_summary") or {}
    prefs: list[dict] = []

    # 1. 评分偏好：审查人持续上调/下调 LLM 分数
    score_delta = summary.get("score_delta", 0)
    if abs(score_delta) >= 3:
        prefs.append({
            "pref_type": "score_bias",
            "pref_key": "score_adjustment_direction",
            "pref_value": {"delta": score_delta, "direction": "up" if score_delta > 0 else "down"},
        })

    # 2. 风险点增删：审查人倾向于增加/删除风险点
    added_count = len(summary.get("risk_points_added", []))
    removed_count = len(summary.get("risk_points_removed", []))
    if added_count > 0:
        prefs.append({
            "pref_type": "risk_calibration",
            "pref_key": "tends_to_add_risk_points",
            "pref_value": {"count": added_count, "samples": [
                rp.get("tier1_general_critique", "")[:80]
                for rp in summary.get("risk_points_added", [])[:3]
            ]},
        })
    if removed_count > 0:
        prefs.append({
            "pref_type": "risk_calibration",
            "pref_key": "tends_to_remove_risk_points",
            "pref_value": {"count": removed_count},
        })

    # 3. 风险等级调整：审查人将「一般」改为「严重」等
    for change in summary.get("risk_points_changed", []):
        orig_lvl = (change.get("original") or {}).get("risk_level", "")
        edit_lvl = (change.get("edited") or {}).get("risk_level", "")
        if orig_lvl and edit_lvl and orig_lvl != edit_lvl:
            prefs.append({
                "pref_type": "risk_level_adjustment",
                "pref_key": f"upgrade_{orig_lvl}_to_{edit_lvl}",
                "pref_value": {"from": orig_lvl, "to": edit_lvl},
            })

    return prefs


# ---------------------------------------------------------------------------
# 公开入口
# ---------------------------------------------------------------------------

def run_preference_extraction(*, tenant_id: str | None = None, limit: int = 50) -> int:
    """批量处理 pending diffs，返回处理条数。

    Args:
        tenant_id: 若指定则只处理该租户（未实现，当前处理所有 pending）。
        limit: 单次最多处理条数，防止单次运行过长。
    """
    pending = db_diff_list_pending(limit=limit)
    processed = 0
    for diff in pending:
        try:
            prefs = _extract_prefs_from_diff(diff)
            for pref in prefs:
                db_pref_insert(
                    tenant_id=diff["tenant_id"],
                    pref_type=pref["pref_type"],
                    pref_key=pref["pref_key"],
                    pref_value=pref["pref_value"],
                    source_job_id=diff["job_id"],
                    source_diff_id=diff["id"],
                )
            db_diff_mark_extracted(diff["id"])
            processed += 1
            logger.info(
                "evolution_pref_extracted diff_id=%s prefs=%d", diff["id"], len(prefs)
            )
        except Exception:  # noqa: BLE001
            logger.exception("evolution_pref_extraction_failed diff_id=%s", diff.get("id"))
    return processed
