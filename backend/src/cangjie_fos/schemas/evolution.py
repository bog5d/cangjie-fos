"""自我进化：请求体与持久化记录（SPEC A6）。"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from cangjie_fos.schemas.tenant import TenantScoped


class EvolutionStatus(StrEnum):
    PENDING_REFLECTION = "pending_reflection"
    REFLECTED = "reflected"
    REJECTED = "rejected"


class TextDiffFeedbackRequest(TenantScoped):
    """用户提交定稿相对 AI 原文的反馈入口。"""

    ai_text: str = Field(..., description="模型原文")
    user_text: str = Field(..., description="用户定稿")
    trace_id: str | None = Field(None, description="可选链路追踪 id")
    memory_tag: str | None = Field(
        None,
        description="Executive Memory 桶名；缺省为 default，与 Pitch_Coach memory_engine 对齐",
    )


class EvolutionRecord(BaseModel):
    """旧逻辑 → 用户修正 → 候选新逻辑（候选字段预占位）。"""

    record_id: str
    tenant_id: str
    trace_id: str | None
    ai_text: str
    user_text: str
    diff_unified: str
    status: EvolutionStatus = EvolutionStatus.PENDING_REFLECTION
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    prior_logic_ref: str | None = None
    user_correction_summary: str | None = None
    candidate_new_logic: dict[str, Any] | None = None
    exp_delta: int = Field(
        default=0,
        description="前端 Exp HUD：错题本落盘奖励（Phase 3 事件总线）",
    )
