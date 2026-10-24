"""Webhook 感官骨架（SPEC A3）+ Phase 5 IM 路由。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from fastapi import APIRouter

from cangjie_fos.services.npc_chat_graph import invoke_npc_chat

router = APIRouter()


class WebhookIngestBody(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    event_type: str | None = None
    payload: dict | None = None


class WebhookImBody(BaseModel):
    """外部 IM 模拟：文本驱动 NPC LangGraph。"""

    tenant_id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1, description="用户指令正文")
    thread_id: str | None = Field(None, description="续写同一线程；空则新建")
    channel: str | None = Field(None, description="来源标记，如 telegram / wechat_stub")
    agent: str = Field("npc", description="子智能体：当前仅支持 npc")


@router.post("/webhooks/ingest")
def ingest_webhook(body: WebhookIngestBody) -> dict[str, str | bool]:
    return {"accepted": True, "tenant_id": body.tenant_id}


@router.post("/webhooks/im")
def ingest_im(body: WebhookImBody) -> dict[str, str | bool]:
    if body.agent != "npc":
        return {"accepted": False, "error": f"unknown_agent:{body.agent}"}
    reply, trace_id, thread_id = invoke_npc_chat(
        tenant_id=body.tenant_id,
        user_message=body.text,
        thread_id=body.thread_id,
    )
    return {
        "accepted": True,
        "tenant_id": body.tenant_id,
        "channel": body.channel or "",
        "reply": reply,
        "trace_id": trace_id,
        "thread_id": thread_id,
    }
