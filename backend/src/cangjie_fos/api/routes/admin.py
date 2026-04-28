"""管理员端点（调试用）。"""
from __future__ import annotations

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.post("/nightly-settle")
async def trigger_nightly_settle(tenant_id: str) -> dict:
    """立即执行单租户夜间结算，返回生成的建议数量。"""
    from cangjie_fos.services.nightly_settle import nightly_settle_for_tenant  # noqa: PLC0415

    count = await nightly_settle_for_tenant(tenant_id)
    return {"tenant_id": tenant_id, "suggested": count}


@router.get("/association-log")
def get_association_log(
    tenant_id: str = Query(..., description="租户ID"),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """返回最近的 material_match_history 记录，用于调试确认关联链路真实触发。

    返回字段：institution_id, matched_count（按 institution_id 聚合）, created_at（最新一条）
    """
    from cangjie_fos.services.pitch_job_db import _connect  # noqa: PLC0415

    conn = _connect()
    try:
        cur = conn.execute(
            """SELECT institution_id,
                      COUNT(*) as matched_count,
                      MAX(matched_at) as created_at
               FROM material_match_history
               WHERE institution_id = ?
               GROUP BY institution_id
               ORDER BY created_at DESC
               LIMIT ?""",
            (tenant_id, max(1, min(int(limit), 100))),
        )
        rows = [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()

    return {"tenant_id": tenant_id, "total": len(rows), "records": rows}
