"""夜间自动进化结算服务（Phase 3）。

每晚2点由 APScheduler 触发，逐租户执行：
1. 偏好提取（pending review_diffs → investor_prefs）
2. 规则性素材建议生成
3. 写入 nightly_suggestions 表供豆豆次日注入
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from typing import Any

import structlog

from cangjie_fos.services.pitch_job_db import (
    _connect,
    _write_lock,
    db_nightly_suggestion_insert,
)

log = structlog.get_logger(__name__)


def _list_active_tenant_ids() -> list[str]:
    """返回 pitch_jobs 中所有有 completed 状态记录的 tenant_id（去重）。"""
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT DISTINCT tenant_id FROM pitch_jobs WHERE status = 'completed'"
        )
        return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def _generate_material_suggestions(tenant_id: str) -> list[dict[str, Any]]:
    """规则性生成素材建议，不调用 LLM。"""
    conn = _connect()
    try:
        # 近30天 completed 任务数
        cutoff = time.time() - 30 * 86400
        cur = conn.execute(
            "SELECT COUNT(*) FROM pitch_jobs WHERE tenant_id = ? AND status = 'completed' AND created_at >= ?",
            (tenant_id, cutoff),
        )
        recent_count: int = cur.fetchone()[0]

        # 高使用率素材 top-3
        cur2 = conn.execute(
            "SELECT asset_filename, usage_count, contribution_score FROM material_contributions "
            "ORDER BY usage_count DESC LIMIT 3"
        )
        top_materials = [dict(zip(["asset_filename", "usage_count", "contribution_score"], row)) for row in cur2.fetchall()]
    finally:
        conn.close()

    suggestions: list[dict[str, Any]] = []

    if recent_count > 0:
        suggestions.append({
            "type": "material_update",
            "content": f"过去30天完成 {recent_count} 次路演评估，建议复盘高频风险点并更新对应素材。",
            "priority": 5,
        })

    for mat in top_materials:
        if mat["usage_count"] >= 3 and mat["contribution_score"] < 1.0:
            suggestions.append({
                "type": "material_update",
                "content": f"素材「{mat['asset_filename']}」已被引用 {mat['usage_count']} 次但贡献分偏低（{mat['contribution_score']:.1f}），建议更新内容。",
                "asset_id": mat["asset_filename"],
                "priority": 5,
            })

    return suggestions


async def nightly_settle_for_tenant(tenant_id: str) -> int:
    """对单租户执行夜间结算，返回写入建议条数。"""
    log.info("nightly_settle_start", tenant_id=tenant_id)
    count = 0

    # Step 1: 偏好提取
    try:
        from cangjie_fos.services.evolution_extractor import run_preference_extraction  # noqa: PLC0415
        extracted = run_preference_extraction(tenant_id=tenant_id)
        log.info("nightly_pref_extracted", tenant_id=tenant_id, count=extracted)
    except Exception as exc:
        log.warning("nightly_pref_extraction_failed", tenant_id=tenant_id, error=str(exc))

    # Step 2: 生成素材建议
    try:
        suggestions = _generate_material_suggestions(tenant_id)
    except Exception as exc:
        log.warning("nightly_material_suggestions_failed", tenant_id=tenant_id, error=str(exc))
        suggestions = []

    # Step 3: 写入 nightly_suggestions 表
    for s in suggestions:
        try:
            db_nightly_suggestion_insert(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                type=s["type"],
                content=s["content"],
                asset_id=s.get("asset_id"),
                priority=s.get("priority", 5),
            )
            count += 1
        except Exception as exc:
            log.warning("nightly_suggestion_insert_failed", error=str(exc))

    log.info("nightly_settle_done", tenant_id=tenant_id, suggested=count)
    return count


async def nightly_settle_all_tenants() -> None:
    """APScheduler cron 入口：遍历所有活跃租户执行夜间结算。"""
    log.info("nightly_settle_all_start")
    try:
        tenant_ids = _list_active_tenant_ids()
    except Exception as exc:
        log.error("nightly_settle_list_tenants_failed", error=str(exc))
        return

    for tenant_id in tenant_ids:
        try:
            await nightly_settle_for_tenant(tenant_id)
        except Exception as exc:
            log.error("nightly_settle_tenant_failed", tenant_id=tenant_id, error=str(exc))

    log.info("nightly_settle_all_done", tenant_count=len(tenant_ids))
