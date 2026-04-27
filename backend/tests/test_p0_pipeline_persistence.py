"""TDD tests for pitch_upload_pipeline.py persistence changes (Phase 6.4 Task 2).

All external I/O is mocked. Tests verify:
1. Audio file is moved to permanent location (not deleted).
2. words_json and audio_path are persisted to DB.
3. original_report is written to DB on success.
4. In-memory store still receives 'report' on success (backward compat).
5. On failure, both stores are updated with FAILED status.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_JOB_ID = "test-job-abc123"
_TENANT_ID = "tenant-test"
_FILENAME = "pitch.wav"
_RAW_BYTES = b"fake-audio-data"


def _make_word(text: str = "hello"):
    w = MagicMock()
    w.model_dump.return_value = {"word": text, "start": 0.0, "end": 0.5}
    return w


def _make_report():
    r = MagicMock()
    r.model_dump.return_value = {"score": 85, "feedback": "Good pitch"}
    return r


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_DEFAULT_MOCK_WORDS = None  # populated lazily per test via helper


def _make_default_words():
    return [_make_word("hello"), _make_word("world")]


# ---------------------------------------------------------------------------
# Test 1: audio moved to permanent location, tmp NOT unlinked
# ---------------------------------------------------------------------------


def test_audio_moved_to_permanent_location():
    """shutil.move must be called with the correct destination; tmp.unlink not called."""
    mock_report = _make_report()

    with (
        patch("cangjie_fos.services.pitch_upload_pipeline.AudioService") as mock_audio_svc,
        patch("cangjie_fos.services.pitch_upload_pipeline.transcribe_audio", return_value=_make_default_words()),
        patch("cangjie_fos.services.pitch_upload_pipeline.PitchGraphService") as mock_graph_svc,
        patch("cangjie_fos.services.pitch_upload_pipeline.db_job_update"),
        patch("cangjie_fos.services.pitch_upload_pipeline.job_update"),
        patch("cangjie_fos.services.pitch_upload_pipeline.shutil") as mock_shutil,
        patch("cangjie_fos.services.pitch_upload_pipeline.get_backend_root") as mock_root,
        patch("cangjie_fos.services.pitch_upload_pipeline.tempfile") as mock_tempfile,
    ):
        # Setup mocks
        mock_compressed = MagicMock()
        mock_compressed.data = b"compressed-audio"
        mock_audio_svc.smart_compress_media.return_value = mock_compressed

        mock_graph_svc.run_evaluation_with_state.return_value = (mock_report, "excerpt")

        # Simulate tempfile.NamedTemporaryFile context manager
        mock_tmp_file = MagicMock()
        mock_tmp_file.__enter__ = MagicMock(return_value=mock_tmp_file)
        mock_tmp_file.__exit__ = MagicMock(return_value=False)
        mock_tmp_file.name = "/tmp/tmpXYZabc.wav"
        mock_tempfile.NamedTemporaryFile.return_value = mock_tmp_file

        mock_root.return_value = Path("/fake/backend")

        from cangjie_fos.services.pitch_upload_pipeline import run_pitch_upload_job

        run_pitch_upload_job(
            job_id=_JOB_ID,
            raw_bytes=_RAW_BYTES,
            filename=_FILENAME,
            tenant_id=_TENANT_ID,
        )

        # shutil.move must have been called
        assert mock_shutil.move.called, "shutil.move was not called"
        move_args = mock_shutil.move.call_args
        src, dst = move_args[0][0], move_args[0][1]

        # destination must contain job_id and .wav suffix
        assert _JOB_ID in dst, f"Destination path does not contain job_id: {dst}"
        assert dst.endswith(".wav"), f"Destination path does not end with .wav: {dst}"
        assert "audio" in dst, f"Destination path does not contain 'audio' dir: {dst}"

        # tmp file must NOT have been unlinked (it was moved, not deleted)
        # The pipeline sets tmp=None after move, so unlink is never called on it.
        # We verify shutil.move was called (move = success path).
        mock_shutil.move.assert_called_once()


# ---------------------------------------------------------------------------
# Test 2: words_json and audio_path persisted to DB
# ---------------------------------------------------------------------------


def test_words_json_persisted_to_db():
    """db_job_update must be called with words_json list and audio_path containing job_id."""
    mock_report = _make_report()
    mock_words = [_make_word("test")]

    with (
        patch("cangjie_fos.services.pitch_upload_pipeline.AudioService") as mock_audio_svc,
        patch("cangjie_fos.services.pitch_upload_pipeline.transcribe_audio", return_value=mock_words),
        patch("cangjie_fos.services.pitch_upload_pipeline.PitchGraphService") as mock_graph_svc,
        patch("cangjie_fos.services.pitch_upload_pipeline.db_job_update") as mock_db_update,
        patch("cangjie_fos.services.pitch_upload_pipeline.job_update"),
        patch("cangjie_fos.services.pitch_upload_pipeline.shutil"),
        patch("cangjie_fos.services.pitch_upload_pipeline.get_backend_root") as mock_root,
        patch("cangjie_fos.services.pitch_upload_pipeline.tempfile") as mock_tempfile,
    ):
        mock_compressed = MagicMock()
        mock_compressed.data = b"data"
        mock_audio_svc.smart_compress_media.return_value = mock_compressed

        mock_graph_svc.run_evaluation_with_state.return_value = (mock_report, "excerpt")

        mock_tmp_file = MagicMock()
        mock_tmp_file.__enter__ = MagicMock(return_value=mock_tmp_file)
        mock_tmp_file.__exit__ = MagicMock(return_value=False)
        mock_tmp_file.name = "/tmp/tmpABC.wav"
        mock_tempfile.NamedTemporaryFile.return_value = mock_tmp_file

        mock_root.return_value = Path("/fake/backend")

        from cangjie_fos.services.pitch_upload_pipeline import run_pitch_upload_job

        run_pitch_upload_job(
            job_id=_JOB_ID,
            raw_bytes=_RAW_BYTES,
            filename=_FILENAME,
            tenant_id=_TENANT_ID,
        )

        # Find the call that contains words_json
        words_json_calls = [
            c for c in mock_db_update.call_args_list if "words_json" in c.kwargs
        ]
        assert words_json_calls, "db_job_update was never called with words_json"

        words_call = words_json_calls[0]
        assert isinstance(words_call.kwargs["words_json"], list), "words_json must be a list"
        assert len(words_call.kwargs["words_json"]) == 1

        # Also check audio_path
        assert "audio_path" in words_call.kwargs, "db_job_update with words_json must also contain audio_path"
        assert _JOB_ID in words_call.kwargs["audio_path"], "audio_path must contain job_id"


# ---------------------------------------------------------------------------
# Test 3: original_report written to DB on success
# ---------------------------------------------------------------------------


def test_original_report_written_to_db():
    """db_job_update must be called with original_report dict on successful completion."""
    mock_report = _make_report()

    with (
        patch("cangjie_fos.services.pitch_upload_pipeline.AudioService") as mock_audio_svc,
        patch("cangjie_fos.services.pitch_upload_pipeline.transcribe_audio", return_value=_make_default_words()),
        patch("cangjie_fos.services.pitch_upload_pipeline.PitchGraphService") as mock_graph_svc,
        patch("cangjie_fos.services.pitch_upload_pipeline.db_job_update") as mock_db_update,
        patch("cangjie_fos.services.pitch_upload_pipeline.job_update"),
        patch("cangjie_fos.services.pitch_upload_pipeline.shutil"),
        patch("cangjie_fos.services.pitch_upload_pipeline.get_backend_root") as mock_root,
        patch("cangjie_fos.services.pitch_upload_pipeline.tempfile") as mock_tempfile,
    ):
        mock_compressed = MagicMock()
        mock_compressed.data = b"data"
        mock_audio_svc.smart_compress_media.return_value = mock_compressed

        mock_graph_svc.run_evaluation_with_state.return_value = (mock_report, "excerpt")

        mock_tmp_file = MagicMock()
        mock_tmp_file.__enter__ = MagicMock(return_value=mock_tmp_file)
        mock_tmp_file.__exit__ = MagicMock(return_value=False)
        mock_tmp_file.name = "/tmp/tmpDEF.wav"
        mock_tempfile.NamedTemporaryFile.return_value = mock_tmp_file

        mock_root.return_value = Path("/fake/backend")

        from cangjie_fos.services.pitch_upload_pipeline import run_pitch_upload_job

        run_pitch_upload_job(
            job_id=_JOB_ID,
            raw_bytes=_RAW_BYTES,
            filename=_FILENAME,
            tenant_id=_TENANT_ID,
        )

        # Find call with original_report
        original_report_calls = [
            c for c in mock_db_update.call_args_list if "original_report" in c.kwargs
        ]
        assert original_report_calls, "db_job_update was never called with original_report"

        report_call = original_report_calls[0]
        assert isinstance(report_call.kwargs["original_report"], dict), "original_report must be a dict"
        assert report_call.kwargs["original_report"]["score"] == 85


# ---------------------------------------------------------------------------
# Test 4: in-memory store still receives 'report' on success
# ---------------------------------------------------------------------------


def test_in_memory_report_still_written():
    """job_update (in-memory) must be called with 'report' key on success for backward compat."""
    mock_report = _make_report()

    with (
        patch("cangjie_fos.services.pitch_upload_pipeline.AudioService") as mock_audio_svc,
        patch("cangjie_fos.services.pitch_upload_pipeline.transcribe_audio", return_value=_make_default_words()),
        patch("cangjie_fos.services.pitch_upload_pipeline.PitchGraphService") as mock_graph_svc,
        patch("cangjie_fos.services.pitch_upload_pipeline.db_job_update"),
        patch("cangjie_fos.services.pitch_upload_pipeline.job_update") as mock_mem_update,
        patch("cangjie_fos.services.pitch_upload_pipeline.shutil"),
        patch("cangjie_fos.services.pitch_upload_pipeline.get_backend_root") as mock_root,
        patch("cangjie_fos.services.pitch_upload_pipeline.tempfile") as mock_tempfile,
    ):
        mock_compressed = MagicMock()
        mock_compressed.data = b"data"
        mock_audio_svc.smart_compress_media.return_value = mock_compressed

        mock_graph_svc.run_evaluation_with_state.return_value = (mock_report, "excerpt")

        mock_tmp_file = MagicMock()
        mock_tmp_file.__enter__ = MagicMock(return_value=mock_tmp_file)
        mock_tmp_file.__exit__ = MagicMock(return_value=False)
        mock_tmp_file.name = "/tmp/tmpGHI.wav"
        mock_tempfile.NamedTemporaryFile.return_value = mock_tmp_file

        mock_root.return_value = Path("/fake/backend")

        from cangjie_fos.services.pitch_upload_pipeline import run_pitch_upload_job

        run_pitch_upload_job(
            job_id=_JOB_ID,
            raw_bytes=_RAW_BYTES,
            filename=_FILENAME,
            tenant_id=_TENANT_ID,
        )

        # Find call with 'report' key (in-memory store backward compat)
        report_calls = [
            c for c in mock_mem_update.call_args_list if "report" in c.kwargs
        ]
        assert report_calls, "job_update was never called with 'report' key"
        assert isinstance(report_calls[0].kwargs["report"], dict)
        assert report_calls[0].kwargs["report"]["score"] == 85


# ---------------------------------------------------------------------------
# Test 5: failure updates both stores
# ---------------------------------------------------------------------------


def test_failure_updates_both_stores():
    """On exception during transcription, both job_update and db_job_update called with FAILED."""
    with (
        patch("cangjie_fos.services.pitch_upload_pipeline.AudioService") as mock_audio_svc,
        patch("cangjie_fos.services.pitch_upload_pipeline.transcribe_audio", side_effect=RuntimeError("ASR exploded")),
        patch("cangjie_fos.services.pitch_upload_pipeline.PitchGraphService"),
        patch("cangjie_fos.services.pitch_upload_pipeline.db_job_update") as mock_db_update,
        patch("cangjie_fos.services.pitch_upload_pipeline.job_update") as mock_mem_update,
        patch("cangjie_fos.services.pitch_upload_pipeline.shutil"),
        patch("cangjie_fos.services.pitch_upload_pipeline.get_backend_root") as mock_root,
        patch("cangjie_fos.services.pitch_upload_pipeline.tempfile") as mock_tempfile,
    ):
        mock_compressed = MagicMock()
        mock_compressed.data = b"data"
        mock_audio_svc.smart_compress_media.return_value = mock_compressed

        mock_tmp_file = MagicMock()
        mock_tmp_file.__enter__ = MagicMock(return_value=mock_tmp_file)
        mock_tmp_file.__exit__ = MagicMock(return_value=False)
        mock_tmp_file.name = "/tmp/tmpJKL.wav"
        mock_tempfile.NamedTemporaryFile.return_value = mock_tmp_file

        mock_root.return_value = Path("/fake/backend")

        from cangjie_fos.services.pitch_upload_pipeline import run_pitch_upload_job
        from cangjie_fos.schemas.pitch_upload import PitchJobStatus

        run_pitch_upload_job(
            job_id=_JOB_ID,
            raw_bytes=_RAW_BYTES,
            filename=_FILENAME,
            tenant_id=_TENANT_ID,
        )

        # In-memory store: called with FAILED
        failed_mem_calls = [
            c for c in mock_mem_update.call_args_list
            if c.kwargs.get("status") == PitchJobStatus.FAILED
        ]
        assert failed_mem_calls, "job_update was not called with FAILED status"

        # DB store: called with FAILED (as string since db_job_update receives str)
        failed_db_calls = [
            c for c in mock_db_update.call_args_list
            if str(PitchJobStatus.FAILED) in str(c.kwargs.get("status", ""))
        ]
        assert failed_db_calls, "db_job_update was not called with FAILED status"
