"""
Phase 0 R3 — LLM 指数退避重试 + retry-eval 端点测试。

运行：
  uv run --extra dev pytest tests/test_p0_retry_eval.py -v
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest
from fastapi.testclient import TestClient

from cangjie_fos.main import create_app
from cangjie_fos.services.pitch_job_db import _connect, db_job_create, db_job_get, db_job_update

TENANT = "test-tenant-retry"
JOB_WORDS = "job-retry-words-001"
JOB_NO_WORDS = "job-retry-no-words-001"
JOB_ACTIVE = "job-retry-active-001"

FAKE_WORDS_JSON = [
    {"word_index": 0, "text": "测试", "start_time": 0.0, "end_time": 0.5, "speaker_id": "A"},
    {"word_index": 1, "text": "词语", "start_time": 0.5, "end_time": 1.0, "speaker_id": "A"},
]

FAKE_REPORT_DICT = {
    "scene_analysis": {"scene_type": "R3测试场景", "speaker_roles": "双方"},
    "total_score": 75,
    "total_score_deduction_reason": "R3自动测试",
    "risk_points": [],
    "positive_highlights": ["R3亮点"],
}


@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(autouse=True, scope="module")
def setup_jobs():
    """Pre-create test jobs in SQLite."""
    conn = _connect()
    for jid in (JOB_WORDS, JOB_NO_WORDS, JOB_ACTIVE):
        conn.execute("DELETE FROM pitch_jobs WHERE job_id = ?", (jid,))
    conn.commit()
    conn.close()

    db_job_create(JOB_WORDS, TENANT)
    db_job_update(
        JOB_WORDS,
        status="failed",
        words_json=FAKE_WORDS_JSON,
        error_summary="LLM 连接失败",
    )

    db_job_create(JOB_NO_WORDS, TENANT)
    db_job_update(JOB_NO_WORDS, status="failed", error_summary="转写失败")

    db_job_create(JOB_ACTIVE, TENANT)
    db_job_update(JOB_ACTIVE, status="evaluating")


# ─── 1. Retry logic in PitchGraphService ────────────────────────────────────

class TestLLMRetryLogic:
    """验证 PitchGraphService 在 ConnectionError 时做指数退避重试。"""

    def test_raises_after_exhausting_all_attempts(self):
        """4次全部失败 → re-raise 最后一个 ConnectionError。"""
        from cangjie_fos.services.pitch_graph_service import PitchGraphService

        mock_runner = MagicMock(side_effect=ConnectionError("mock connection error"))

        with (
            patch(
                "cangjie_fos.services.pitch_graph_service.run_pitch_evaluation_via_langgraph_with_state",
                mock_runner,
            ),
            patch("cangjie_fos.services.pitch_graph_service.time.sleep") as mock_sleep,
        ):
            with pytest.raises(ConnectionError, match="mock connection error"):
                PitchGraphService.run_evaluation_with_state(
                    tenant_id=TENANT,
                    words=[],
                )
        # 4 total attempts (initial + 3 retries)
        assert mock_runner.call_count == 4
        # 3 sleeps: 2s, 4s, 8s
        assert mock_sleep.call_count == 3
        assert mock_sleep.call_args_list == [call(2), call(4), call(8)]

    def test_succeeds_on_third_retry(self):
        """前3次失败，第4次成功 → 正常返回，不 raise。"""
        from cangjie_fos.services.pitch_graph_service import PitchGraphService

        fake_report = SimpleNamespace(model_dump=lambda: FAKE_REPORT_DICT)
        mock_runner = MagicMock(
            side_effect=[
                ConnectionError("attempt 1"),
                ConnectionError("attempt 2"),
                ConnectionError("attempt 3"),
                (fake_report, {}),
            ]
        )

        with (
            patch(
                "cangjie_fos.services.pitch_graph_service.run_pitch_evaluation_via_langgraph_with_state",
                mock_runner,
            ),
            patch("cangjie_fos.services.pitch_graph_service.time.sleep"),
        ):
            report, excerpt = PitchGraphService.run_evaluation_with_state(
                tenant_id=TENANT,
                words=[],
            )
        assert mock_runner.call_count == 4
        assert report.model_dump() == FAKE_REPORT_DICT

    def test_non_retryable_error_raises_immediately(self):
        """非 ConnectionError/TimeoutError → 立即 raise，不重试。"""
        from cangjie_fos.services.pitch_graph_service import PitchGraphService

        mock_runner = MagicMock(side_effect=ValueError("schema validation failed"))

        with (
            patch(
                "cangjie_fos.services.pitch_graph_service.run_pitch_evaluation_via_langgraph_with_state",
                mock_runner,
            ),
            patch("cangjie_fos.services.pitch_graph_service.time.sleep") as mock_sleep,
        ):
            with pytest.raises(ValueError, match="schema validation failed"):
                PitchGraphService.run_evaluation_with_state(
                    tenant_id=TENANT,
                    words=[],
                )
        assert mock_runner.call_count == 1  # no retry
        mock_sleep.assert_not_called()

    def test_timeout_error_is_retried(self):
        """TimeoutError 与 ConnectionError 同等对待：3次重试后 raise。"""
        from cangjie_fos.services.pitch_graph_service import PitchGraphService

        mock_runner = MagicMock(side_effect=TimeoutError("mock timeout"))

        with (
            patch(
                "cangjie_fos.services.pitch_graph_service.run_pitch_evaluation_via_langgraph_with_state",
                mock_runner,
            ),
            patch("cangjie_fos.services.pitch_graph_service.time.sleep") as mock_sleep,
        ):
            with pytest.raises(TimeoutError, match="mock timeout"):
                PitchGraphService.run_evaluation_with_state(
                    tenant_id=TENANT,
                    words=[],
                )
        assert mock_runner.call_count == 4
        assert mock_sleep.call_count == 3


# ─── 2. retry-eval endpoint ──────────────────────────────────────────────────

class TestRetryEvalEndpoint:

    def test_404_unknown_job(self, client):
        r = client.post("/api/pitch/jobs/nonexistent-job-xyz/retry-eval")
        assert r.status_code == 404

    def test_422_no_words_json(self, client):
        r = client.post(f"/api/pitch/jobs/{JOB_NO_WORDS}/retry-eval")
        assert r.status_code == 422

    def test_409_already_active(self, client):
        r = client.post(f"/api/pitch/jobs/{JOB_ACTIVE}/retry-eval")
        assert r.status_code == 409

    def test_200_queues_evaluation(self, client):
        """成功重跑：状态立即变 evaluating，background task 完成后变 completed。"""
        fake_report = SimpleNamespace(model_dump=lambda: FAKE_REPORT_DICT)

        with (
            patch("cangjie_fos.api.routes.pitch.ensure_pitch_coach_runtime"),
            patch(
                "cangjie_fos.api.routes.pitch.PitchGraphService.run_evaluation_with_state",
                return_value=(fake_report, {}),
            ),
        ):
            r = client.post(f"/api/pitch/jobs/{JOB_WORDS}/retry-eval")

        assert r.status_code == 200, r.text
        data = r.json()
        assert data["job_id"] == JOB_WORDS
        # HTTP response body captures the status set before background task runs
        assert data["status"] == "evaluating"
        # TestClient runs BackgroundTasks synchronously — DB is already updated
        row = db_job_get(JOB_WORDS)
        assert row is not None and row["status"] == "completed"
        assert row["original_report"]["total_score"] == 75

    def test_db_completed_after_retry(self, client):
        """验证 DB 持久化（补充 test_200_queues_evaluation 的 DB 断言）。
        TestClient 同步执行 BackgroundTasks，此处为可读性补充，不依赖顺序。
        """
        row = db_job_get(JOB_WORDS)
        assert row is not None
        assert row["status"] == "completed"
        assert isinstance(row.get("original_report"), dict)
        assert row["original_report"]["total_score"] == 75

    def test_has_words_json_in_job_list(self, client):
        """GET /jobs 应含 has_words_json=true 对于有 words_json 的 job。"""
        r = client.get("/api/pitch/jobs", params={"tenant_id": TENANT})
        assert r.status_code == 200
        jobs = r.json()
        target = next((j for j in jobs if j["job_id"] == JOB_WORDS), None)
        assert target is not None
        assert target["has_words_json"] is True

    def test_has_words_json_false_without_words(self, client):
        target_no_words = next(
            (j for j in client.get("/api/pitch/jobs", params={"tenant_id": TENANT}).json()
             if j["job_id"] == JOB_NO_WORDS),
            None,
        )
        assert target_no_words is not None
        assert target_no_words["has_words_json"] is False
