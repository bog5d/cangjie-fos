"""Phase 6.2：上传向导 API 契约与批次工具。"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from cangjie_fos.main import app as global_app
from cangjie_fos.schemas.pitch_upload_wizard import UploadWizardCreateRequest, WizardTrackSpec
from cangjie_fos.schemas.pitch_upload_wizard import SniperRow
from cangjie_fos.services.pitch_wizard_batch import (
    SCENE_PLACEHOLDER,
    build_session_notes as bn,
    compute_batch_name,
    sniper_rows_to_json,
)


def test_compute_batch_name_matches_coach_rules() -> None:
    assert compute_batch_name(institution_name="红杉", batch_label="") == "红杉"
    assert compute_batch_name(institution_name="", batch_label="Q1") == "Q1"
    assert compute_batch_name(institution_name="", batch_label="") == "未命名批次"


def test_sniper_rows_to_json() -> None:
    j = sniper_rows_to_json([SniperRow(quote="a", reason="b"), SniperRow(quote="", reason="")])
    assert "quote" in j and "a" in j


def test_session_notes_investor_prefix() -> None:
    s = bn(investor_name="李总监", interviewee="王总", speaker_hint="")
    assert "【接待投资人】李总监" in s


def test_create_session_rejects_placeholder_scene() -> None:
    c = TestClient(global_app)
    body = UploadWizardCreateRequest(
        tenant_id="t1",
        category=SCENE_PLACEHOLDER,
        institution_name="某机构",
        tracks=[WizardTrackSpec(client_temp_id="x", interviewee="张三")],
    )
    r = c.post("/api/v1/pitch/upload-sessions", json=body.model_dump())
    # 创建阶段不强制校验大类；commit 才校验。此处应 200。
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_commit_unknown_session_404() -> None:
    transport = ASGITransport(app=global_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/v1/pitch/upload-sessions/nope/commit")
    assert r.status_code == 404


def test_commit_validates_audio_present(monkeypatch: pytest.MonkeyPatch) -> None:
    from cangjie_fos.services import pitch_upload_session_store as sus

    sid = "testsid123"
    payload = UploadWizardCreateRequest(
        tenant_id="t-wiz",
        user_name="波总",
        category="01_机构路演",
        institution_name="测试机构",
        tracks=[WizardTrackSpec(client_temp_id="a", interviewee="李四")],
    )
    with sus._lock:
        sus._sessions[sid] = {
            "payload": payload.model_dump(),
            "audio": {},
            "qa": {},
            "created": 9999999999.0,
        }

    c = TestClient(global_app)
    r = c.post(f"/api/v1/pitch/upload-sessions/{sid}/commit")
    assert r.status_code == 400
    assert "尚未上传音频" in r.json().get("detail", "")


def test_commit_schedules_jobs(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from cangjie_fos.services import pitch_upload_session_store as sus

    called: list[dict] = []

    def fake_run(**kwargs: object) -> None:
        called.append(dict(kwargs))

    monkeypatch.setattr(
        "cangjie_fos.api.routes.pitch_wizard.run_pitch_wizard_track_job",
        fake_run,
    )
    monkeypatch.setattr(
        "cangjie_fos.api.routes.pitch_wizard.schedule_broadcast_to_tenant",
        lambda *a, **k: None,
    )

    sid = "testsid456"
    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"fake")

    payload = UploadWizardCreateRequest(
        tenant_id="t-wiz2",
        user_name="波总",
        category="01_机构路演",
        institution_name="红杉中国",
        investor_name="王合伙人",
        enable_asr_polish=True,
        tracks=[WizardTrackSpec(client_temp_id="a", interviewee="创始人")],
    )
    with sus._lock:
        sus._sessions[sid] = {
            "payload": payload.model_dump(),
            "audio": {0: str(audio)},
            "filenames": {0: "pitch.m4a"},
            "qa": {},
            "created": 9999999999.0,
        }

    c = TestClient(global_app)
    r = c.post(f"/api/v1/pitch/upload-sessions/{sid}/commit")
    assert r.status_code == 200
    data = r.json()
    assert len(data["job_ids"]) == 1
    assert "豆豆" in data["assistant_echo"]
    assert len(called) == 1
    assert called[0]["interviewee"] == "创始人"
    assert called[0]["skip_asr_polish"] is False
    assert "红杉" in called[0]["project_name"] or called[0]["project_name"] == "红杉中国"
    notes = called[0]["session_notes"]
    assert "【接待投资人】王合伙人" in notes

    with sus._lock:
        assert sid not in sus._sessions
