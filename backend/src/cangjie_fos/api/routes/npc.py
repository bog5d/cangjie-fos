"""主动 NPC：WebSocket + 长轮询占位（Phase 2 SPEC A4/A5 预留）。"""
from __future__ import annotations

from fastapi import APIRouter, Query, WebSocket
from starlette.websockets import WebSocketDisconnect

from cangjie_fos.events.npc_ws_house import register_npc_ws, unregister_npc_ws
from cangjie_fos.services.npc_queue import line_by_index, peek_lines_after

router = APIRouter(prefix="/api", tags=["npc"])


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
