"""战局大盘 HTTP 入口（Phase 3 SPEC A3）。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from cangjie_fos.schemas.dashboard import DashboardStatusResponse
from cangjie_fos.services.dashboard_status import build_dashboard_status

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/status", response_model=DashboardStatusResponse)
def get_dashboard_status(tenant_id: str = Query(..., min_length=1)) -> DashboardStatusResponse:
    return build_dashboard_status(tenant_id=tenant_id)
