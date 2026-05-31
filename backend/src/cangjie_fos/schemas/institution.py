"""Phase 6：机构画像与 Pipeline 阶段（CRM）。"""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class PipelineStage(StrEnum):
    """机构在融资 Pipeline 中的阶段。"""

    TARGETED = "targeted"
    PITCHED = "pitched"
    DD = "dd"
    TERM_SHEET = "term_sheet"


class InstitutionThermal(StrEnum):
    COLD = "cold"
    WARM = "warm"
    HOT = "hot"


class InstitutionProfile(BaseModel):
    """机构实体（持久化行映射）。"""

    institution_id: str = Field(..., min_length=8)
    tenant_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, description="机构常用名，如 红杉资本")
    stage: PipelineStage = PipelineStage.PITCHED
    thermal: InstitutionThermal = InstitutionThermal.WARM
    preferences: str = Field("", description="投资偏好摘要")
    concerns: str = Field("", description="核心疑虑 / 追问焦点")
    ai_summary: str = Field("", description="综合画像一句话")
    updated_at: float = 0.0
    source_trace_id: str | None = None
    # CRM 扩展字段（v1.2.0）
    contact_name: str = Field("", description="主要联系人姓名")
    contact_title: str = Field("", description="联系人职位")
    valuation: str = Field("", description="估值描述，如「2亿」")
    deal_size: str = Field("", description="目标融资规模，如「3000万」")
    probability: int = Field(0, ge=0, le=100, description="成功概率 0-100")
    legal_status: str = Field("", description="法务进度备注")


class InstitutionProfileCreate(BaseModel):
    tenant_id: str
    name: str
    stage: PipelineStage = PipelineStage.PITCHED
    thermal: InstitutionThermal = InstitutionThermal.WARM
    preferences: str = ""
    concerns: str = ""
    ai_summary: str = ""
    source_trace_id: str | None = None
    contact_name: str = ""
    contact_title: str = ""
    valuation: str = ""
    deal_size: str = ""
    probability: int = 0
    legal_status: str = ""


class InstitutionProfileUpdate(BaseModel):
    """PATCH 请求体：只传需要更新的字段，None = 不修改。"""

    name: str | None = None
    stage: PipelineStage | None = None
    thermal: InstitutionThermal | None = None
    preferences: str | None = None
    concerns: str | None = None
    ai_summary: str | None = None
    contact_name: str | None = None
    contact_title: str | None = None
    valuation: str | None = None
    deal_size: str | None = None
    probability: int | None = None
    legal_status: str | None = None


class PipelineCountsResponse(BaseModel):
    tenant_id: str
    counts: dict[str, int]
    total: int
