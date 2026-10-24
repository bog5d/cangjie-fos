"""
Pipeline 端到端集成测试。

外部服务（ASR、LLM）全部 mock，只测真实的：
  - 音频压缩 + 文件落盘
  - DB 状态流转（TRANSCRIBING → EVALUATING → COMPLETED）
  - words_json / audio_path / original_report 写入 SQLite
  - GET /review 返回 words_summary 和 original_report
  - GET /words  返回词列表
  - GET /audio  返回 206/200 音频流

运行：
  uv run --extra dev pytest tests/test_pipeline_e2e.py -v
"""
from __future__ import annotations

import io
import time
import wave
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.real_db]

from cangjie_fos.main import create_app
from cangjie_fos.services.pitch_job_db import db_job_get
from cangjie_fos.services.pitch_upload_pipeline import run_pitch_upload_job

# ──────────────────────────────────────────────
# 测试用常量
# ──────────────────────────────────────────────
TENANT = "test-tenant-e2e"
JOB_ID = "e2e-test-job-00000001"


# ──────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────
def make_wav_bytes(duration_sec: float = 1.0, sample_rate: int = 16000) -> bytes:
    """生成最小合法 WAV 文件（单声道 16-bit PCM 静音）。"""
    buf = io.BytesIO()
    n_frames = int(sample_rate * duration_sec)
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)
    return buf.getvalue()


def make_fake_words(count: int = 5):
    """生成假的 TranscriptionWord 对象列表。"""
    from pydantic import BaseModel

    class FakeWord(BaseModel):
        word_index: int
        text: str
        start_time: float
        end_time: float
        speaker_id: str = "A"

        def model_dump(self):  # noqa: D102
            return self.__dict__

    return [
        FakeWord(
            word_index=i,
            text=f"词{i}",
            start_time=float(i),
            end_time=float(i) + 0.8,
        )
        for i in range(count)
    ]


FAKE_REPORT = SimpleNamespace(
    model_dump=lambda self=None: {
        "scene_analysis": {"scene_type": "E2E测试场景", "speaker_roles": "测试角色"},
        "total_score": 80,
        "total_score_deduction_reason": "E2E自动测试扣分",
        "risk_points": [
            {
                "risk_level": "一般",
                "tier1_general_critique": "E2E风险点",
                "tier2_qa_alignment": "无偏差",
                "improvement_suggestion": "E2E建议",
                "original_text": "词0 词1",
                "start_word_index": 0,
                "end_word_index": 1,
                "score_deduction": 5,
                "deduction_reason": "E2E扣分原因",
                "is_manual_entry": False,
            }
        ],
        "positive_highlights": ["E2E亮点"],
    }
)


