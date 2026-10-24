"""
Wizard pipeline 端到端测试。

覆盖 run_pitch_wizard_track_job 全链路：
  job_create → TRANSCRIBING → audio永久落盘 → EVALUATING → COMPLETED
  → SQLite words_json / audio_path / original_report 写入
  → GET /review 返回正确数据（而非「数据异常」）

不需要真实 ASR / LLM / 人工上传。
"""
from __future__ import annotations

import io
import sys
import tempfile
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.real_db]

from cangjie_fos.main import create_app
from cangjie_fos.services.pitch_job_db import db_job_get, _connect
from cangjie_fos.services.pitch_job_store import job_create
from cangjie_fos.services.pitch_wizard_runner import run_pitch_wizard_track_job

# ── 测试常量 ─────────────────────────────────────
TENANT = "test-tenant-wizard"
JOB_ID = "wizard-e2e-test-00000001"

# ── 假数据 ────────────────────────────────────────
def make_wav(duration: float = 1.0, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * int(rate * duration))
    return buf.getvalue()


class _FakeWord:
    def __init__(self, i: int):
        self.word_index = i
        self.text = f"词{i}"
        self.start_time = float(i)
        self.end_time = float(i) + 0.8
        self.speaker_id = "A"

    def model_dump(self):
        return self.__dict__


FAKE_WORDS = [_FakeWord(i) for i in range(8)]

FAKE_REPORT = SimpleNamespace(
    model_dump=lambda self=None: {
        "scene_analysis": {"scene_type": "尽调访谈", "speaker_roles": "A问B答"},
        "total_score": 78,
        "total_score_deduction_reason": "wizard e2e 自动测试",
        "risk_points": [
            {
                "risk_level": "一般",
                "tier1_general_critique": "wizard风险点",
                "tier2_qa_alignment": "无偏差",
                "improvement_suggestion": "wizard建议",
                "original_text": "词0 词1",
                "start_word_index": 0,
                "end_word_index": 1,
                "score_deduction": 7,
                "deduction_reason": "wizard扣分",
                "is_manual_entry": False,
            }
        ],
        "positive_highlights": ["wizard亮点"],
    }
)

# ── Fixture ──────────────────────────────────────
@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="module", autouse=True)
def run_wizard_job(tmp_path_factory):
    """写临时 WAV → 直接调 run_pitch_wizard_track_job（mock 掉 ASR+LLM）。"""
    # 准备临时音频文件
    tmp_dir = tmp_path_factory.mktemp("wizard_audio")
    audio_file = tmp_dir / "test_track.wav"
    audio_file.write_bytes(make_wav())

    # 清理上次残留
    conn = _connect()
    conn.execute("DELETE FROM pitch_jobs WHERE job_id = ?", (JOB_ID,))
    conn.commit()
    conn.close()

    # 建 job 记录（桥接到 DB）
    job_create(JOB_ID, TENANT)

    # mock: run_pitch_file_job 返回假 words+report
    mock_run_pitch_file_job = MagicMock(return_value=(FAKE_WORDS, FAKE_REPORT))

    # mock: job_pipeline 模块（lazy import 在 runner 里）
    mock_job_pipeline = MagicMock()
    mock_job_pipeline.run_pitch_file_job = mock_run_pitch_file_job
    mock_job_pipeline.PitchFileJobParams = MagicMock(return_value=MagicMock())
    mock_job_pipeline.build_explicit_context = MagicMock(return_value={})

    mock_report_builder = MagicMock()
    mock_report_builder.HtmlExportOptions = MagicMock(return_value=MagicMock())

    with (
        # patch runner 模块命名空间内的符号（已在模块顶层 import，必须 patch 本地引用）
        patch("cangjie_fos.services.pitch_wizard_runner.run_pitch_file_job", mock_run_pitch_file_job),
        patch("cangjie_fos.services.pitch_wizard_runner.PitchFileJobParams", MagicMock(return_value=MagicMock())),
        patch("cangjie_fos.services.pitch_wizard_runner.build_explicit_context", return_value={}),
        patch("cangjie_fos.services.pitch_wizard_runner.HtmlExportOptions", MagicMock(return_value=MagicMock())),
        # institution_intel_extract 可选，直接让它静默跳过
        patch(
            "cangjie_fos.services.pitch_wizard_runner.extract_and_persist_institution_intel",
            side_effect=Exception("skip intel in test"),
            create=True,
        ),
    ):
        run_pitch_wizard_track_job(
            job_id=JOB_ID,
            tenant_id=TENANT,
            audio_path=audio_file,
            recording_label="test_track.wav",
            category="尽调",
            project_name="测试项目",
            interviewee="测试被访者",
            session_notes="",
            sniper_targets_json="",
            custom_roles_other="",
            qa_text="",
            company_background="",
            sensitive_words=[],
            hot_words=None,
            memory_company_id=TENANT,
            skip_asr_polish=True,
            use_langgraph_v1=False,
        )


# ── DB 层验证 ─────────────────────────────────────
class TestWizardDB:
    def test_status_completed(self):
        row = db_job_get(JOB_ID)
        assert row is not None
        assert row["status"] == "completed", f"状态异常: {row['status']}"

    def test_original_report_written(self):
        row = db_job_get(JOB_ID)
        report = row.get("original_report")
        assert isinstance(report, dict), "original_report 未写入 SQLite"
        assert report["total_score"] == 78

    def test_words_json_written(self):
        row = db_job_get(JOB_ID)
        words = row.get("words_json")
        assert isinstance(words, list) and len(words) == 8, "words_json 未写入"

    def test_audio_path_permanent(self):
        row = db_job_get(JOB_ID)
        audio_path = row.get("audio_path")
        assert audio_path, "audio_path 未写入"
        assert Path(audio_path).exists(), f"永久音频文件不存在: {audio_path}"


# ── Review API 验证（这正是「数据异常」的来源）───────
class TestWizardReviewAPI:
    def test_review_200(self, client):
        r = client.get(f"/api/pitch/jobs/{JOB_ID}/review")
        assert r.status_code == 200, r.text

    def test_review_has_report(self, client):
        data = client.get(f"/api/pitch/jobs/{JOB_ID}/review").json()
        assert data["original_report"] is not None, "original_report 为 null → 会触发「数据异常」"
        assert data["original_report"]["total_score"] == 78

    def test_review_words_summary(self, client):
        data = client.get(f"/api/pitch/jobs/{JOB_ID}/review").json()
        assert data["words_summary"]["total_words"] == 8

    def test_review_audio_available(self, client):
        data = client.get(f"/api/pitch/jobs/{JOB_ID}/review").json()
        assert data["audio_available"] is True

    def test_review_status_completed(self, client):
        data = client.get(f"/api/pitch/jobs/{JOB_ID}/review").json()
        assert data["status"] == "completed"

    def test_words_api(self, client):
        r = client.get(f"/api/pitch/jobs/{JOB_ID}/words")
        assert r.status_code == 200
        assert len(r.json()) == 8
