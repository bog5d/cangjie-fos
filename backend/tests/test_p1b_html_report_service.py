"""Tests for html_report_service.generate_job_html_report.

All tests fully mocked — zero real FFmpeg / disk I/O.
After Phase-1 engine/ migration, the service imports directly from
cangjie_fos.engine.schema and cangjie_fos.engine.report_builder, so we
patch those instead of injecting bare names into sys.modules.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_WORDS = [
    {"word_index": 0, "text": "Hello", "start_time": 0.0, "end_time": 0.5, "speaker_id": "A"}
]
_SAMPLE_REPORT = {"title": "Test Report", "score": 80}
_SAMPLE_AUDIO = "/fake/audio.m4a"


def _make_row(*, original_report=None, edited_report=None, words_json=None, audio_path=_SAMPLE_AUDIO):
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
    import cangjie_fos.services.html_report_service as svc_mod
    return svc_mod


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGenerateJobHtmlReport:

    def test_generates_html_for_completed_job(self, tmp_path):
        fake_output = tmp_path / "job1.html"
        fake_output.touch()
        svc = _get_svc()

        with (
            patch.object(svc, "db_job_get", return_value=_make_row(original_report=_SAMPLE_REPORT)),
            patch.object(svc, "db_job_update") as mock_update,
            patch.object(svc, "get_backend_root", return_value=tmp_path),
            patch("pathlib.Path.is_file", return_value=True),
            patch("cangjie_fos.engine.report_builder.generate_html_report", return_value=fake_output),
            patch("cangjie_fos.engine.schema.AnalysisReport.model_validate", return_value=MagicMock()),
            patch("cangjie_fos.engine.schema.TranscriptionWord.model_validate", return_value=MagicMock()),
        ):
            result = svc.generate_job_html_report("job1")

        mock_update.assert_called_once()
        _, kwargs = mock_update.call_args
        assert "html_report_path" in kwargs
        assert result  # truthy

    def test_uses_edited_report_when_committed(self, tmp_path):
        fake_output = tmp_path / "job1.html"
        fake_output.touch()
        edited = {"title": "Edited Report", "score": 90}
        original = {"title": "Original Report", "score": 70}
        svc = _get_svc()
        mock_ar = MagicMock()

        with (
            patch.object(svc, "db_job_get", return_value=_make_row(original_report=original, edited_report=edited)),
            patch.object(svc, "db_job_update"),
            patch.object(svc, "get_backend_root", return_value=tmp_path),
            patch("pathlib.Path.is_file", return_value=True),
            patch("cangjie_fos.engine.report_builder.generate_html_report", return_value=fake_output),
            patch("cangjie_fos.engine.schema.AnalysisReport.model_validate", return_value=mock_ar) as mock_ar_validate,
            patch("cangjie_fos.engine.schema.TranscriptionWord.model_validate", return_value=MagicMock()),
        ):
            svc.generate_job_html_report("job1")

        # Should be called with edited_report contents, not original
        mock_ar_validate.assert_called_once_with(edited)

    def test_raises_value_error_when_job_not_found(self):
        svc = _get_svc()
        with patch.object(svc, "db_job_get", return_value=None):
            with pytest.raises(ValueError, match="not found"):
                svc.generate_job_html_report("missing-job")

    def test_raises_value_error_when_no_report(self):
        row = _make_row(original_report=None, edited_report=None)
        svc = _get_svc()
        with patch.object(svc, "db_job_get", return_value=row):
            with pytest.raises(ValueError, match="no report data"):
                svc.generate_job_html_report("job1")

    def test_raises_value_error_when_no_words(self):
        row = _make_row(original_report=_SAMPLE_REPORT, words_json=[])
        svc = _get_svc()
        with patch.object(svc, "db_job_get", return_value=row):
            with pytest.raises(ValueError, match="no transcription words"):
                svc.generate_job_html_report("job1")

    def test_raises_file_not_found_when_no_audio(self):
        row = _make_row(original_report=_SAMPLE_REPORT, audio_path=None)
        svc = _get_svc()
        with patch.object(svc, "db_job_get", return_value=row):
            with pytest.raises(FileNotFoundError, match="Audio file not found"):
                svc.generate_job_html_report("job1")

    def test_raises_file_not_found_when_audio_missing_from_disk(self):
        row = _make_row(original_report=_SAMPLE_REPORT, audio_path="/nonexistent/path/audio.m4a")
        svc = _get_svc()
        with patch.object(svc, "db_job_get", return_value=row):
            with pytest.raises(FileNotFoundError, match="Audio file not found"):
                svc.generate_job_html_report("job1")
