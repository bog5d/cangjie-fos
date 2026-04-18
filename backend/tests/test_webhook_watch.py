from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from cangjie_fos.main import app


@pytest.mark.asyncio
async def test_webhook_accepts_tenant() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/webhooks/ingest",
            json={"tenant_id": "acme", "event_type": "ping"},
        )
    assert r.status_code == 200
    assert r.json()["accepted"] is True


@pytest.mark.asyncio
async def test_watch_status_shape() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/watch/status")
    assert r.status_code == 200
    assert "watchdog_running" in r.json()
