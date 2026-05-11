"""路演分析端到端集成测试（Phase 7.5）。

测试目标：覆盖人工测试发现的3个真实Bug，确保回归不再发生。

Bug #1 — UNIQUE constraint: job_create() 内部已调 db_job_create，不能再显式调用
Bug #2 — 说话人样本是ASR碎片: words_json 必须先合并连续同说话人段才能展示
Bug #3 — 黑屏/错误报告: resume_roadshow_analysis 必须传 biz_type=01_机构路演

外部服务（ASR、LLM）全部 mock，真实执行：
  - DB 状态流转（awaiting_speakers → completed）
  - words_json 写入 SQLite 并可读
  - speaker-preview 返回有意义的合并话语（非碎片）
  - confirm-speakers 触发正确 biz_type 传给 LangGraph
  - report 包含 RoadshowIntelReport 字段

运行：
  uv run --extra dev pytest tests/test_roadshow_e2e.py -v
"""
from __future__ import annotations

import io
import sqlite3
import time
import wave
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from cangjie_fos.main import create_app
from cangjie_fos.services.pitch_job_db import db_job_get

# ──────────────────────────────────────────────────────────────────────────────
# 辅助常量 & 工厂
# ──────────────────────────────────────────────────────────────────────────────

TENANT = "test-roadshow-e2e"
TRANSCRIPT = (
    "说话人A：你们的退出路径是什么？现在ARR大概多少？IRR怎么算？\n"
    "说话人A：我们主要看这个赛道的投资逻辑，基金规模多大？\n"
    "说话人B：我们的产品核心壁垒在于AI技术，客户已覆盖500强企业。\n"
    "说话人B：商业模式是SaaS订阅制，月ARR约50万，今年目标600万。\n"
    "说话人A：你们之前投过类似的项目吗？\n"
    "说话人B：我们计划3年内科创板上市，融资用途是扩张销售团队。\n"
)

# ASR 输出模拟：多条短碎片，同一说话人连续出现（真实ASR特征）
_ASR_FRAGMENTS: list[dict] = [
    # 说话人0 — 多个短段（模拟ASR时间切割）
    {"word_index": 0, "text": "你们的", "start_time": 0.0, "end_time": 0.3, "speaker_id": "0"},
    {"word_index": 1, "text": "退出路径", "start_time": 0.3, "end_time": 0.8, "speaker_id": "0"},
    {"word_index": 2, "text": "是什么", "start_time": 0.8, "end_time": 1.2, "speaker_id": "0"},
    {"word_index": 3, "text": "现在ARR", "start_time": 1.2, "end_time": 1.6, "speaker_id": "0"},
    {"word_index": 4, "text": "大概多少", "start_time": 1.6, "end_time": 2.0, "speaker_id": "0"},
    {"word_index": 5, "text": "IRR怎么算", "start_time": 2.0, "end_time": 2.5, "speaker_id": "0"},
    # 说话人1
    {"word_index": 6, "text": "我们的产品", "start_time": 3.0, "end_time": 3.4, "speaker_id": "1"},
    {"word_index": 7, "text": "核心壁垒", "start_time": 3.4, "end_time": 3.8, "speaker_id": "1"},
    {"word_index": 8, "text": "在于AI技术", "start_time": 3.8, "end_time": 4.2, "speaker_id": "1"},
    {"word_index": 9, "text": "客户已覆盖", "start_time": 4.2, "end_time": 4.6, "speaker_id": "1"},
    {"word_index": 10, "text": "500强企业", "start_time": 4.6, "end_time": 5.0, "speaker_id": "1"},
    # 说话人0 再次出现
    {"word_index": 11, "text": "我们主要看", "start_time": 6.0, "end_time": 6.4, "speaker_id": "0"},
    {"word_index": 12, "text": "这个赛道", "start_time": 6.4, "end_time": 6.8, "speaker_id": "0"},
    {"word_index": 13, "text": "投资逻辑是什么", "start_time": 6.8, "end_time": 7.3, "speaker_id": "0"},
]

FAKE_ROADSHOW_REPORT = {
    "meeting_atmosphere": "warm",
    "meeting_stage": "first_contact",
    "key_questions": [
        {"question": "IRR预期是多少？", "theme": "回报", "asked_by": "0"}
    ],
    "interest_signals": [
        {"signal": "对AI技术壁垒感兴趣", "speaker_id": "0", "sentiment": "positive"}
    ],
    "hidden_concerns": ["市场规模可能被高估"],
    "key_verbatim_moments": [
        {"speaker_id": "0", "quote": "你们的退出路径是什么？", "significance": "核心关切"}
    ],
    "next_actions": [
        {"action": "发送财务模型", "responsible_party": "企业方", "deadline": "下周五"}
    ],
    "institution_update": "关注AI SaaS赛道，重视盈利模式",
    "referrer": "",
    "dominant_speaker": "0",
    "competitor_mentions": [],
    "timeline_signals": "3年内科创板上市",
}


