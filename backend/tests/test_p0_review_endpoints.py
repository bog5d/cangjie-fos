"""Tests for Phase 6.4 Task 3 — HITL Review API endpoints.

All DB calls are mocked. No real SQLite is touched.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from cangjie_fos.main import app

client = TestClient(app)

_JOB_ID = "review-job-abc123"

_FULL_ROW = {
    "job_id": _JOB_ID,
    "tenant_id": "tenant-test",
    "status": "completed",
    "created_at": 1_700_000_000.0,
    "original_report": {"score": 80, "notes": "original"},
    "edited_report": {"score": 85, "notes": "edited"},
    "words_json": [{"text": "hello"}, {"text": "world"}],
    "audio_path": None,
    "committed_at": 1_700_000_100.0,
    "exp_delta": 10,
    "exp_reason": "good job",
    "error_summary": None,
    "error_detail": None,
    "error_code": None,
    "report": {"score": 85, "notes": "edited"},
}


# ---------------------------------------------------------------------------
# GET /api/pitch/jobs/{job_id}/review
# ---------------------------------------------------------------------------


def test_get_review_returns_both_reports():
    with patch("cangjie_fos.api.routes.pitch.db_job_get", return_value=_FULL_ROW):
        resp = client.get(f"/api/pitch/jobs/{_JOB_ID}/review")
    assert resp.status_code == 200
    data = resp.json()
    assert data["original_report"] == {"score": 80, "notes": "original"}
    assert data["edited_report"] == {"score": 85, "notes": "edited"}
    assert data["job_id"] == _JOB_ID
    assert data["words_total"] == 2


def test_get_review_404_unknown_job():
    with patch("cangjie_fos.api.routes.pitch.db_job_get", return_value=None):
        resp = client.get(f"/api/pitch/jobs/nonexistent/review")
    assert resp.status_code == 404


def test_get_review_audio_available_true():
    with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as tmp:
        tmp_path = tmp.name

    row = {**_FULL_ROW, "audio_path": tmp_path}
    try:
        with patch("cangjie_fos.api.routes.pitch.db_job_get", return_value=row):
            resp = client.get(f"/api/pitch/jobs/{_JOB_ID}/review")
        assert resp.status_code == 200
        assert resp.json()["audio_available"] is True
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_get_review_audio_available_false():
    row = {**_FULL_ROW, "audio_path": "/nonexistent/path.m4a"}
    with patch("cangjie_fos.api.routes.pitch.db_job_get", return_value=row):
        resp = client.get(f"/api/pitch/jobs/{_JOB_ID}/review")
    assert resp.status_code == 200
    assert resp.json()["audio_available"] is False


# ---------------------------------------------------------------------------
# PATCH /api/pitch/jobs/{job_id}/review
# ---------------------------------------------------------------------------


def test_patch_review_commits_edited_report():
    with (
        patch("cangjie_fos.api.routes.pitch.db_job_get", return_value=_FULL_ROW),
        patch("cangjie_fos.api.routes.pitch.db_job_update") as mock_update,
    ):
        resp = client.patch(
            f"/api/pitch/jobs/{_JOB_ID}/review",
            json={"edited_report": {"score": 90, "notes": "human-edited"}},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == _JOB_ID
    assert isinstance(data["committed_at"], float)
    assert data["committed_at"] > 0

    mock_update.assert_called_once()
    call_kwargs = mock_update.call_args
    assert call_kwargs.args[0] == _JOB_ID
    assert call_kwargs.kwargs["edited_report"] == {"score": 90, "notes": "human-edited"}


def test_patch_review_404_unknown():
    with patch("cangjie_fos.api.routes.pitch.db_job_get", return_value=None):
        resp = client.patch(
            f"/api/pitch/jobs/nonexistent/review",
            json={"edited_report": {"score": 90}},
        )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/pitch/jobs/{job_id}/words
# ---------------------------------------------------------------------------


def test_get_words_returns_list():
    with patch("cangjie_fos.api.routes.pitch.db_job_get", return_value=_FULL_ROW):
        resp = client.get(f"/api/pitch/jobs/{_JOB_ID}/words")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["text"] == "hello"


def test_get_words_404_unknown():
    with patch("cangjie_fos.api.routes.pitch.db_job_get", return_value=None):
        resp = client.get(f"/api/pitch/jobs/nonexistent/words")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/pitch/jobs/{job_id}/audio
# ---------------------------------------------------------------------------


def test_get_audio_404_no_audio_path():
    row = {**_FULL_ROW, "audio_path": None}
    with patch("cangjie_fos.api.routes.pitch.db_job_get", return_value=row):
        resp = client.get(f"/api/pitch/jobs/{_JOB_ID}/audio")
    assert resp.status_code == 404
    assert "audio not available" in resp.json()["detail"]
