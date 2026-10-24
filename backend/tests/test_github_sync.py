"""GitHub 同步模块单元测试（全部离线，不真实访问网络）。"""
from __future__ import annotations

import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest


# ─── is_configured ─────────────────────────────────────────────────────────────

def test_is_configured_false_when_no_token(monkeypatch):
    monkeypatch.delenv("COACH_DATA_GITHUB_TOKEN", raising=False)
    from cangjie_fos.services import github_sync
    assert github_sync.is_configured() is False


def test_is_configured_true_when_token_set(monkeypatch):
    monkeypatch.setenv("COACH_DATA_GITHUB_TOKEN", "ghp_test123")
    from cangjie_fos.services import github_sync
    assert github_sync.is_configured() is True


# ─── _job_to_export ────────────────────────────────────────────────────────────

def test_job_to_export_basic():
    from cangjie_fos.services.github_sync import _job_to_export

    job_row = {
        "job_id": "abc-123",
        "tenant_id": "zt",
        "interviewee": "李总",
        "created_at": 1700000000.0,
        "committed_at": 1700000100.0,
        "original_report": json.dumps({"total_score": 82, "risk_breakdown": {"严重": {"count": 1}}}),
        "edited_report": None,
    }
    result = _job_to_export(job_row)
    assert result["session_id"] == "abc-123"
    assert result["company_id"] == "zt"
    assert result["interviewee"] == "李总"
    assert result["total_score"] == 82
    assert result["fos_source"] == "cangjie_fos"
    assert result["status"] == "locked"


def test_job_to_export_prefers_edited_report():
    from cangjie_fos.services.github_sync import _job_to_export

    job_row = {
        "job_id": "x",
        "tenant_id": "t",
        "interviewee": "",
        "created_at": 1700000000.0,
        "committed_at": 1700000100.0,
        "original_report": json.dumps({"total_score": 50}),
        "edited_report": json.dumps({"total_score": 90}),
    }
    result = _job_to_export(job_row)
    assert result["total_score"] == 90  # 用 edited_report


# ─── _match_session_to_export ──────────────────────────────────────────────────

def test_match_session_to_export():
    from cangjie_fos.services.github_sync import _match_session_to_export

    session_row = {
        "id": "sess-456",
        "created_at": 1700000000.0,
        "institution": "红杉资本",
        "req_text": "需要财务报表",
        "status": "confirmed",
        "confirmed_files": json.dumps([{"filename": "报表.xlsx", "relative_path": "财务/报表.xlsx"}]),
        "results": "[]",
    }
    result = _match_session_to_export(session_row)
    assert result["session_id"] == "sess-456"
    assert result["institution"] == "红杉资本"
    assert result["fos_source"] == "cangjie_fos"
    assert len(result["confirmed_files"]) == 1


# ─── push_pitch_job（mock 网络）────────────────────────────────────────────────

def test_push_pitch_job_skips_when_not_configured(monkeypatch):
    monkeypatch.delenv("COACH_DATA_GITHUB_TOKEN", raising=False)
    from cangjie_fos.services import github_sync
    # 不配置 token，应该直接返回 False 而不发网络请求
    result = github_sync.push_pitch_job("any-job-id")
    assert result is False


def test_push_pitch_job_returns_true_on_success(monkeypatch, tmp_path):
    monkeypatch.setenv("COACH_DATA_GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("COACH_DATA_GITHUB_REPO", "test/repo")
    monkeypatch.setenv("COACH_DATA_TENANT_ID", "zt")

    # Mock db_job_get
    mock_job = {
        "job_id": "job-001",
        "tenant_id": "zt",
        "interviewee": "测试路演",
        "created_at": time.time(),
        "committed_at": time.time(),
        "original_report": json.dumps({"total_score": 75}),
        "edited_report": None,
    }

    from cangjie_fos.services import github_sync
    with patch.object(github_sync, "_get_file_sha", return_value=None), \
         patch.object(github_sync, "_put_file", return_value=True) as mock_put, \
         patch("cangjie_fos.services.pitch_job_db.db_job_get", return_value=mock_job):
        result = github_sync.push_pitch_job("job-001")

    assert result is True
    assert mock_put.called
    # 确认 path 格式正确
    call_path = mock_put.call_args[0][0]
    assert call_path.startswith("analytics/zt/")
    assert call_path.endswith(".json")


# ─── push_match_session（mock 网络）───────────────────────────────────────────

def test_push_match_session_skips_when_not_configured(monkeypatch):
    monkeypatch.delenv("COACH_DATA_GITHUB_TOKEN", raising=False)
    from cangjie_fos.services import github_sync
    result = github_sync.push_match_session("any-session-id")
    assert result is False


# ─── pull_latest（mock 网络）──────────────────────────────────────────────────

def test_pull_latest_skips_when_not_configured(monkeypatch):
    monkeypatch.delenv("COACH_DATA_GITHUB_TOKEN", raising=False)
    from cangjie_fos.services import github_sync
    result = github_sync.pull_latest()
    assert result == {"pitch_imported": 0, "match_imported": 0}


def test_pull_latest_returns_counts_structure(monkeypatch):
    monkeypatch.setenv("COACH_DATA_GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("COACH_DATA_GITHUB_REPO", "test/repo")

    from cangjie_fos.services import github_sync

    # Mock 所有网络调用，返回空列表
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = b"[]"
        mock_resp.getcode.return_value = 200
        mock_urlopen.return_value = mock_resp

        result = github_sync.pull_latest()

    assert "pitch_imported" in result
    assert "match_imported" in result
    assert isinstance(result["pitch_imported"], int)
