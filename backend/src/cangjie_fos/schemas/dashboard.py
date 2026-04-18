"""GET /api/dashboard/status 契约（Phase 3 SPEC A3）。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from cangjie_fos.schemas.war_room import WarRoomFunnelResponse


class DashboardStatusResponse(BaseModel):
    tenant_id: str
    funnel: WarRoomFunnelResponse
    docs_health_pct: int = Field(..., ge=0, le=100, description="资料健康度")
    data_room_completeness_pct: int = Field(
        ...,
        ge=0,
        le=100,
        description="数据室完成度（与漏斗独立维度）",
    )
    headline: str = ""
    exp_hint: str = Field(default="", description="前端可展示的 Exp 提示文案")
