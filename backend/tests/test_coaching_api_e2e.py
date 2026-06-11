"""需求01 — 教练 & 审问 API E2E（全 mock：ASR + LLM）。"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from cangjie_fos.main import create_app
from cangjie_fos.services import coach_keypoint_service as kp_svc
from cangjie_fos.services import coach_score_service as score_svc
from cangjie_fos.services import coach_session_service as sess_svc
from cangjie_fos.services import qa_examiner_service as ex
from cangjie_fos.services import qa_grader_service as gr


@pytest.fixture()
def client():
    return TestClient(create_app(), raise_server_exceptions=False)


def _word(text, start, end, idx=0):
    return {"word_index": idx, "text": text, "start_time": start, "end_time": end, "speaker_id": "0"}


@pytest.fixture()
def patched(monkeypatch):
    monkeypatch.setattr(kp_svc, "_llm_extract_keypoints_chunk", lambda chunk: [
        {"page_no": 1, "point_text": "SaaS 订阅模式", "weight": "core"},
        {"page_no": 1, "point_text": "30 家客户", "weight": "normal"},
    ])
    monkeypatch.setattr(sess_svc, "_transcribe", lambda path: [_word("我们做SaaS订阅有30家客户", 0.0, 45.0, 0)])
    monkeypatch.setattr(score_svc, "_llm_judge_coverage", lambda kp, t: {
        "1": {"status": "covered"}, "2": {"status": "covered"},
    })


# ── 教练链路 ──────────────────────────────────────────────────

def test_create_session_via_text(client, patched):
    r = client.post("/api/v1/coaching/sessions", data={
        "bp_text": "第一页：我们做 SaaS……", "tenant_id": "zt", "title": "A轮",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    assert data["session_id"]


def test_create_session_empty_400(client, patched):
    r = client.post("/api/v1/coaching/sessions", data={"bp_text": "  ", "tenant_id": "zt"})
    assert r.status_code == 400


def test_full_coaching_flow(client, patched):
    """建会话 → 提交录音 → 查进步曲线。"""
    sid = client.post("/api/v1/coaching/sessions", data={
        "bp_text": "BP……", "tenant_id": "zt",
    }).json()["session_id"]

    audio = io.BytesIO(b"RIFF....fake wav data")
    r = client.post(
        f"/api/v1/coaching/sessions/{sid}/rounds",
        files={"file": ("take1.wav", audio, "audio/wav")},
    )
    assert r.status_code == 200
    report = r.json()
    assert report["coverage_score"] == 100.0
    assert report["round_no"] == 1
    assert report["duration_sec"] == 45.0

    # 进步曲线
    pc = client.get(f"/api/v1/coaching/sessions/{sid}/progress")
    assert pc.status_code == 200
    assert len(pc.json()["rounds"]) == 1


def test_rounds_unknown_session_404(client, patched):
    audio = io.BytesIO(b"fake")
    r = client.post(
        "/api/v1/coaching/sessions/nope/rounds",
        files={"file": ("a.wav", audio, "audio/wav")},
    )
    assert r.status_code == 404


def test_get_session_404(client):
    assert client.get("/api/v1/coaching/sessions/nope").status_code == 404


# ── 审问链路 ──────────────────────────────────────────────────

def test_generate_questions(client, monkeypatch):
    monkeypatch.setattr(ex, "_llm_generate_questions", lambda m, s, r: [
        {"category": "财务", "question_text": "毛利率为何低？", "answer_points": ["规模效应"]},
    ])
    r = client.post("/api/v1/coaching/qa/questions", json={
        "material": "公司材料……", "tenant_id": "zt", "sector": "AI",
    })
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_generate_questions_empty_400(client, monkeypatch):
    monkeypatch.setattr(ex, "_llm_generate_questions", lambda m, s, r: [])
    r = client.post("/api/v1/coaching/qa/questions", json={"material": "x", "tenant_id": "zt"})
    assert r.status_code == 400


def test_grade_answer_and_persist(client, monkeypatch):
    monkeypatch.setattr(gr, "_llm_grade", lambda q, ap, t: {
        "score": 75, "hit_points": ["规模效应"], "missed_points": [],
        "logic_flaws": [], "risk_statements": [], "feedback": "尚可",
    })
    r = client.post("/api/v1/coaching/qa/grade", json={
        "question": "毛利率为何低？", "answer_points": ["规模效应"],
        "transcript": "因为规模效应", "tenant_id": "zt", "sector": "AI", "persist": True,
    })
    assert r.status_code == 200
    assert r.json()["score"] == 75.0
    # 已沉淀进库
    from cangjie_fos.services.db_base import _connect
    with _connect() as conn:
        n = conn.execute("SELECT COUNT(*) FROM qa_question_bank WHERE tenant_id = 'zt'").fetchone()[0]
    assert n == 1
