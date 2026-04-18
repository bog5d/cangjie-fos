"""Phase 5：按 tenant 广播 WebSocket 消息（文件监听等线程安全投递）。"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

_main_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.RLock()
_tenant_ws: dict[str, list[Any]] = {}


def set_main_event_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    global _main_loop
    _main_loop = loop


def register_npc_ws(tenant_id: str, ws: Any) -> None:
    with _lock:
        _tenant_ws.setdefault(tenant_id, []).append(ws)


def unregister_npc_ws(tenant_id: str, ws: Any) -> None:
    with _lock:
        lst = _tenant_ws.get(tenant_id)
        if not lst:
            return
        try:
            lst.remove(ws)
        except ValueError:
            pass


async def broadcast_to_tenant(tenant_id: str, payload: dict[str, Any]) -> None:
    with _lock:
        targets = list(_tenant_ws.get(tenant_id, []))
    for ws in targets:
        try:
            await ws.send_json(payload)
        except Exception as e:  # noqa: BLE001
            logger.debug("npc_ws_send_failed tenant=%s err=%s", tenant_id, e)
            unregister_npc_ws(tenant_id, ws)


def schedule_broadcast_to_tenant(tenant_id: str, payload: dict[str, Any]) -> None:
    """供 watchdog 等非 asyncio 线程调用。"""
    loop = _main_loop
    if loop is None:
        logger.debug("npc_ws_no_loop skip_broadcast tenant=%s", tenant_id)
        return
    try:
        asyncio.run_coroutine_threadsafe(broadcast_to_tenant(tenant_id, payload), loop)
    except RuntimeError as e:
        logger.warning("npc_ws_schedule_failed: %s", e)
