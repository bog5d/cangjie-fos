"""TDD tests for pitch_job_db.py — SQLite persistence layer (Phase 6.4 Task 1).

All tests use tmp_path so they never touch data/pitch_jobs.sqlite.
"""
from __future__ import annotations

import time

import pytest

import cangjie_fos.services.pitch_job_db as _module
from cangjie_fos.services.pitch_job_db import (
    db_job_create,
    db_job_get,
    db_job_list_for_tenant,
    db_job_update,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch, tmp_path):
    """Redirect DB path to a fresh tmp_path for every test."""
    db_file = tmp_path / "pitch_jobs.sqlite"

    monkeypatch.setattr(_module, "_db_path", lambda: str(db_file))
    yield


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_and_get_round_trip():
    """Create a job and retrieve it; all base fields must be present."""
    db_job_create("job-001", "tenant-A")
    row = db_job_get("job-001")

    assert row is not None
    assert row["job_id"] == "job-001"
    assert row["tenant_id"] == "tenant-A"
    assert row["status"] == "pending"
    assert isinstance(row["created_at"], float)
    assert row["created_at"] > 0


def test_get_returns_none_for_unknown_job():
    """db_job_get must return None for a job_id that was never created."""
    result = db_job_get("does-not-exist")
    assert result is None


def test_update_status():
    """db_job_update should change the status field."""
    db_job_create("job-002", "tenant-A")
    db_job_update("job-002", status="transcribing")
    row = db_job_get("job-002")

    assert row is not None
    assert row["status"] == "transcribing"


def test_update_original_report_dict_serialized_back_to_dict():
    """Passing a dict for original_report stores JSON and returns a dict."""
    report = {"score": 88, "feedback": "Good structure"}
    db_job_create("job-003", "tenant-A")
    db_job_update("job-003", original_report=report)
    row = db_job_get("job-003")

    assert row is not None
    assert isinstance(row["original_report"], dict)
    assert row["original_report"]["score"] == 88
    assert row["original_report"]["feedback"] == "Good structure"


def test_update_edited_report_does_not_affect_original_report():
    """Updating edited_report leaves original_report unchanged."""
    original = {"score": 75, "feedback": "Needs improvement"}
    edited = {"score": 80, "feedback": "Better after edit"}

    db_job_create("job-004", "tenant-A")
    db_job_update("job-004", original_report=original)
    db_job_update("job-004", edited_report=edited)
    row = db_job_get("job-004")

    assert row is not None
    assert row["original_report"]["score"] == 75
    assert row["edited_report"]["score"] == 80


def test_report_alias_only_original_set():
    """When only original_report is set, report == original_report."""
    original = {"score": 70}
    db_job_create("job-005", "tenant-A")
    db_job_update("job-005", original_report=original)
    row = db_job_get("job-005")

    assert row is not None
    assert row["edited_report"] is None
    assert row["report"] == row["original_report"]
    assert row["report"]["score"] == 70


def test_report_alias_with_edited_report_set():
    """When edited_report is set, report == edited_report (not original)."""
    original = {"score": 65}
    edited = {"score": 90}

    db_job_create("job-006", "tenant-A")
    db_job_update("job-006", original_report=original, edited_report=edited)
    row = db_job_get("job-006")

    assert row is not None
    assert row["report"] == row["edited_report"]
    assert row["report"]["score"] == 90


def test_list_for_tenant_ordering_newest_first():
    """db_job_list_for_tenant must return jobs sorted by created_at DESC."""
    db_job_create("job-old", "tenant-B")
    time.sleep(0.01)  # ensure distinct timestamps
    db_job_create("job-new", "tenant-B")

    results = db_job_list_for_tenant("tenant-B")
    assert len(results) == 2
    job_ids = [jid for jid, _ in results]
    assert job_ids[0] == "job-new"
    assert job_ids[1] == "job-old"


def test_list_for_tenant_isolates_tenants():
    """Jobs from other tenants must not appear in the list."""
    db_job_create("job-t1", "tenant-1")
    db_job_create("job-t2", "tenant-2")

    results = db_job_list_for_tenant("tenant-1")
    assert len(results) == 1
    assert results[0][0] == "job-t1"


def test_words_json_round_trip():
    """words_json stored as list → JSON → returns as list."""
    words = [{"word": "hello", "start": 0.0, "end": 0.5}, {"word": "world", "start": 0.6, "end": 1.0}]
    db_job_create("job-007", "tenant-A")
    db_job_update("job-007", words_json=words)
    row = db_job_get("job-007")

    assert row is not None
    assert isinstance(row["words_json"], list)
    assert len(row["words_json"]) == 2
    assert row["words_json"][0]["word"] == "hello"


def test_audio_path_storage():
    """audio_path should be stored and retrieved as a plain string."""
    db_job_create("job-008", "tenant-A")
    db_job_update("job-008", audio_path="/tmp/uploads/audio_abc.wav")
    row = db_job_get("job-008")

    assert row is not None
    assert row["audio_path"] == "/tmp/uploads/audio_abc.wav"


def test_create_with_extra_kwargs():
    """db_job_create accepts status, exp_delta, exp_reason via **extra."""
    db_job_create("job-009", "tenant-A", status="evaluating", exp_delta=10, exp_reason="bonus")
    row = db_job_get("job-009")

    assert row is not None
    assert row["status"] == "evaluating"
    assert row["exp_delta"] == 10
    assert row["exp_reason"] == "bonus"


def test_list_for_tenant_returns_dicts():
    """Each item returned by list_for_tenant is a (str, dict) tuple."""
    db_job_create("job-010", "tenant-C")
    results = db_job_list_for_tenant("tenant-C")

    assert len(results) == 1
    job_id, row = results[0]
    assert isinstance(job_id, str)
    assert isinstance(row, dict)
    assert "report" in row  # alias key must be present


def test_update_ignores_unknown_kwargs():
    """db_job_update must silently ignore kwargs not in _WRITABLE_COLS."""
    db_job_create("job-011", "tenant-A")
    # This should not raise even though 'unknown_field' is not a column
    db_job_update("job-011", status="completed", unknown_field="ignored")
    row = db_job_get("job-011")
    assert row is not None
    assert row["status"] == "completed"
