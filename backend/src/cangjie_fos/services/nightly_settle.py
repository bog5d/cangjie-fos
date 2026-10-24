"""夜间结算服务（Phase 3，v1.9.5 起仅保留偏好提取）。

每晚 2 点由 APScheduler 触发，逐租户执行**偏好提取**：
  pending review_diffs → investor_prefs（喂 Coach 注入，真实学习链路）。

历史说明：早期还顺带生成"夜间素材建议"写入 nightly_suggestions 表，但那套生成
逻辑一直是占位/启发式、前端 banner 长期为空，已于 v1.9.5 整条下线。偏好提取这条
真实链路保留。
"""
from __future__ import annotations

import structlog

from cangjie_fos.services.pitch_job_db import _connect

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


async def nightly_settle_for_tenant(tenant_id: str) -> int:
    """对单租户执行夜间偏好提取，返回提取到的偏好条数。"""
    log.info("nightly_settle_start", tenant_id=tenant_id)
    extracted = 0
    try:
        from cangjie_fos.services.evolution_extractor import run_preference_extraction  # noqa: PLC0415
        extracted = run_preference_extraction(tenant_id=tenant_id)
        log.info("nightly_pref_extracted", tenant_id=tenant_id, count=extracted)
    except (RuntimeError, OSError, ValueError) as exc:
        log.warning("nightly_pref_extraction_failed", tenant_id=tenant_id, error=str(exc))
    log.info("nightly_settle_done", tenant_id=tenant_id, extracted=extracted)
    return extracted


async def nightly_settle_all_tenants() -> None:
    """APScheduler cron 入口：遍历所有活跃租户执行夜间偏好提取。"""
    log.info("nightly_settle_all_start")
    try:
        tenant_ids = _list_active_tenant_ids()
    except Exception as exc:  # noqa: BLE001
        log.error("nightly_settle_list_tenants_failed", error=str(exc))
        return

    for tenant_id in tenant_ids:
        try:
            await nightly_settle_for_tenant(tenant_id)
        except (RuntimeError, OSError, ValueError) as exc:
            log.error("nightly_settle_tenant_failed", tenant_id=tenant_id, error=str(exc))

    log.info("nightly_settle_all_done", tenant_count=len(tenant_ids))
