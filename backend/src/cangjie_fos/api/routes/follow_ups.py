"""待跟进行动项 API（Phase 7 P1）

路由：
  GET  /api/v1/follow-ups?tenant_id=X            — 列出待跟进行动项（默认未完成）
  PATCH /api/v1/follow-ups/{item_id}/done        — 标记已完成
  GET  /api/v1/pitch/jobs/{job_id}/follow-ups    — 指定 job 的所有行动项
  GET  /api/v1/institutions/{name}/jobs          — 机构路演时间线（关联的 jobs 列表）
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from cangjie_fos.services.pitch_job_db import (
    db_follow_up_list,
    db_follow_up_list_by_job,
    db_follow_up_mark_done,
    db_job_get,
)

router = APIRouter(tags=["follow_ups"])
logger = logging.getLogger(__name__)


@router.get("/api/v1/follow-ups", summary="列出租户待跟进行动项")
def list_follow_ups(
    tenant_id: str = Query(..., description="租户 ID"),
    include_done: bool = Query(False, description="是否包含已完成"),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    return db_follow_up_list(tenant_id, limit=limit, include_done=include_done)


@router.patch("/api/v1/follow-ups/{item_id}/done", summary="标记行动项已完成")
def mark_done(item_id: str) -> dict[str, Any]:
    found = db_follow_up_mark_done(item_id)
    if not found:
        raise HTTPException(status_code=404, detail="follow_up item not found")
    return {"ok": True, "id": item_id}


@router.get(
    "/api/v1/pitch/jobs/{job_id}/follow-ups",
    summary="返回指定 job 的所有行动项（含已完成）",
)
def list_job_follow_ups(job_id: str) -> list[dict[str, Any]]:
    if not db_job_get(job_id):
        raise HTTPException(status_code=404, detail="job not found")
    return db_follow_up_list_by_job(job_id)


@router.get(
    "/api/v1/institutions/{name}/jobs",
    summary="机构路演时间线：按时间倒序返回该机构关联的 pitch_jobs",
)
def institution_job_timeline(name: str, limit: int = Query(20, ge=1, le=100)) -> list[dict[str, Any]]:
    """返回 institution_id = name 的 pitch_jobs，含 job_id / category / status / created_at。"""
    from cangjie_fos.services.pitch_job_db import _connect  # noqa: PLC0415

    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT job_id, tenant_id, category, status, created_at, interviewee, institution_id
            FROM pitch_jobs
            WHERE institution_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (name, limit),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
