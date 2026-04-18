"""Phase 2：战局 API、LangGraph 桥接、NPC 通道、静态挂载（SPEC + TODO_LIST）。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from cangjie_fos.main import app as global_app
from cangjie_fos.main import create_app


def test_war_room_funnel_pipeline_contract() -> None:
    """与 /api/dashboard/status 内 funnel 同源：WarRoomFunnelResponse 结构契约。"""
    c = TestClient(global_app)
    r = c.get("/api/war-room/funnel", params={"tenant_id": "acme"})
    assert r.status_code == 200
    data = r.json()
    assert data["tenant_id"] == "acme"
    assert len(data["stages"]) >= 5
    assert data["momentum_score"] >= 0


def test_pitch_run_dry_run_no_pitch_coach() -> None:
    c = TestClient(global_app)
    r = c.post(
        "/api/pitch/run",
        json={
            "tenant_id": "t1",
            "dry_run": True,
            "words": [
                {
                    "word_index": 0,
                    "text": "x",
                    "start_time": 0.0,
                    "end_time": 0.1,
                    "speaker_id": "S1",
                }
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    assert body["report"]["total_score"] == 88


def test_pitch_run_invokes_langgraph_when_not_dry_run() -> None:
    mock_report = MagicMock()
    mock_report.model_dump.return_value = {"scene_analysis": {}, "total_score": 99}

    with patch(
        "cangjie_fos.api.routes.pitch.PitchGraphService.run_evaluation_with_state",
        return_value=(mock_report, {"k": 1}),
    ) as m:
        c = TestClient(global_app)
        r = c.post(
            "/api/pitch/run",
            json={
                "tenant_id": "t1",
                "dry_run": False,
                "words": [
                    {
                        "word_index": 0,
                        "text": "x",
                        "start_time": 0.0,
                        "end_time": 0.1,
                        "speaker_id": "S1",
                    }
                ],
            },
        )
    assert r.status_code == 200
    m.assert_called_once()
    assert r.json()["dry_run"] is False
    assert r.json()["report"]["total_score"] == 99


def test_npc_poll_returns_lines() -> None:
    c = TestClient(global_app)
    r = c.get("/api/npc/poll", params={"cursor": 0})
    assert r.status_code == 200
    j = r.json()
    assert "lines" in j and "next_cursor" in j
    assert isinstance(j["lines"], list)


def test_npc_websocket_handshake() -> None:
    c = TestClient(global_app)
    with c.websocket_connect("/api/ws/npc?tenant_id=boss") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        assert hello["tenant_id"] == "boss"
        msg = ws.receive_json()
        assert msg["type"] == "npc_prompt"


@pytest.mark.asyncio
async def test_root_serves_built_spa_when_dist_present(monkeypatch, tmp_path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        "<!doctype html><html><body>CJSPA</body></html>",
        encoding="utf-8",
    )
    monkeypatch.setattr("cangjie_fos.main.get_frontend_dist_dir", lambda: dist)
    fresh = create_app()
    transport = ASGITransport(app=fresh)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get("/")
    assert r.status_code == 200
    assert b"CJSPA" in r.content
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        h = await ac.get("/health")
    assert h.status_code == 200
