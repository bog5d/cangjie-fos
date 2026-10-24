"""NPC 文本对话（Phase 3 SPEC A1 / 任务 3.2）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class PitchChatRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1, description="用户输入")
    session_id: str | None = None
    thread_id: str | None = Field(None, description="不传则新建线程；传则续写 LangGraph checkpoint")
    user_name: str | None = Field(None, description="当前指挥官展示名，注入 System Prompt")
    active_job_id: str | None = None


class PitchChatResponse(BaseModel):
    reply: str
    trace_id: str
    thread_id: str
    graph_invoked: bool = True
    exp_delta: int = 0
    exp_reason: str = ""


class PitchThreadSummary(BaseModel):
    thread_id: str
    tenant_id: str
    preview: str | None
    updated_at: float


class PitchThreadMessagesResponse(BaseModel):
    thread_id: str
    messages: list[dict[str, str]]
