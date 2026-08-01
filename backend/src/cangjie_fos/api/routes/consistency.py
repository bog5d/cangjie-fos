"""跨录音口径一致性对比 API（F1）。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from cangjie_fos.services.consistency_service import run_consistency_check

router = APIRouter(prefix="/api/v1/consistency", tags=["consistency"])


@router.get("/check")
def check_consistency(
    tenant_id: str = Query(..., description="租户 ID"),
    limit: int = Query(8, ge=1, le=30, description="回看最近多少场录音"),
    institution: str = Query("", description="只看某机构相关录音（可选）"),
) -> dict:
    """跨最近若干场路演/访谈录音做关键指标口径一致性对比。"""
    return run_consistency_check(tenant_id, limit=limit, institution_filter=institution)
