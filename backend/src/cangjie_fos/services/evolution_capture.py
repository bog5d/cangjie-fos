"""进化飞轮：捕获审查台 commit 时的 original vs edited diff。

调用方式：在 PATCH /jobs/{job_id}/review 成功后调用 capture_review_diff()。
diff_summary 结构（稳定契约，extractor 依赖此格式）：
{
    "score_delta": int,           # edited.total_score - original.total_score
    "risk_points_added": [...],   # edited 有、original 没有的风险点
    "risk_points_removed": [...], # original 有、edited 没有的风险点
    "risk_points_changed": [      # 两边都有但内容不同
        {"original": {...}, "edited": {...}}
    ],
    "highlights_added": [...],
    "highlights_removed": [...],
}
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def _risk_key(rp: dict) -> str:
    """稳定 key：用 original_text 或 start/end word_index 标识同一条风险点。"""
    return rp.get("original_text", "") or f"{rp.get('start_word_index')}_{rp.get('end_word_index')}"


def _extract_risk_keywords(report: dict[str, Any]) -> list[str]:
    """从报告的 risk_points 提取关键词（original_text / category / type）。"""
    keywords: list[str] = []
    for rp in report.get("risk_points") or []:
        for field in ("original_text", "category", "type", "description"):
            val = rp.get(field)
            if val and isinstance(val, str) and val.strip():
                keywords.append(val.strip())
    return keywords


def compute_diff_summary(
    original: dict[str, Any] | None,
    edited: dict[str, Any],
) -> dict[str, Any]:
    """计算 original_report 与 edited_report 之间的结构化差异。"""
    if not original:
        return {
            "score_delta": 0,
            "risk_points_added": edited.get("risk_points", []),
            "risk_points_removed": [],
            "risk_points_changed": [],
            "highlights_added": edited.get("positive_highlights", []),
            "highlights_removed": [],
        }

    orig_score = original.get("total_score", 0) or 0
    edit_score = edited.get("total_score", 0) or 0

    orig_rps: dict[str, dict] = {
        _risk_key(rp): rp for rp in (original.get("risk_points") or [])
    }
    edit_rps: dict[str, dict] = {
        _risk_key(rp): rp for rp in (edited.get("risk_points") or [])
    }

    added = [rp for k, rp in edit_rps.items() if k not in orig_rps]
    removed = [rp for k, rp in orig_rps.items() if k not in edit_rps]
    changed = [
        {"original": orig_rps[k], "edited": rp}
        for k, rp in edit_rps.items()
        if k in orig_rps and rp != orig_rps[k]
    ]

    orig_hl = set(original.get("positive_highlights") or [])
    edit_hl = set(edited.get("positive_highlights") or [])

    return {
        "score_delta": edit_score - orig_score,
        "risk_points_added": added,
        "risk_points_removed": removed,
        "risk_points_changed": changed,
        "highlights_added": list(edit_hl - orig_hl),
        "highlights_removed": list(orig_hl - edit_hl),
    }


def capture_review_diff(
    *,
    job_id: str,
    tenant_id: str,
    committed_at: float,
    original_report: dict[str, Any] | None,
    edited_report: dict[str, Any],
) -> int:
    """计算 diff 并持久化到 review_diffs 表。返回 diff id。

    同时触发全链路数据关联：
    1. 提取 edited 报告中的风险点关键词 → 找相关素材
    2. 记录素材使用（material_contributions usage_count +1）
    """
    from cangjie_fos.services.pitch_job_db import (  # noqa: PLC0415
        db_diff_insert,
        db_assets_search_by_keywords,
        db_material_contribution_bulk_upsert,
    )

    diff_summary = compute_diff_summary(original_report, edited_report)
    diff_id = db_diff_insert(
        job_id=job_id,
        tenant_id=tenant_id,
        committed_at=committed_at,
        original_report=original_report,
        edited_report=edited_report,
        diff_summary=diff_summary,
    )
    logger.info(
        "evolution_diff_captured job_id=%s diff_id=%s score_delta=%s",
        job_id,
        diff_id,
        diff_summary["score_delta"],
    )

    # Phase 4: 全链路数据关联
    try:
        keywords = _extract_risk_keywords(edited_report)
        if keywords:
            matched_assets = db_assets_search_by_keywords(tenant_id, keywords)
            if matched_assets:
                asset_ids = [a["asset_filename"] for a in matched_assets]
                db_material_contribution_bulk_upsert(tenant_id, asset_ids, action="review_use")
                logger.info(
                    "phase4_association_triggered job_id=%s matched_assets=%d",
                    job_id,
                    len(matched_assets),
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("phase4_association_failed job_id=%s error=%s", job_id, exc)

    return diff_id