# ──────────────────────────────────────────────
# Fixture：共享 client，确保同一 DB
# ──────────────────────────────────────────────
@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ──────────────────────────────────────────────
# 核心测试
# ──────────────────────────────────────────────
class TestPipelineE2E:
    """全链路测试：从上传到 Review API，不需要点 UI。"""

    @pytest.fixture(autouse=True, scope="class")
    def run_job(self):
        """在所有测试前跑一次完整 pipeline（同步执行）。"""
        import sys

        fake_words = make_fake_words()
        wav_bytes = make_wav_bytes()

        with (
            patch(
                "cangjie_fos.services.pitch_upload_pipeline.AudioService.smart_compress_media",
                return_value=SimpleNamespace(data=wav_bytes),
            ),
            patch(
                "cangjie_fos.services.pitch_upload_pipeline.transcribe_audio",
                return_value=fake_words,
            ),
            patch(
                "cangjie_fos.services.pitch_upload_pipeline.PitchGraphService.run_evaluation_with_state",
                return_value=(FAKE_REPORT, {}),
            ),
        ):
            from cangjie_fos.services.pitch_job_db import db_job_create, _connect

            # 清理上次残留测试数据
            conn = _connect()
            conn.execute("DELETE FROM pitch_jobs WHERE job_id = ?", (JOB_ID,))
            conn.commit()
            conn.close()

            db_job_create(JOB_ID, TENANT)

            run_pitch_upload_job(
                job_id=JOB_ID,
                raw_bytes=wav_bytes,
                filename="e2e_test.wav",
                tenant_id=TENANT,
            )

    # ── DB 层验证 ─────────────────────────────
    def test_db_status_completed(self):
        row = db_job_get(JOB_ID)
        assert row is not None, "job 不存在于 DB"
        assert row["status"] == "completed", f"状态异常: {row['status']}"

    def test_db_words_json_persisted(self):
        row = db_job_get(JOB_ID)
        words = row.get("words_json")
        assert isinstance(words, list) and len(words) == 5, "words_json 未正确写入"

    def test_db_audio_path_exists(self):
        from pathlib import Path
        row = db_job_get(JOB_ID)
        audio_path = row.get("audio_path")
        assert audio_path and Path(audio_path).exists(), f"音频文件不存在: {audio_path}"

    def test_db_original_report_persisted(self):
        row = db_job_get(JOB_ID)
        report = row.get("original_report")
        assert isinstance(report, dict), "original_report 未写入"
        assert report.get("total_score") == 80

    # ── Review API 验证 ───────────────────────
    def test_review_api_200(self, client):
        r = client.get(f"/api/pitch/jobs/{JOB_ID}/review")
        assert r.status_code == 200, r.text

    def test_review_api_words_summary(self, client):
        data = client.get(f"/api/pitch/jobs/{JOB_ID}/review").json()
        ws = data["words_summary"]
        assert ws["total_words"] == 5
        assert ws["duration_sec"] > 0

    def test_review_api_original_report(self, client):
        data = client.get(f"/api/pitch/jobs/{JOB_ID}/review").json()
        assert data["original_report"]["total_score"] == 80
        assert data["edited_report"] is None

    # ── Wiki 摄入验证 ──────────────────────────
    def test_wiki_episode_created_for_job(self):
        """pipeline 完成后 wiki episode 应已创建（即使 LLM 返回空也会创建）。"""
        from cangjie_fos.services.pitch_job_db import db_wiki_episodes_for_source
        episodes = db_wiki_episodes_for_source(JOB_ID)
        assert isinstance(episodes, list), "wiki episodes 查询应返回 list"
        # wiki 摄入是非阻塞的；若 LLM mock 返回空，episode 仍会被创建
        assert len(episodes) >= 1, "pipeline 完成后应有至少一条 wiki episode 记录"

    def test_review_api_audio_available(self, client):
        data = client.get(f"/api/pitch/jobs/{JOB_ID}/review").json()
        assert data["audio_available"] is True

    # ── Words API 验证 ────────────────────────
    def test_words_api_returns_list(self, client):
        r = client.get(f"/api/pitch/jobs/{JOB_ID}/words")
        assert r.status_code == 200
        words = r.json()
        assert isinstance(words, list) and len(words) == 5

    def test_words_api_structure(self, client):
        words = client.get(f"/api/pitch/jobs/{JOB_ID}/words").json()
        w = words[0]
        assert "word_index" in w and "start_time" in w and "end_time" in w

    # ── Audio API 验证 ────────────────────────
    def test_audio_api_returns_audio(self, client):
        r = client.get(f"/api/pitch/jobs/{JOB_ID}/audio")
        assert r.status_code in (200, 206), f"音频 API 异常: {r.status_code}"
        assert "audio" in r.headers.get("content-type", "")

    # ── PATCH commit 验证 ─────────────────────
    def test_commit_edited_report(self, client):
        edited = FAKE_REPORT.model_dump()
        edited["total_score"] = 75
        r = client.patch(
            f"/api/pitch/jobs/{JOB_ID}/review",
            json={"edited_report": edited},
        )
        assert r.status_code == 200
        data = r.json()
        assert "committed_at" in data

    def test_edited_report_persisted(self, client):
        data = client.get(f"/api/pitch/jobs/{JOB_ID}/review").json()
        assert data["edited_report"]["total_score"] == 75
        assert data["committed_at"] is not None
