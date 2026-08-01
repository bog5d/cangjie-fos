"""通用会议纪要端到端集成测试。

外部服务（ASR、LLM）全部 mock，真实执行：
  - 音频上传 → 压缩 → ASR → 纪要提炼 → completed 全链路（单阶段）
  - biz_type == '06_通用会议纪要' 正确传给 PitchGraphService
  - 文字稿模式（跳过 ASR）
  - report 端点返回 MeetingMinutesReport 字段
  - HTML 报告生成 + 落盘 + 生成前 404

运行：
  uv run --extra dev pytest tests/test_meeting_minutes_e2e.py -v
"""
from __future__ import annotations

import io
import time
import urllib.parse
import wave
from types import SimpleNamespace

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from cangjie_fos.main import create_app
from cangjie_fos.services.pitch_job_db import db_job_get

TENANT = "test-meeting-e2e"

FAKE_MINUTES_REPORT = {
    "report_type": "meeting_minutes",
    "meeting_title": "Q3 高管访谈",
    "attendees": ["王总", "李经理"],
    "summary": "讨论了Q3销售目标与技术路线，确定了两项行动。",
    "key_points": ["Q3目标600万", "技术路线聚焦AI"],
    "decisions": ["扩招销售团队3人"],
    "action_items": [
        {"source": "commitment", "actor": "李经理", "action": "本周提交招聘计划", "priority": "urgent"},
    ],
    "open_questions": ["预算是否到位待确认"],
}


def _fake_eval(*, tenant_id, words, explicit_context=None, **kw):
    ns = SimpleNamespace(**FAKE_MINUTES_REPORT)
    ns.model_dump = lambda: FAKE_MINUTES_REPORT
    return ns, {}


def make_wav_bytes(duration_sec: float = 0.3, sample_rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    n_frames = int(sample_rate * duration_sec)
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)
    return buf.getvalue()


FAKE_WORDS = [
    SimpleNamespace(
        word_index=0, text="今天讨论Q3目标", start_time=0.0, end_time=1.0, speaker_id="0",
        model_dump=lambda: {"word_index": 0, "text": "今天讨论Q3目标",
                            "start_time": 0.0, "end_time": 1.0, "speaker_id": "0"},
    ),
]


