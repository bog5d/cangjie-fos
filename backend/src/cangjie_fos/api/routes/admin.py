"""管理员端点（调试用）。"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.post("/nightly-settle")
async def trigger_nightly_settle(tenant_id: str) -> dict:
    """立即执行单租户夜间结算，返回生成的建议数量。"""
    from cangjie_fos.services.nightly_settle import nightly_settle_for_tenant  # noqa: PLC0415

    count = await nightly_settle_for_tenant(tenant_id)
    return {"tenant_id": tenant_id, "suggested": count}
