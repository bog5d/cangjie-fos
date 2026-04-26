"""Tests for Phase 6.4 Task 4 (P3): NPC 豆豆 audio/job context awareness."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Test 1: _base_system contains capability keywords
# ---------------------------------------------------------------------------

def test_base_system_contains_capability_keywords():
    from cangjie_fos.services.npc_chat_graph import _base_system, _npc_display_name

    result = _base_system()
    assert "音轨复盘" in result
    assert "LangGraph" in result
    npc_name = _npc_display_name()
    assert npc_name in result


# ---------------------------------------------------------------------------
# Test 2: _inject_job_context — no-op when active_job_id is absent
# ---------------------------------------------------------------------------

def test_inject_job_context_no_job_id():
    from cangjie_fos.services.npc_chat_graph import _inject_job_context

    result = _inject_job_context({"narrative": "base"})
    assert result == {}


# ---------------------------------------------------------------------------
# Test 3: _inject_job_context — valid job row injects context into narrative
# ---------------------------------------------------------------------------

def test_inject_job_context_with_valid_job():
    from cangjie_fos.services.npc_chat_graph import _inject_job_context

    fake_row = {
        "status": "completed",
        "original_report": {
            "total_score": 75,
            "risk_points": [{"x": 1}, {"x": 2}],
        },
        "committed_at": None,
    }

    state = {"narrative": "base", "active_job_id": "abc123"}

    with patch("cangjie_fos.services.pitch_job_db.db_job_get", return_value=fake_row):
        result = _inject_job_context(state)

    assert "narrative" in result
    narrative = result["narrative"]
    assert "abc123" in narrative
    assert "75" in narrative
    assert "2" in narrative
    assert "未审查" in narrative


# ---------------------------------------------------------------------------
# Test 4: _inject_job_context — db returns None → no-op
# ---------------------------------------------------------------------------

def test_inject_job_context_db_returns_none():
    from cangjie_fos.services.npc_chat_graph import _inject_job_context

    state = {"narrative": "base", "active_job_id": "nonexistent-job"}

    with patch("cangjie_fos.services.pitch_job_db.db_job_get", return_value=None):
        result = _inject_job_context(state)

    assert result == {}


# ---------------------------------------------------------------------------
# Test 5: invoke_npc_chat passes active_job_id into graph invoke
# ---------------------------------------------------------------------------

def test_invoke_npc_chat_passes_active_job_id():
    from cangjie_fos.services.npc_chat_graph import invoke_npc_chat, reset_compiled_npc_graph_for_tests

    reset_compiled_npc_graph_for_tests()

    mock_app = MagicMock()
    mock_app.invoke.return_value = {"messages": []}

    with patch(
        "cangjie_fos.services.npc_chat_graph.get_compiled_npc_graph",
        return_value=mock_app,
    ):
        invoke_npc_chat(
            tenant_id="t1",
            user_message="hi",
            thread_id=None,
            active_job_id="job999",
        )

    assert mock_app.invoke.called
    call_args = mock_app.invoke.call_args
    # First positional arg is the state dict
    state_dict = call_args[0][0]
    assert state_dict.get("active_job_id") == "job999"


# ---------------------------------------------------------------------------
# Test 6: PitchChatRequest schema accepts active_job_id and defaults to None
# ---------------------------------------------------------------------------

def test_pitch_chat_schema_has_active_job_id():
    from cangjie_fos.schemas.pitch_chat import PitchChatRequest

    # Default is None
    req_default = PitchChatRequest(tenant_id="t1", message="hello")
    assert req_default.active_job_id is None

    # Accepts a value without validation error
    req_with_job = PitchChatRequest(tenant_id="t1", message="hello", active_job_id="abc")
    assert req_with_job.active_job_id == "abc"


# ---------------------------------------------------------------------------
# Test 7: _inject_system_health — readiness OK + no recent errors → OK line
# ---------------------------------------------------------------------------

def test_inject_system_health_ok_no_errors():
    from unittest.mock import MagicMock
    from cangjie_fos.services.npc_chat_graph import _inject_system_health

    mock_readiness = MagicMock()
    mock_readiness.ok = True
    mock_readiness.issues = []
    mock_readiness.job_queue_in_use = 0
    mock_readiness.job_queue_capacity = 0

    with (
        patch("cangjie_fos.core.readiness.compute_readiness", return_value=mock_readiness),
        patch("cangjie_fos.services.pitch_job_db.db_job_list_recent_errors", return_value=[]),
    ):
        result = _inject_system_health({"narrative": "base"})

    assert "narrative" in result
    assert "<<系统健康快照>>" in result["narrative"]
    assert "OK" in result["narrative"]


# ---------------------------------------------------------------------------
# Test 8: _inject_system_health — readiness NOT ok → issues injected
# ---------------------------------------------------------------------------

def test_inject_system_health_with_issues():
    from unittest.mock import MagicMock
    from cangjie_fos.core.readiness import ReadinessIssue
    from cangjie_fos.services.npc_chat_graph import _inject_system_health

    issue = ReadinessIssue(
        code="E_API_KEYS_INCOMPLETE",
        message="SILICONFLOW_API_KEY 未配置",
        fix_hint="请在 backend/.env 填写密钥",
        severity="error",
    )
    mock_readiness = MagicMock()
    mock_readiness.ok = False
    mock_readiness.issues = [issue]
    mock_readiness.job_queue_in_use = 0
    mock_readiness.job_queue_capacity = 0

    with (
        patch("cangjie_fos.core.readiness.compute_readiness", return_value=mock_readiness),
        patch("cangjie_fos.services.pitch_job_db.db_job_list_recent_errors", return_value=[]),
    ):
        result = _inject_system_health({"narrative": "base"})

    narrative = result["narrative"]
    assert "异常" in narrative
    assert "E_API_KEYS_INCOMPLETE" in narrative
    assert "请在 backend/.env 填写密钥" in narrative


# ---------------------------------------------------------------------------
# Test 9: _inject_system_health — recent failed jobs are included in snapshot
# ---------------------------------------------------------------------------

def test_inject_system_health_with_recent_errors():
    from unittest.mock import MagicMock
    from cangjie_fos.services.npc_chat_graph import _inject_system_health

    mock_readiness = MagicMock()
    mock_readiness.ok = True
    mock_readiness.issues = []
    mock_readiness.job_queue_in_use = 0
    mock_readiness.job_queue_capacity = 0

    recent_errors = [
        {"job_id": "abcdef1234", "error_summary": "转写服务超时"},
        {"job_id": "xyz9876543", "error_summary": "API 密钥无效"},
    ]

    with (
        patch("cangjie_fos.core.readiness.compute_readiness", return_value=mock_readiness),
        patch("cangjie_fos.services.pitch_job_db.db_job_list_recent_errors", return_value=recent_errors),
    ):
        result = _inject_system_health({"narrative": "base"})

    narrative = result["narrative"]
    assert "最近失败任务" in narrative
    assert "abcdef12" in narrative   # first 8 chars of job_id
    assert "转写服务超时" in narrative
    assert "API 密钥无效" in narrative


# ---------------------------------------------------------------------------
# Test 10: _inject_system_health — compute_readiness raises → graceful fallback
# ---------------------------------------------------------------------------

def test_inject_system_health_exception_resilience():
    from cangjie_fos.services.npc_chat_graph import _inject_system_health

    with (
        patch("cangjie_fos.core.readiness.compute_readiness", side_effect=RuntimeError("disk read failed")),
        patch("cangjie_fos.services.pitch_job_db.db_job_list_recent_errors", return_value=[]),
    ):
        result = _inject_system_health({"narrative": "base"})

    # Should not raise; should return fallback message
    assert "narrative" in result
    assert "系统状态读取失败" in result["narrative"]


# ---------------------------------------------------------------------------
# Test 11: _base_system contains diagnostic keywords
# ---------------------------------------------------------------------------

def test_base_system_contains_diagnostic_keywords():
    from cangjie_fos.services.npc_chat_graph import _base_system

    result = _base_system()
    assert "健康监测员" in result
    assert "<<系统健康快照>>" in result
    assert "建议" in result
