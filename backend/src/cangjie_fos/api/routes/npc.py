"""主动 NPC：WebSocket + 长轮询 + 群聊情报摄入。"""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query, WebSocket
from starlette.websockets import WebSocketDisconnect

from cangjie_fos.events.npc_ws_house import register_npc_ws, unregister_npc_ws
from cangjie_fos.services.npc_queue import line_by_index, peek_lines_after

router = APIRouter(prefix="/api", tags=["npc"])


@router.post("/v1/npc/ingest-chat-log", summary="从粘贴的群聊记录中提取融资情报入库")
def ingest_chat_log(
    raw_text: str = Body(..., embed=True, description="原始聊天记录全文"),
    tenant_id: str = Body(..., embed=True, description="租户 ID"),
    persist: bool = Body(True, embed=True, description="是否写入数据库"),
) -> dict:
    """
    接受粘贴的原始群聊记录（含时间戳、人名、表情等噪声），
    调用 LLM 提取机构进展更新和行动项，并可选择性写入数据库。
    """
    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="raw_text 不能为空")
    if not tenant_id.strip():
        raise HTTPException(status_code=400, detail="tenant_id 不能为空")

    from cangjie_fos.services.chat_log_ingestor import ingest_chat_log as _ingest
    return _ingest(raw_text, tenant_id=tenant_id, persist=persist)


@router.post("/v1/npc/proactive-interview", summary="手动触发反向访谈（立即扫描停滞机构）")
def trigger_proactive_interview(
    tenant_id: str = Body(..., embed=True, description="租户 ID"),
) -> dict:
    """
    手动触发一次反向访谈扫描。
    正常由 APScheduler 每天 18:00 自动运行，此端点供手动测试和紧急触发使用。
    """
    from cangjie_fos.services.proactive_interviewer import run_proactive_interview
    return run_proactive_interview(tenant_id=tenant_id)


@router.get("/npc/poll")
def npc_poll(cursor: int = Query(0, ge=0)) -> dict:
    lines, next_cursor = peek_lines_after(cursor)
    return {
        "lines": [
            {"id": ln.id, "role": ln.role, "text": ln.text, "proactive": ln.proactive}
            for ln in lines
        ],
        "next_cursor": next_cursor,
    }


@router.websocket("/ws/npc")
async def npc_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    tenant_id = websocket.query_params.get("tenant_id") or "default"
    register_npc_ws(tenant_id, websocket)
    try:
        await websocket.send_json(
            {
                "type": "hello",
                "tenant_id": tenant_id,
                "message": "仓颉 FOS · 豆豆已上线（WebSocket）",
            }
        )
        for i in range(3):
            ln = line_by_index(i)
            if ln:
                await websocket.send_json(
                    {
                        "type": "npc_prompt",
                        "proactive": ln.proactive,
                        "role": ln.role,
                        "text": ln.text,
                    }
                )
                if i == 0:
                    await websocket.send_json(
                        {
                            "type": "score_delta",
                            "delta": 10,
                            "reason": "资料补齐",
                        }
                    )
        while True:
            await websocket.receive_text()
            await websocket.send_json({"type": "ack", "echo": True})
    except WebSocketDisconnect:
        return
    finally:
        unregister_npc_ws(tenant_id, websocket)
