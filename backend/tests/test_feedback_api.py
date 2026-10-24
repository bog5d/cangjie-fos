from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from cangjie_fos.main import app


@pytest.mark.asyncio
async def test_text_diff_persists_pending_reflection(tmp_path) -> None:
    from cangjie_fos.services.evolution_store import EvolutionJsonStore

    store = EvolutionJsonStore(base=tmp_path)

    from cangjie_fos.api.routes import feedback as fb

    app.dependency_overrides[fb.get_store] = lambda: store
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/api/v1/feedback/text-diff",
                json={
                    "tenant_id": "t1",
                    "trace_id": "tr-1",
                    "ai_text": "hello\n",
                    "user_text": "world\n",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    data = r.json()
    assert data["tenant_id"] == "t1"
    assert data["status"] == "pending_reflection"
    assert data.get("exp_delta") == 18
    assert "record_id" in data
    f = tmp_path / "t1" / f"{data['record_id']}.json"
    assert f.is_file()
    disk = json.loads(f.read_text(encoding="utf-8"))
    assert disk["diff_unified"]


@pytest.mark.asyncio
async def test_feedback_text_diff_invokes_capture_after_persist(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """persist 成功后必须调用 coach_memory_bridge（失败不阻主路径；此处 spy 断言调用一次）。"""
    from cangjie_fos.services.evolution_store import EvolutionJsonStore

    store = EvolutionJsonStore(base=tmp_path)
    calls: list[dict] = []

    def spy(**kwargs: object) -> None:
        calls.append(dict(kwargs))

    from cangjie_fos.api.routes import feedback as fb

    monkeypatch.setattr(fb, "try_capture_diff_to_executive_memory", spy)
    app.dependency_overrides[fb.get_store] = lambda: store
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/api/v1/feedback/text-diff",
                json={
                    "tenant_id": "t-cap",
                    "trace_id": "tr-cap",
                    "ai_text": "a\n",
                    "user_text": "b\n",
                    "memory_tag": "  custom  ",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert len(calls) == 1
    assert calls[0]["tenant_id"] == "t-cap"
    assert calls[0]["ai_text"] == "a\n"
    assert calls[0]["user_text"] == "b\n"
    assert calls[0]["tag"] == "custom"
