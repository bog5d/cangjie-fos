"""Tests for POST /api/pitch/jobs/{job_id}/html-report endpoint (Task P1-C)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from cangjie_fos.main import app
from cangjie_fos.schemas.pitch_upload import PitchHtmlReportResponse

client = TestClient(app)

MOCK_TARGET = "cangjie_fos.api.routes.pitch.generate_job_html_report"


def test_post_html_report_success() -> None:
    with patch(MOCK_TARGET, return_value=Path("/data/html_reports/job1.html")):
        resp = client.post("/api/pitch/jobs/job1/html-report")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == "job1"
    assert isinstance(data["html_path"], str) and len(data["html_path"]) > 0
    assert isinstance(data["generated_at"], float) and data["generated_at"] > 0


def test_post_html_report_404_job_not_found() -> None:
    with patch(MOCK_TARGET, side_effect=ValueError("Job not found: job1")):
        resp = client.post("/api/pitch/jobs/job1/html-report")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_post_html_report_404_audio_missing() -> None:
    with patch(MOCK_TARGET, side_effect=FileNotFoundError("Audio file not found")):
        resp = client.post("/api/pitch/jobs/job1/html-report")
    assert resp.status_code == 404


def test_post_html_report_500_generation_failed() -> None:
    with patch(MOCK_TARGET, side_effect=RuntimeError("FFmpeg exploded")):
        resp = client.post("/api/pitch/jobs/job1/html-report")
    assert resp.status_code == 500
    assert "failed" in resp.json()["detail"].lower()


def test_html_report_response_schema() -> None:
    obj = PitchHtmlReportResponse(job_id="x", html_path="/tmp/x.html", generated_at=1234.0)
    assert obj.job_id == "x"
    assert obj.html_path == "/tmp/x.html"
    assert obj.generated_at == 1234.0