@pytest.fixture()
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def _wait_done(job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        row = db_job_get(job_id)
        if row and row.get("status") in ("completed", "failed"):
            return row
        time.sleep(0.1)
    return db_job_get(job_id) or {}


class TestMeetingMinutesAudioE2E:
    """音频上传全链路（单阶段）。"""

    def _start_audio(self, client) -> str:
        with patch(
            "cangjie_fos.services.pitch_upload_pipeline.AudioService.smart_compress_media",
            return_value=SimpleNamespace(data=make_wav_bytes(), did_compress=False),
        ), patch(
            "cangjie_fos.services.pitch_upload_pipeline.transcribe_audio",
            return_value=FAKE_WORDS,
        ), patch(
            "cangjie_fos.services.pitch_upload_pipeline.PitchGraphService.run_evaluation_with_state",
            side_effect=_fake_eval,
        ):
            resp = client.post(
                f"/api/v1/meeting/start?tenant_id={TENANT}&meeting_title=Q3高管访谈",
                files={"file": ("meeting.wav", make_wav_bytes(), "audio/wav")},
            )
            assert resp.status_code == 200, resp.text
            return resp.json()["job_id"]

    def test_audio_flow_completes(self, client):
        job_id = self._start_audio(client)
        row = _wait_done(job_id)
        assert row.get("status") == "completed", f"实际状态 {row.get('status')}"

    def test_report_type_is_meeting_minutes(self, client):
        job_id = self._start_audio(client)
        _wait_done(job_id)
        resp = client.get(f"/api/v1/meeting/jobs/{job_id}/report")
        assert resp.status_code == 200, resp.text
        assert resp.json()["report"]["report_type"] == "meeting_minutes"

    def test_biz_type_passed_to_pitch_graph(self, client):
        captured: dict = {}

        def _capture_eval(*, tenant_id, words, explicit_context=None, **kw):
            captured.update(explicit_context or {})
            return _fake_eval(tenant_id=tenant_id, words=words, explicit_context=explicit_context)

        with patch(
            "cangjie_fos.services.pitch_upload_pipeline.AudioService.smart_compress_media",
            return_value=SimpleNamespace(data=make_wav_bytes(), did_compress=False),
        ), patch(
            "cangjie_fos.services.pitch_upload_pipeline.transcribe_audio",
            return_value=FAKE_WORDS,
        ), patch(
            "cangjie_fos.services.pitch_upload_pipeline.PitchGraphService.run_evaluation_with_state",
            side_effect=_capture_eval,
        ):
            resp = client.post(
                f"/api/v1/meeting/start?tenant_id={TENANT}&meeting_title=测试会",
                files={"file": ("m.wav", make_wav_bytes(), "audio/wav")},
            )
            job_id = resp.json()["job_id"]
            _wait_done(job_id)
        assert captured.get("biz_type") == "06_通用会议纪要"

    def test_db_category_written(self, client):
        job_id = self._start_audio(client)
        row = _wait_done(job_id)
        assert row["category"] == "06_通用会议纪要"
        assert row["is_roadshow"] == 0


class TestMeetingMinutesTranscriptE2E:
    """文字稿模式（跳过 ASR）。"""

    def test_transcript_flow_completes(self, client):
        transcript = "说话人A：我们定一下Q3目标。\n说话人B：好，目标600万。"
        encoded = urllib.parse.quote(transcript, safe="")
        with patch(
            "cangjie_fos.services.pitch_graph_service.PitchGraphService.run_evaluation_with_state",
            side_effect=_fake_eval,
        ):
            resp = client.post(
                f"/api/v1/meeting/start?tenant_id={TENANT}&meeting_title=文字稿会&transcript_text={encoded}"
            )
            assert resp.status_code == 200, resp.text
            job_id = resp.json()["job_id"]
            row = _wait_done(job_id)
        assert row.get("status") == "completed"


class TestMeetingMinutesHtmlAndErrors:
    def test_status_404_unknown_job(self, client):
        resp = client.get("/api/v1/meeting/jobs/nonexistent/status")
        assert resp.status_code == 404

    def test_start_requires_input(self, client):
        resp = client.post(f"/api/v1/meeting/start?tenant_id={TENANT}")
        assert resp.status_code == 400

    def test_html_report_generation_and_download(self, client):
        # 先跑一场完成的会议
        with patch(
            "cangjie_fos.services.pitch_upload_pipeline.AudioService.smart_compress_media",
            return_value=SimpleNamespace(data=make_wav_bytes(), did_compress=False),
        ), patch(
            "cangjie_fos.services.pitch_upload_pipeline.transcribe_audio",
            return_value=FAKE_WORDS,
        ), patch(
            "cangjie_fos.services.pitch_upload_pipeline.PitchGraphService.run_evaluation_with_state",
            side_effect=_fake_eval,
        ):
            resp = client.post(
                f"/api/v1/meeting/start?tenant_id={TENANT}&meeting_title=HTML会",
                files={"file": ("m.wav", make_wav_bytes(), "audio/wav")},
            )
            job_id = resp.json()["job_id"]
            _wait_done(job_id)

        # 生成前 GET 应 404
        r_before = client.get(f"/api/v1/meeting/jobs/{job_id}/html-report")
        assert r_before.status_code == 404

        # 生成
        r_gen = client.post(f"/api/v1/meeting/jobs/{job_id}/html-report")
        assert r_gen.status_code == 200, r_gen.text
        assert r_gen.json()["ok"] is True

        # 下载
        r_get = client.get(f"/api/v1/meeting/jobs/{job_id}/html-report")
        assert r_get.status_code == 200
        assert "会议纪要" in r_get.text
        assert "扩招销售团队3人" in r_get.text  # 决议内容


class TestMeetingMinutesSchema:
    def test_minimal_construct(self):
        from cangjie_fos.engine.schema import MeetingMinutesReport
        r = MeetingMinutesReport(summary="简单纪要")
        assert r.report_type == "meeting_minutes"
        assert r.key_points == []
        assert r.action_items == []

    def test_full_construct_and_dump(self):
        from cangjie_fos.engine.schema import MeetingMinutesReport
        r = MeetingMinutesReport.model_validate(FAKE_MINUTES_REPORT)
        assert r.meeting_title == "Q3 高管访谈"
        assert r.action_items[0].actor == "李经理"
        assert r.action_items[0].priority == "urgent"
        assert "report_type" in r.model_dump()
