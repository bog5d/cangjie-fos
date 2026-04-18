"""战局地图 / 融资漏斗响应契约（Phase 2 SPEC A3；数据源为 Pipeline 聚合）。"""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class FunnelStageKey(StrEnum):
    MATERIALS = "materials"
    TEASER = "teaser"
    PARTNER_MEET = "partner_meet"
    TERM_SHEET = "term_sheet"
    CLOSING = "closing"


class FunnelStage(BaseModel):
    key: FunnelStageKey
    title: str
    subtitle: str
    progress_pct: int = Field(..., ge=0, le=100)
    status: str = Field(..., description="pending | active | done")


class WarRoomFunnelResponse(BaseModel):
    tenant_id: str
    round_name: str = "Series A"
    headline: str
    stages: list[FunnelStage]
    momentum_score: int = Field(..., ge=0, le=100)
