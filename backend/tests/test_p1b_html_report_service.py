"""Tests for html_report_service.generate_job_html_report (Task P1-B).

All tests are fully mocked — zero real FFmpeg calls, zero real file I/O.
Legacy modules (schema, report_builder) are injected into sys.modules before
the service module is imported so that lazy imports inside the function work.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixture: inject fake legacy modules into sys.modules, reload service module
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_legacy_modules():
    """Ensure schema and report_builder exist in sys.modules before each test."""
    mock_schema = MagicMock()
    mock_report_builder = MagicMock()
    sys.modules["schema"] = mock_schema
    sys.modules["report_builder"] = mock_report_builder

    # Force-reload the service so it picks up clean state each test
    import cangjie_fos.services.html_report_service as svc_mod
    importlib.reload(svc_mod)

    yield mock_schema, mock_report_builder

    sys.modules.pop("schema", None)
    sys.modules.pop("report_builder", None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_WORDS = [
    {"word_index": 0, "text": "Hello", "start_time": 0.0, "end_time": 0.5, "speaker_id": "A"}
]

_SAMPLE_REPORT = {"title": "Test Report", "score": 80}

_SAMPLE_AUDIO = "/fake/audio.m4a"


def _make_row(
    *,
    original_report=None,
    edited_report=None,
    words_json=None,
    audio_path=_SAMPLE_AUDIO,
):
    return {
        "job_id": "job1",
        "tenant_id": "t1",
        "status": "done",
        "original_report": original_report,
        "edited_report": edited_report,
        "words_json": words_json if words_json is not None else _SAMPLE_WORDS,
        "audio_path": audio_path,
    }


def _get_svc():
    """Return freshly-reloaded service module."""
    import cangjie_fos.services.html_report_service as svc_mod
    return svc_mod


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGenerateJobHtmlReport:

    def test_generates_html_for_completed_job(self, mock_legacy_modules, tmp_path):
        mock_schema, mock_report_builder = mock_legacy_modules
        fake_output = tmp_path / "job1.html"
        mock_report_builder.generate_html_report.return_value = fake_output

        row = _make_row(original_report=_SAMPLE_REPORT)
        svc = _get_svc()

        with (
            patch.object(svc, "db_job_get", return_value=row),
            patch.object(svc, "db_job_update") as mock_update,
            patch.object(svc, "ensure_pitch_coach_runtime"),
            patch.object(svc, "get_backend_root", return_value=tmp_path),
            patch("pathlib.Path.is_file", return_value=True),
        ):
            result = svc.generate_job_html_report("job1")

        mock_report_builder.generate_html_report.assert_called_once()
        mock_update.assert_called_once()
        _, kwargs = mock_update.call_args
        assert "html_report_path" in kwargs
        assert result  # truthy

    def test_uses_edited_report_when_committed(self, mock_legacy_modules, tmp_path):
        mock_schema, mock_report_builder = mock_legacy_modules
        fake_output = tmp_path / "job1.html"
        mock_report_builder.generate_html_report.return_value = fake_output

        edited = {"title": "Edited Report", "score": 90}
        original = {"title": "Original Report", "score": 70}
        row = _make_row(original_report=original, edited_report=edited)
        svc = _get_svc()

        with (
            patch.object(svc, "db_job_get", return_value=row),
            patch.object(svc, "db_job_update"),
            patch.object(svc, "ensure_pitch_coach_runtime"),
            patch.object(svc, "get_backend_root", return_value=tmp_path),
            patch("pathlib.Path.is_file", return_value=True),
        ):
            svc.generate_job_html_report("job1")

        # AnalysisReport.model_validate should have been called with edited_report contents
        mock_schema.AnalysisReport.model_validate.assert_called_once_with(edited)

    def test_raises_value_error_when_job_not_found(self, mock_legacy_modules):
        svc = _get_svc()

        with patch.object(svc, "db_job_get", return_value=None):
            with pytest.raises(ValueError, match="not found"):
                svc.generate_job_html_report("missing-job")

    def test_raises_value_error_when_no_report(self, mock_legacy_modules):
        row = _make_row(original_report=None, edited_report=None)
        svc = _get_svc()

        with patch.object(svc, "db_job_get", return_value=row):
            with pytest.raises(ValueError, match="no report data"):
                svc.generate_job_html_report("job1")

    def test_raises_value_error_when_no_words(self, mock_legacy_modules):
        row = _make_row(original_report=_SAMPLE_REPORT, words_json=[])
        svc = _get_svc()

        with patch.object(svc, "db_job_get", return_value=row):
            with pytest.raises(ValueError, match="no transcription words"):
                svc.generate_job_html_report("job1")

    def test_raises_file_not_found_when_no_audio(self, mock_legacy_modules):
        row = _make_row(original_report=_SAMPLE_REPORT, audio_path=None)
        svc = _get_svc()

        with patch.object(svc, "db_job_get", return_value=row):
            with pytest.raises(FileNotFoundError, match="Audio file not found"):
                svc.generate_job_html_report("job1")

    def test_raises_file_not_found_when_audio_missing_from_disk(self, mock_legacy_modules):
        # Use a path that genuinely does not exist on disk — no mock needed for is_file
        row = _make_row(
            original_report=_SAMPLE_REPORT,
            audio_path="/nonexistent/path/audio.m4a",
        )
        svc = _get_svc()

        with patch.object(svc, "db_job_get", return_value=row):
            with pytest.raises(FileNotFoundError, match="Audio file not found"):
                svc.generate_job_html_report("job1")
