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


# ── /api/dashboard/live 战情地图 ──────────────────────────────────────────────

def test_live_intel_returns_correct_shape():
    """GET /api/dashboard/live 应返回三个 key 且结构正确。"""
    c = TestClient(app)
    r = c.get("/api/dashboard/live", params={"tenant_id": "t-live-test"})
    assert r.status_code == 200
    body = r.json()
    assert "pipeline_counts" in body
    assert "recent_roadshows" in body
    assert "pending_followups" in body
    assert isinstance(body["pipeline_counts"], list)
    assert isinstance(body["recent_roadshows"], list)
    assert isinstance(body["pending_followups"], list)


def test_live_intel_pipeline_counts_structure(monkeypatch):
    """pipeline_counts 每条应有 stage / label / count 三个字段。"""
    from cangjie_fos.services import institution_store

    monkeypatch.setattr(
        institution_store,
        "count_by_stage",
        lambda *, tenant_id: {"dd": 2, "term_sheet": 1, "targeted": 0, "pitched": 3},
    )
    c = TestClient(app)
    r = c.get("/api/dashboard/live", params={"tenant_id": "t1"})
    assert r.status_code == 200
    counts = r.json()["pipeline_counts"]
    # targeted=0 应被过滤掉
    stages = {c["stage"] for c in counts}
    assert "targeted" not in stages
    assert "dd" in stages
    for entry in counts:
        assert "stage" in entry
        assert "label" in entry
        assert "count" in entry


def test_live_intel_recent_roadshows_structure(monkeypatch):
    """recent_roadshows 每条应有 institution / status / date 字段。"""
    from cangjie_fos.services import pitch_job_db

    fake_jobs = [
        ("job1", {
            "institution_id": "红杉资本",
            "status": "completed",
            "created_at": 1716825600.0,
            "exp_delta": 3,
            "interviewee": "张总",
        }),
    ]
    monkeypatch.setattr(
        pitch_job_db,
        "db_job_list_for_tenant",
        lambda tenant_id, limit: fake_jobs,
    )
    c = TestClient(app)
    r = c.get("/api/dashboard/live", params={"tenant_id": "t1"})
    roadshows = r.json()["recent_roadshows"]
    assert len(roadshows) == 1
    assert roadshows[0]["institution"] == "红杉资本"
    assert roadshows[0]["status"] == "completed"
    assert roadshows[0]["exp_delta"] == 3
    assert "date" in roadshows[0]


def test_live_intel_pending_followups_structure(monkeypatch):
    """pending_followups 每条应有 actor / action / priority / institution 字段。"""
    from cangjie_fos.services import pitch_job_db

    fake_items = [
        {
            "id": "item1",
            "actor": "我方",
            "action": "发送尽调清单",
            "priority": "high",
            "institution_id": "红杉资本",
        },
    ]
    monkeypatch.setattr(
        pitch_job_db,
        "db_follow_up_list",
        lambda tenant_id, limit, include_done: fake_items,
    )
    c = TestClient(app)
    r = c.get("/api/dashboard/live", params={"tenant_id": "t1"})
    followups = r.json()["pending_followups"]
    assert len(followups) == 1
    assert followups[0]["action"] == "发送尽调清单"
    assert followups[0]["priority"] == "high"
    assert followups[0]["institution"] == "红杉资本"
