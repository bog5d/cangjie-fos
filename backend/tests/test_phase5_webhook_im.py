"""Phase 5：IM Webhook -> LangGraph NPC。"""
from __future__ import annotations

from unittest.mock import patch

from httpx import ASGITransport, AsyncClient

from cangjie_fos.main import app


async def test_webhooks_im_invokes_npc() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "cangjie_fos.api.routes.webhooks.invoke_npc_chat",
            return_value=("模拟回复", "tr1", "th1"),
        ) as m:
            r = await client.post(
                "/api/v1/webhooks/im",
                json={"tenant_id": "acme", "text": "帮我总结风险", "thread_id": "abc"},
            )
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is True
    assert body["reply"] == "模拟回复"
    assert body["thread_id"] == "th1"
    m.assert_called_once_with(tenant_id="acme", user_message="帮我总结风险", thread_id="abc")


async def test_webhooks_im_rejects_unknown_agent() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/webhooks/im",
            json={"tenant_id": "acme", "text": "x", "agent": "other"},
        )
    assert r.status_code == 200
    assert r.json()["accepted"] is False