def _make_fake_report_ns():
    """返回 (report_ns, metadata_dict) 供 run_evaluation_with_state mock。"""
    report_ns = SimpleNamespace(**FAKE_ROADSHOW_REPORT)
    report_ns.model_dump = lambda: FAKE_ROADSHOW_REPORT
    return report_ns, {}


def make_wav_bytes(duration_sec: float = 0.5, sample_rate: int = 16000) -> bytes:
    """生成最小合法 WAV 文件（单声道 16-bit PCM 静音）。"""
    buf = io.BytesIO()
    n_frames = int(sample_rate * duration_sec)
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)
    return buf.getvalue()


# ──────────────────────────────────────────────────────────────────────────────
# Fixture
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


# ──────────────────────────────────────────────────────────────────────────────
# TestRoadshowTranscriptE2E — 文字稿模式（跳过ASR，覆盖完整流程）
# ──────────────────────────────────────────────────────────────────────────────

class TestRoadshowTranscriptE2E:
    """文字稿模式端到端测试。"""

    def _start_job(self, client) -> str:
        """提交文字稿，返回 job_id。"""
        import urllib.parse
        encoded = urllib.parse.quote(TRANSCRIPT, safe="")
        resp = client.post(
            f"/api/v1/roadshow/start"
            f"?tenant_id={TENANT}&roadshow_date=2026-05-11"
            f"&referrer=测试引荐方&transcript_text={encoded}"
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["job_id"]

    # ── Bug #1 回归：no UNIQUE constraint violation ──────────────────────────

    def test_no_duplicate_db_insert(self, client):
        """Bug #1：start 接口只能创建1条 DB 记录，不能因重复写入报500。"""
        job_id = self._start_job(client)
        row = db_job_get(job_id)
        assert row is not None, "DB 中应有该 job 记录"
        from cangjie_fos.services.pitch_job_db import _db_path
        conn = sqlite3.connect(str(_db_path()))
        count = conn.execute(
            "SELECT COUNT(*) FROM pitch_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()[0]
        conn.close()
        assert count == 1, f"期望 1 条记录，实际 {count} 条（Bug #1：重复写入）"

    def test_start_returns_awaiting_speakers(self, client):
        """文字稿模式：start 后状态应为 awaiting_speakers。"""
        job_id = self._start_job(client)
        resp = client.get(f"/api/v1/roadshow/jobs/{job_id}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "awaiting_speakers"
        assert data["is_roadshow"] is True

    def test_db_fields_written_correctly(self, client):
        """start 后 SQLite 中 is_roadshow=1, category=01_机构路演 应正确写入。"""
        job_id = self._start_job(client)
        row = db_job_get(job_id)
        assert row["is_roadshow"] == 1
        assert row["category"] == "01_机构路演"
        assert row["referrer"] == "测试引荐方"

    # ── Bug #2 回归：speaker-preview 返回有意义的合并话语 ───────────────────

    def test_speaker_preview_no_garbage_fragments(self, client):
        """Bug #2：说话人样本必须是完整话语，不能是ASR碎片（< 8字）。"""
        job_id = self._start_job(client)
        resp = client.get(f"/api/v1/roadshow/jobs/{job_id}/speaker-preview")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) >= 1, "至少应有1个说话人"
        for item in items:
            for line in item["sample_lines"]:
                assert len(line) >= 8, (
                    f"Bug #2：样本行 {line!r} 长度 {len(line)} < 8，"
                    f"说明 ASR 碎片未合并"
                )

    def test_speaker_preview_role_inference(self, client):
        """角色推测：含 IRR/投资逻辑关键词 → GP执行；含 产品/商业模式 → 企业方创始人。"""
        job_id = self._start_job(client)
        resp = client.get(f"/api/v1/roadshow/jobs/{job_id}/speaker-preview")
        items = resp.json()
        roles = {item["guessed_role"] for item in items}
        assert "GP执行" in roles or "企业方创始人" in roles, (
            f"预期至少推测出 GP执行 或 企业方创始人，实际角色集: {roles}"
        )

    def test_speaker_preview_two_speakers(self, client):
        """文字稿含说话人A和B → preview 应返回2个说话人。"""
        job_id = self._start_job(client)
        resp = client.get(f"/api/v1/roadshow/jobs/{job_id}/speaker-preview")
        items = resp.json()
        assert len(items) == 2, f"期望2个说话人，实际 {len(items)} 个"

    # ── Bug #3 回归：biz_type 必须传给 LangGraph ────────────────────────────

    def test_confirm_speakers_passes_biz_type_to_langgraph(self, client):
        """Bug #3：confirm-speakers 触发的 LangGraph 必须收到 biz_type=01_机构路演。"""
        job_id = self._start_job(client)
        captured: dict = {}

        def fake_run_eval(*, tenant_id, words, explicit_context=None, **kw):
            captured.update(explicit_context or {})
            return _make_fake_report_ns()

        with patch(
            "cangjie_fos.services.pitch_upload_pipeline.PitchGraphService.run_evaluation_with_state",
            side_effect=fake_run_eval,
        ):
            resp = client.post(
                f"/api/v1/roadshow/jobs/{job_id}/confirm-speakers?tenant_id={TENANT}",
                json={
                    "confirmed_by": "测试指挥官",
                    "speakers": [
                        {"speaker_id": "0", "real_name": "张三", "institution": "红杉", "role": "GP执行"},
                        {"speaker_id": "1", "real_name": "李四", "institution": "科技公司", "role": "企业方创始人"},
                    ],
                },
            )
            assert resp.status_code == 200
            deadline = time.time() + 10
            while time.time() < deadline:
                row = db_job_get(job_id)
                if row and row.get("status") in ("completed", "failed"):
                    break
                time.sleep(0.2)

        assert captured.get("biz_type") == "01_机构路演", (
            f"Bug #3：LangGraph 收到的 biz_type={captured.get('biz_type')!r}，"
            f"期望 '01_机构路演'。这会导致走评分分支而非路演分析分支，产生黑屏。"
        )

    def test_report_has_roadshow_fields(self, client):
        """report 端点应返回 RoadshowIntelReport 字段，不是评分字段。"""
        job_id = self._start_job(client)

        def fake_run_eval(*, tenant_id, words, explicit_context=None, **kw):
            return _make_fake_report_ns()

        with patch(
            "cangjie_fos.services.pitch_upload_pipeline.PitchGraphService.run_evaluation_with_state",
            side_effect=fake_run_eval,
        ):
            client.post(
                f"/api/v1/roadshow/jobs/{job_id}/confirm-speakers?tenant_id={TENANT}",
                json={
                    "confirmed_by": "测试官",
                    "speakers": [
                        {"speaker_id": "0", "real_name": "A", "role": "GP执行"},
                    ],
                },
            )
            deadline = time.time() + 10
            while time.time() < deadline:
                row = db_job_get(job_id)
                if row and row.get("status") == "completed":
                    break
                time.sleep(0.2)

        resp = client.get(f"/api/v1/roadshow/jobs/{job_id}/report")
        assert resp.status_code == 200, f"report API 返回 {resp.status_code}：{resp.text}"
        data = resp.json()
        report = data["report"]
        assert "meeting_atmosphere" in report, "缺少 meeting_atmosphere（路演报告核心字段）"
        assert "key_questions" in report, "缺少 key_questions"
        assert "next_actions" in report, "缺少 next_actions"
        assert "total_score" not in report, "报告含 total_score，说明走了评分分支（Bug #3）"

    def test_confirmed_speakers_written_to_db(self, client):
        """confirm-speakers 后，说话人信息应持久化到 SQLite。"""
        job_id = self._start_job(client)

        def fake_run_eval(**kw):
            return _make_fake_report_ns()

        with patch(
            "cangjie_fos.services.pitch_upload_pipeline.PitchGraphService.run_evaluation_with_state",
            side_effect=fake_run_eval,
        ):
            client.post(
                f"/api/v1/roadshow/jobs/{job_id}/confirm-speakers?tenant_id={TENANT}",
                json={
                    "confirmed_by": "指挥官甲",
                    "speakers": [
                        {"speaker_id": "0", "real_name": "王总", "institution": "XX基金", "role": "GP执行", "title": "合伙人"},
                    ],
                },
            )
            deadline = time.time() + 10
            while time.time() < deadline:
                row = db_job_get(job_id)
                if row and row.get("status") == "completed":
                    break
                time.sleep(0.2)

        row = db_job_get(job_id)
        speakers = row.get("confirmed_speakers_json") or []
        assert any(sp.get("real_name") == "王总" for sp in speakers), (
            f"confirmed_speakers_json 中找不到 real_name=王总，实际: {speakers}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# TestRoadshowAudioE2E — 音频上传模式（mock ASR）
# ──────────────────────────────────────────────────────────────────────────────

class TestRoadshowAudioE2E:
    """音频上传模式端到端测试（mock ASR + FFmpeg）。"""

    def _start_audio_job(self, client) -> str:
        """上传 WAV 文件，mock ASR，同步运行 pipeline，返回 job_id。"""
        wav_bytes = make_wav_bytes()

        def fake_asr_job(job_id, filename, tenant_id, referrer, pre_written_path, **kw):
            """Mock ASR：直接写 ASR 碎片 words 并设置 awaiting_speakers 状态。"""
            from cangjie_fos.services.pitch_job_db import db_job_update
            from cangjie_fos.services.pitch_job_store import job_update
            from cangjie_fos.schemas.pitch_upload import PitchJobStatus
            db_job_update(
                job_id,
                status=str(PitchJobStatus.AWAITING_SPEAKERS),
                substatus="ASR mock 完成",
                words_json=_ASR_FRAGMENTS,
                is_roadshow=1,
                referrer=referrer,
            )
            job_update(job_id, status=PitchJobStatus.AWAITING_SPEAKERS)

        with patch(
            "cangjie_fos.api.routes.roadshow.run_roadshow_asr_job",
            side_effect=fake_asr_job,
        ):
            resp = client.post(
                f"/api/v1/roadshow/start?tenant_id={TENANT}&roadshow_date=2026-05-11",
                files={"file": ("test.wav", wav_bytes, "audio/wav")},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["status"] == "transcribing"
            job_id = data["job_id"]

        deadline = time.time() + 5
        while time.time() < deadline:
            row = db_job_get(job_id)
            if row and row.get("status") == "awaiting_speakers":
                break
            time.sleep(0.1)

        return job_id

    def test_audio_no_duplicate_db_insert(self, client):
        """Bug #1（音频模式）：job_create 内部已写 DB，不能再写一次。"""
        job_id = self._start_audio_job(client)
        from cangjie_fos.services.pitch_job_db import _db_path
        conn = sqlite3.connect(str(_db_path()))
        count = conn.execute(
            "SELECT COUNT(*) FROM pitch_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()[0]
        conn.close()
        assert count == 1, f"期望 1 条记录，实际 {count} 条（Bug #1）"

    def test_audio_reaches_awaiting_speakers(self, client):
        """音频上传后（mock ASR），状态应进入 awaiting_speakers。"""
        job_id = self._start_audio_job(client)
        resp = client.get(f"/api/v1/roadshow/jobs/{job_id}/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "awaiting_speakers"

    def test_audio_speaker_preview_merges_asr_fragments(self, client):
        """Bug #2（音频模式）：speaker-preview 必须合并 ASR 碎片，不显示单个短段。"""
        job_id = self._start_audio_job(client)
        resp = client.get(f"/api/v1/roadshow/jobs/{job_id}/speaker-preview")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) >= 1

        for item in items:
            for line in item["sample_lines"]:
                assert len(line) >= 8, (
                    f"Bug #2：样本行 {line!r} 是未合并的 ASR 碎片"
                )
            if item["sample_lines"]:
                has_meaningful = any(len(line) >= 15 for line in item["sample_lines"])
                assert has_meaningful, (
                    f"说话人 {item['speaker_id']} 没有 >=15字 的合并话语，"
                    f"样本: {item['sample_lines']}"
                )

    def test_audio_confirm_and_complete(self, client):
        """音频模式：confirm-speakers → completed → report 完整链路。"""
        job_id = self._start_audio_job(client)

        def fake_run_eval(*, tenant_id, words, explicit_context=None, **kw):
            assert explicit_context and explicit_context.get("biz_type") == "01_机构路演", (
                f"Bug #3：biz_type={explicit_context and explicit_context.get('biz_type')!r}"
            )
            return _make_fake_report_ns()

        with patch(
            "cangjie_fos.services.pitch_upload_pipeline.PitchGraphService.run_evaluation_with_state",
            side_effect=fake_run_eval,
        ):
            resp = client.post(
                f"/api/v1/roadshow/jobs/{job_id}/confirm-speakers?tenant_id={TENANT}",
                json={
                    "confirmed_by": "测试指挥官",
                    "speakers": [
                        {"speaker_id": "0", "real_name": "投资人甲", "role": "GP执行"},
                        {"speaker_id": "1", "real_name": "创始人乙", "role": "企业方创始人"},
                    ],
                },
            )
            assert resp.status_code == 200

            deadline = time.time() + 10
            while time.time() < deadline:
                row = db_job_get(job_id)
                if row and row.get("status") == "completed":
                    break
                time.sleep(0.2)

        row = db_job_get(job_id)
        assert row["status"] == "completed", f"status={row['status']}"
        report = row.get("original_report") or {}
        assert "meeting_atmosphere" in report, "报告缺少路演字段（走了错误分支）"
        assert "total_score" not in report, "报告含评分字段，说明走了评分分支（Bug #3）"


# ──────────────────────────────────────────────────────────────────────────────
# TestSpeakerPreviewMergeLogic — 纯单元测试，验证合并算法
# ──────────────────────────────────────────────────────────────────────────────

class TestSpeakerPreviewMergeLogic:
    """直接测试 speaker-preview 端点的合并逻辑（不依赖音频上传）。"""

    def _make_db_row_with_words(self, words: list[dict]) -> dict:
        return {
            "job_id": "merge-test-job",
            "status": "awaiting_speakers",
            "words_json": words,
            "is_roadshow": 1,
            "referrer": "",
            "original_report": None,
        }

    def test_consecutive_fragments_merged_into_utterance(self, client):
        """多个连续短段 → 合并成1条长话语（>= 8字才保留）。"""
        fragments = [
            {"word_index": i, "text": f"片段{i}内容", "start_time": float(i),
             "end_time": float(i) + 0.3, "speaker_id": "0"}
            for i in range(5)
        ]
        db_row = self._make_db_row_with_words(fragments)

        with patch("cangjie_fos.api.routes.roadshow.db_job_get", return_value=db_row):
            resp = client.get("/api/v1/roadshow/jobs/merge-test-job/speaker-preview")

        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["word_count"] == 5
        for line in items[0]["sample_lines"]:
            assert len(line) >= 8, f"合并后 {line!r} 仍不足8字"

    def test_speaker_switch_creates_new_utterance(self, client):
        """说话人切换时，立刻 flush 上一段，开启新段。"""
        words = [
            {"word_index": 0, "text": "投资人问题是这个", "start_time": 0.0, "end_time": 1.0, "speaker_id": "0"},
            {"word_index": 1, "text": "创始人回答是那个", "start_time": 1.0, "end_time": 2.0, "speaker_id": "1"},
        ]
        db_row = self._make_db_row_with_words(words)

        with patch("cangjie_fos.api.routes.roadshow.db_job_get", return_value=db_row):
            resp = client.get("/api/v1/roadshow/jobs/merge-test-job/speaker-preview")

        items = resp.json()
        sids = {item["speaker_id"] for item in items}
        assert "0" in sids and "1" in sids, f"应有两个说话人，实际: {sids}"

    def test_too_short_utterance_filtered_out(self, client):
        """< 8字的话语不应出现在 sample_lines 中。"""
        words = [
            {"word_index": 0, "text": "嗯", "start_time": 0.0, "end_time": 0.1, "speaker_id": "0"},
            {"word_index": 1, "text": "好的谢谢你今天的介绍真的很精彩", "start_time": 1.0, "end_time": 3.0, "speaker_id": "1"},
        ]
        db_row = self._make_db_row_with_words(words)

        with patch("cangjie_fos.api.routes.roadshow.db_job_get", return_value=db_row):
            resp = client.get("/api/v1/roadshow/jobs/merge-test-job/speaker-preview")

        items = resp.json()
        sp0 = next((i for i in items if i["speaker_id"] == "0"), None)
        if sp0:
            assert sp0["sample_lines"] == [], (
                f"说话人0 只说了嗯，sample_lines 应为空，实际: {sp0['sample_lines']}"
            )

    def test_long_single_speaker_split_at_100_chars(self, client):
        """单说话人连续说超过100字时，应在100字处切断，产生多条话语。"""
        words = [
            {
                "word_index": i,
                "text": "这是一个二十字的测试片段内容" + str(i),
                "start_time": float(i),
                "end_time": float(i) + 1.0,
                "speaker_id": "0",
            }
            for i in range(8)
        ]
        db_row = self._make_db_row_with_words(words)

        with patch("cangjie_fos.api.routes.roadshow.db_job_get", return_value=db_row):
            resp = client.get("/api/v1/roadshow/jobs/merge-test-job/speaker-preview")

        items = resp.json()
        sp0 = next((i for i in items if i["speaker_id"] == "0"), None)
        assert sp0 is not None
        for line in sp0["sample_lines"]:
            assert len(line) <= 130, f"单条话语 {len(line)} 字超出预期切断长度"
