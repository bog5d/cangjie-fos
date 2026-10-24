"""战局地图 API：漏斗与 Dashboard 同源（Pipeline 聚合）。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from cangjie_fos.schemas.war_room import WarRoomFunnelResponse
from cangjie_fos.services.pipeline_funnel import build_funnel_from_institutions

router = APIRouter(prefix="/api/war-room", tags=["war-room"])


@router.get("/funnel", response_model=WarRoomFunnelResponse)
def get_war_room_funnel(tenant_id: str = Query(..., min_length=1)) -> WarRoomFunnelResponse:
    return build_funnel_from_institutions(tenant_id=tenant_id)
