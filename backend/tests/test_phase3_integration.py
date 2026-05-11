"""Phase 3：大盘、对话、上传任务、错题本 Exp 字段（HTTP 契约 + Mock）。"""
from __future__ import annotations

from io import BytesIO
from unittest.mock import patch

from starlette.testclient import TestClient

from cangjie_fos.main import app
from cangjie_fos.schemas.pitch_upload import PitchJobStatus
from cangjie_fos.services.pitch_job_store import job_update


def test_dashboard_status_contract() -> None:
    c = TestClient(app)
    r = c.get("/api/dashboard/status", params={"tenant_id": "t3"})
    assert r.status_code == 200
    j = r.json()
    assert j["tenant_id"] == "t3"
    assert "funnel" in j
    assert "docs_health_pct" in j
    assert "data_room_completeness_pct" in j


def test_pitch_chat_mocked_graph() -> None:
    with patch(
        "cangjie_fos.api.routes.pitch.invoke_npc_chat",
        return_value=("mock-reply-phase3", "trace-mock-1", "thread-mock-1"),
    ):
        c = TestClient(app)
        r = c.post(
            "/api/pitch/chat",
            json={"tenant_id": "t1", "message": "红杉问了什么？"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] == "mock-reply-phase3"
    assert body["trace_id"] == "trace-mock-1"
    assert body["exp_delta"] == 12
    assert body["graph_invoked"] is True


def _instant_complete_job(*, job_id: str, filename: str, tenant_id: str, raw_bytes: bytes | None = None, pre_written_path=None) -> None:
    job_update(
        job_id,
        status=PitchJobStatus.COMPLETED,
        report={"total_score": 91, "scene_analysis": {"scene_type": "ut", "speaker_roles": "x"}},
        exp_delta=40,
        exp_reason="录音解析并完成 LangGraph 复盘",
    )


def test_pitch_upload_and_job_poll_mock_pipeline() -> None:
    with patch(
        "cangjie_fos.api.routes.pitch.run_pitch_upload_job",
        side_effect=_instant_complete_job,
    ):
        c = TestClient(app)
        r = c.post(
            "/api/pitch/upload",
            data={"tenant_id": "tenant-x"},
            files={"file": ("a.mp3", BytesIO(b"\x00\x01fake"), "audio/mpeg")},
        )
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    st = c.get(f"/api/pitch/jobs/{job_id}")
    assert st.status_code == 200
    body = st.json()
    assert body["status"] == "completed"
    assert body["exp_delta"] == 40
    assert isinstance(body.get("created_at"), (int, float))
    assert body["created_at"] > 0

    listed = c.get("/api/pitch/jobs", params={"tenant_id": "tenant-x", "limit": 10})
    assert listed.status_code == 200
    rows = listed.json()
    assert any(r["job_id"] == job_id for r in rows)
    hit = next(r for r in rows if r["job_id"] == job_id)
    assert hit["has_report"] is True
    assert hit["status"] == "completed"
    assert "error_summary" in hit
    assert hit.get("error_summary") in (None, "")


def test_pitch_job_list_empty_tenant() -> None:
    c = TestClient(app)
    r = c.get("/api/pitch/jobs", params={"tenant_id": "no-such-tenant-xyz", "limit": 5})
    assert r.status_code == 200
    assert r.json() == []


def test_pitch_upload_rejects_empty() -> None:
    c = TestClient(app)
    r = c.post(
        "/api/pitch/upload",
        data={"tenant_id": "t"},
        files={"file": ("empty.mp3", BytesIO(b""), "audio/mpeg")},
    )
    assert r.status_code == 400


def test_cors_allows_vite_origin_on_dashboard() -> None:
    c = TestClient(app)
    r = c.get(
        "/api/dashboard/status",
        params={"tenant_id": "cors-t"},
        headers={"Origin": "http://127.0.0.1:5173"},
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"
