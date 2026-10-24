"""v1.11.0 断点续跑：向导路径 ASR 一就绪即落 words_json，
评估失败也不丢转写，可经 retry-eval 端点直接重跑（省去昂贵的二次 ASR）。
"""
from __future__ import annotations

import io
import wave
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.real_db]

from cangjie_fos.main import create_app
from cangjie_fos.services.pitch_job_db import _connect, db_job_get
from cangjie_fos.services.pitch_job_store import job_create
from cangjie_fos.services.pitch_wizard_runner import run_pitch_wizard_track_job

TENANT = "t-resume"


def make_wav(duration: float = 0.5, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * int(rate * duration))
    return buf.getvalue()


class _W:
    def __init__(self, i: int):
        self.word_index = i
        self.text = f"w{i}"
        self.start_time = float(i)
        self.end_time = float(i) + 0.5
        self.speaker_id = "A"

    def model_dump(self):
        return dict(self.__dict__)


WORDS = [_W(i) for i in range(5)]


def _run_failing_wizard(job_id: str, audio_file) -> None:
    """跑一遍向导，但 run_pitch_file_job 先调 on_words 落库、再抛错（模拟 ASR 成功、评估失败）。"""
    def fake_rpfj(audio_path, params, *, on_status=None, skip_html_export=True,
                  cached_words=None, on_words=None):
        if on_words is not None:
            on_words(WORDS)          # ASR 成果落库
        raise RuntimeError("eval boom")  # 评估阶段失败

    with (
        patch("cangjie_fos.services.pitch_wizard_runner.run_pitch_file_job", side_effect=fake_rpfj),
        patch("cangjie_fos.services.pitch_wizard_runner.PitchFileJobParams", MagicMock(return_value=MagicMock())),
        patch("cangjie_fos.services.pitch_wizard_runner.build_explicit_context", return_value={}),
        patch("cangjie_fos.services.pitch_wizard_runner.HtmlExportOptions", MagicMock(return_value=MagicMock())),
    ):
        run_pitch_wizard_track_job(
            job_id=job_id, tenant_id=TENANT, audio_path=audio_file,
            recording_label="r.wav", category="尽调", project_name="p",
            interviewee="x", session_notes="", sniper_targets_json="",
            custom_roles_other="", qa_text="", company_background="",
            sensitive_words=[], hot_words=None, memory_company_id=TENANT,
            skip_asr_polish=True, use_langgraph_v1=False,
        )


def _fresh_job(job_id: str) -> None:
    conn = _connect()
    conn.execute("DELETE FROM pitch_jobs WHERE job_id = ?", (job_id,))
    conn.commit()
    conn.close()
    job_create(job_id, TENANT)


def test_words_survive_eval_failure(tmp_path):
    """评估失败后，job 标 failed，但 words_json 已落库（ASR 成果未丢）。"""
    af = tmp_path / "r.wav"
    af.write_bytes(make_wav())
    _fresh_job("wiz-resume-1")
    _run_failing_wizard("wiz-resume-1", af)

    row = db_job_get("wiz-resume-1")
    assert row["status"] == "failed"
    words = row.get("words_json")
    assert isinstance(words, list) and len(words) == 5, "ASR 成果应在评估失败后仍保留"


def test_retry_eval_resumes_from_cached_words(tmp_path):
    """失败后 retry-eval 应能从 words_json 重跑评估直达 completed（无需二次 ASR）。"""
    af = tmp_path / "r.wav"
    af.write_bytes(make_wav())
    _fresh_job("wiz-resume-2")
    _run_failing_wizard("wiz-resume-2", af)

    fake_report = SimpleNamespace(model_dump=lambda: {
        "total_score": 80, "risk_points": [], "positive_highlights": [],
        "scene_analysis": {"scene_type": "重跑", "speaker_roles": "A"},
    })
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c, patch(
        "cangjie_fos.api.routes.pitch.PitchGraphService.run_evaluation_with_state",
        return_value=(fake_report, {}),
    ):
        r = c.post("/api/pitch/jobs/wiz-resume-2/retry-eval")
        assert r.status_code == 200, r.text

    row = db_job_get("wiz-resume-2")
    assert row["status"] == "completed"
    assert row["original_report"]["total_score"] == 80


def test_retry_eval_422_without_words(tmp_path):
    """没有 words_json 的失败 job，retry-eval 应 422（提示重新上传），不假装能重跑。"""
    _fresh_job("wiz-resume-3")
    from cangjie_fos.services.pitch_job_db import db_job_update
    db_job_update("wiz-resume-3", status="failed")
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/api/pitch/jobs/wiz-resume-3/retry-eval")
    assert r.status_code == 422
