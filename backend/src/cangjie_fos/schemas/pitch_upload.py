"""音频上传任务（Phase 3 SPEC A2 / 任务 3.3）。"""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field  # noqa: TC002 — Field 用于 error 字段说明


class PitchJobStatus(StrEnum):
    PENDING = "pending"
    TRANSCRIBING = "transcribing"
    # 路演分析专属状态：ASR完成后暂停，等待用户确认说话人身份
    AWAITING_SPEAKERS = "awaiting_speakers"
    # 路演分析专属状态：用户确认说话人后，恢复LangGraph评估
    RESUMING_ANALYSIS = "resuming_analysis"
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
    warnings: dict | None = Field(
        default=None,
        description="非致命告警，如机构情报抽取失败。不影响报告生成。",
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
    has_words_json: bool = Field(default=False, description="SQLite 中有 words_json，可重跑评估")
    warnings: dict | None = None
    substatus: str | None = Field(default=None, description="流水线子步骤进度文本，active 状态时展示")
    participants_confirmed: bool = Field(default=False, description="参与人身份已完成确认")
    interviewee: str | None = Field(default=None, description="被访谈人/路演标识")
    category: str | None = Field(default=None, description="业务场景大类")


class WordsSummary(BaseModel):
    total_words: int = 0
    duration_sec: float = 0.0


class PitchReviewResponse(BaseModel):
    job_id: str
    status: PitchJobStatus
    original_report: dict | None = None
    edited_report: dict | None = None
    committed_at: float | None = None
    words_summary: WordsSummary = WordsSummary()
    audio_available: bool = False
    interviewee: str | None = Field(
        default=None,
        description="上传向导填写的被访谈人；简单上传无此项",
    )


class PitchReviewCommitRequest(BaseModel):
    edited_report: dict


class PitchReviewCommitResponse(BaseModel):
    job_id: str
    committed_at: float


class PitchHtmlReportResponse(BaseModel):
    job_id: str
    html_path: str
    generated_at: float
