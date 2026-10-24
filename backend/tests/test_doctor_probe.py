"""Tests for GET /api/v1/doctor — 系统诊断探针端点。"""
from __future__ import annotations

import cangjie_fos.services.pitch_job_db as _db_module
import pytest
from fastapi.testclient import TestClient

from cangjie_fos.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch, tmp_path):
    db_file = tmp_path / "pitch_jobs.sqlite"
    monkeypatch.setattr(_db_module, "_db_path", lambda: str(db_file))
    yield


def test_doctor_returns_200():
    resp = client.get("/api/v1/doctor")
    assert resp.status_code == 200


def test_doctor_required_fields_present():
    data = client.get("/api/v1/doctor").json()
    required = {
        "python_version",
        "ffmpeg_available",
        "data_dir_writable",
        "port_8000_self",
        "db_writable",
        "issues",
        "fix_suggestions",
    }
    assert required.issubset(data.keys())


def test_doctor_python_version_nonempty():
    data = client.get("/api/v1/doctor").json()
    assert isinstance(data["python_version"], str)
    assert len(data["python_version"]) > 0


def test_doctor_ffmpeg_available_is_bool():
    data = client.get("/api/v1/doctor").json()
    assert isinstance(data["ffmpeg_available"], bool)


def test_doctor_db_writable_is_true():
    """测试环境应该可以写 SQLite。"""
    data = client.get("/api/v1/doctor").json()
    assert data["db_writable"] is True


def test_doctor_port_8000_self_is_true():
    """能响应说明端口 OK。"""
    data = client.get("/api/v1/doctor").json()
    assert data["port_8000_self"] is True


def test_doctor_issues_is_list():
    data = client.get("/api/v1/doctor").json()
    assert isinstance(data["issues"], list)


def test_doctor_fix_suggestions_is_list():
    data = client.get("/api/v1/doctor").json()
    assert isinstance(data["fix_suggestions"], list)


def test_doctor_issues_and_suggestions_same_length():
    data = client.get("/api/v1/doctor").json()
    assert len(data["issues"]) == len(data["fix_suggestions"])
