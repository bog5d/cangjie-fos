"""POST /api/pitch/run 请求体（与 Pitch_Coach TranscriptionWord 对齐）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class PitchWordIn(BaseModel):
    word_index: int
    text: str
    start_time: float
    end_time: float
    speaker_id: str


class PitchRunRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    words: list[PitchWordIn] = Field(..., min_length=1)
    dry_run: bool = False
    model_choice: str = "deepseek"
    explicit_context: dict | None = None
    qa_text: str = ""
    company_background: str = ""
    trace_id: str | None = None
