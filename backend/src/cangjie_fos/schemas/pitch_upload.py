"""音频上传任务（Phase 3 SPEC A2 / 任务 3.3）。"""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field  # noqa: TC002 — Field 用于 error 字段说明


class PitchJobStatus(StrEnum):
    PENDING = "pending"
    TRANSCRIBING = "transcribing"
    EVALUATING = "evaluating"
    COMPLETED = "completed"
    FAILED = "failed"


class PitchUploadAck(BaseModel):
    job_id: str
    status: PitchJobStatus = PitchJobStatus.PENDING
    exp_delta: int = 0
    exp_reason: str = ""


class PitchJobStatusResponse(BaseModel):
    job_id: str
    status: PitchJobStatus
    tenant_id: str
    created_at: float = 0.0
    exp_delta: int = 0
    exp_reason: str = ""
    report: dict | None = None
    error_summary: str | None = None
    error_detail: str | None = None
    error_code: str | None = None
    error: str | None = Field(
        default=None,
        description="兼容旧客户端；与 error_summary 同源（人话），禁止为 Raw JSON。",
    )


class PitchJobSummary(BaseModel):
    """列举接口轻量快照（不含完整 report，避免列表过大）。"""

    job_id: str
    status: PitchJobStatus
    tenant_id: str
    created_at: float = 0.0
    exp_delta: int = 0
    exp_reason: str = ""
    error_summary: str | None = None
    error_detail: str | None = None
    error_code: str | None = None
    error: str | None = Field(default=None, description="兼容字段，同 error_summary")
    has_report: bool = False


class PitchReviewResponse(BaseModel):
    job_id: str
    status: PitchJobStatus
    original_report: dict | None = None
    edited_report: dict | None = None
    committed_at: float | None = None
    words_total: int = 0
    audio_available: bool = False


class PitchReviewCommitRequest(BaseModel):
    edited_report: dict


class PitchReviewCommitResponse(BaseModel):
    job_id: str
    committed_at: float
