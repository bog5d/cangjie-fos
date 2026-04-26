from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from cangjie_fos.main import app


@pytest.mark.asyncio
async def test_health_ok() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_pitch_health_ok() -> None:
    from fastapi.testclient import TestClient
    from cangjie_fos.main import create_app
    client = TestClient(create_app())
    r = client.get("/api/pitch/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] in ("ok", "degraded")
    assert "issues" in data
