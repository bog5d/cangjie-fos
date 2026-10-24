"""Tests for P1-A: html_report_path column schema migration (Phase 6.4).

All tests use tmp_path for isolated DB — same pattern as test_pitch_job_db.py.
"""
from __future__ import annotations

import pytest

import cangjie_fos.services.pitch_job_db as _module
from cangjie_fos.services.pitch_job_db import (
    _init_db,
    db_job_create,
    db_job_get,
    db_job_update,
)
import sqlite3


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


def test_html_report_path_column_exists():
    """Create a job, set html_report_path, retrieve and verify the value."""
    db_job_create("job-html-001", "tenant-X")
    db_job_update("job-html-001", html_report_path="/tmp/report.html")
    row = db_job_get("job-html-001")

    assert row is not None
    assert row["html_report_path"] == "/tmp/report.html"


def test_html_report_path_default_none():
    """html_report_path must be None when never set."""
    db_job_create("job-html-002", "tenant-X")
    row = db_job_get("job-html-002")

    assert row is not None
    assert row.get("html_report_path") is None


def test_migration_idempotent(tmp_path, monkeypatch):
    """Calling _init_db() twice must not raise and column must still work."""
    db_file = tmp_path / "idempotent.sqlite"
    monkeypatch.setattr(_module, "_db_path", lambda: str(db_file))

    # First init — creates table and adds column (or no-ops ALTER if new DDL already has it)
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    conn.close()

    # Second init — simulates app restart against an already-initialized DB
    conn2 = sqlite3.connect(str(db_file))
    conn2.row_factory = sqlite3.Row
    _init_db(conn2)  # must not raise
    conn2.close()

    # Column must still be functional
    db_job_create("job-html-003", "tenant-Y")
    db_job_update("job-html-003", html_report_path="/tmp/idempotent.html")
    row = db_job_get("job-html-003")

    assert row is not None
    assert row["html_report_path"] == "/tmp/idempotent.html"
