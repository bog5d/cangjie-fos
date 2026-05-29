"""路演分析 API 测试（Phase 7.5）。

测试范围：
  POST /api/v1/roadshow/start          — 文字稿模式（跳过ASR）
  GET  /api/v1/roadshow/jobs/{id}/status
  GET  /api/v1/roadshow/jobs/{id}/speaker-preview
  POST /api/v1/roadshow/jobs/{id}/confirm-speakers
  GET  /api/v1/roadshow/jobs/{id}/report

所有 DB 调用通过 monkeypatch 隔离，不触碰真实 SQLite。
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from cangjie_fos.main import app

client = TestClient(app)

# ── 辅助数据 ──────────────────────────────────────────────────────────────────

_JOB_ID = "roadshow-test-job-001"
_TENANT = "test-tenant"

_WORDS_JSON = [
    {"word_index": 0, "text": "我们主要看这个赛道的IRR回报", "start_time": 0.0, "end_time": 0.0, "speaker_id": "0"},
    {"word_index": 1, "text": "投资逻辑是什么", "start_time": 0.0, "end_time": 0.0, "speaker_id": "0"},
    {"word_index": 2, "text": "我们的产品核心壁垒在于AI技术", "start_time": 0.0, "end_time": 0.0, "speaker_id": "1"},
    {"word_index": 3, "text": "商业模式是SaaS订阅制", "start_time": 0.0, "end_time": 0.0, "speaker_id": "1"},
    {"word_index": 4, "text": "我们的客户覆盖500强", "start_time": 0.0, "end_time": 0.0, "speaker_id": "1"},
]

_AWAITING_ROW: dict[str, Any] = {
    "job_id": _JOB_ID,
    "tenant_id": _TENANT,
    "status": "awaiting_speakers",
    "substatus": "文字稿解析完成",
    "is_roadshow": 1,
    "referrer": "红杉推荐",
    "original_report": None,
    "confirmed_speakers_json": None,
    "interviewee": "路演_2026-05-11",
    "created_at": 1_715_000_000.0,
    "words_json": _WORDS_JSON,
}

_COMPLETED_ROW: dict[str, Any] = {
    **_AWAITING_ROW,
    "status": "completed",
    "original_report": {
        "meeting_atmosphere": "warm",
        "meeting_stage": "first_contact",
        "key_questions": [{"question": "IRR预期是多少？", "theme": "回报", "asked_by": "0"}],
        "interest_signals": [{"signal": "对AI技术壁垒感兴趣", "speaker_id": "0", "sentiment": "positive"}],
        "hidden_concerns": ["市场规模可能被高估"],
        "key_verbatim_moments": [{"speaker_id": "0", "text": "这个赛道IRR回报怎么算", "significance": "核心关切"}],
        "institution_update": "该机构重点看AI+SaaS赛道",
        "next_actions": [{"action": "发送财务模型", "owner": "企业方", "deadline": "本周内", "priority": "high"}],
        "referrer": "红杉推荐",
        "dominant_speaker": "0",
        "competitor_mentions": ["某竞品A"],
        "timeline_signals": "Q3前完成决策",
    },
    "confirmed_speakers_json": [
        {"speaker_id": "0", "real_name": "张明", "institution": "某VC", "role": "GP执行", "title": "合伙人"},
        {"speaker_id": "1", "real_name": "王磊", "institution": "我司", "role": "企业方创始人", "title": "CEO"},
    ],
}


# ── 测试：POST /start（文字稿模式）────────────────────────────────────────────

class TestRoadshowStart:
    def test_start_with_transcript_returns_awaiting(self, monkeypatch):
        """文字稿模式跳过ASR，直接进入 awaiting_speakers 状态。"""
        import urllib.parse

        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_create", lambda *a, **kw: None
        )
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_update", lambda *a, **kw: None
        )
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.job_create", lambda *a, **kw: None
        )
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.job_update", lambda *a, **kw: None
        )

        transcript = "说话人A：你们的IRR预期是多少？\n说话人B：我们预期30%以上"
        encoded = urllib.parse.quote(transcript, safe="")
        resp = client.post(
            f"/api/v1/roadshow/start"
            f"?tenant_id={_TENANT}&roadshow_date=2026-05-11&transcript_text={encoded}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "awaiting_speakers"
        assert "job_id" in data
        assert "message" in data

    def test_start_without_file_or_transcript_returns_400(self, monkeypatch):
        """既无文件又无文字稿时返回400。"""
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_create", lambda *a, **kw: None
        )
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.job_create", lambda *a, **kw: None
        )
        resp = client.post(
            f"/api/v1/roadshow/start?tenant_id={_TENANT}&roadshow_date=2026-05-11"
        )
        assert resp.status_code == 400


# ── 测试：GET /jobs/{id}/status ───────────────────────────────────────────────

class TestRoadshowJobStatus:
    def test_status_returns_correct_fields(self, monkeypatch):
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_get",
            lambda jid: _AWAITING_ROW if jid == _JOB_ID else None,
        )
        resp = client.get(f"/api/v1/roadshow/jobs/{_JOB_ID}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "awaiting_speakers"
        assert data["is_roadshow"] is True
        assert data["referrer"] == "红杉推荐"
        assert data["has_report"] is False

    def test_status_404_unknown_job(self, monkeypatch):
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_get", lambda jid: None
        )
        resp = client.get(f"/api/v1/roadshow/jobs/nonexistent/status")
        assert resp.status_code == 404


# ── 测试：GET /jobs/{id}/speaker-preview ──────────────────────────────────────

class TestSpeakerPreview:
    def test_speaker_preview_returns_items(self, monkeypatch):
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_get",
            lambda jid: _AWAITING_ROW if jid == _JOB_ID else None,
        )
        resp = client.get(f"/api/v1/roadshow/jobs/{_JOB_ID}/speaker-preview")
        assert resp.status_code == 200
        items = resp.json()
        assert isinstance(items, list)
        assert len(items) == 2  # speaker_id 0 和 1

        sids = {item["speaker_id"] for item in items}
        assert "0" in sids
        assert "1" in sids

    def test_speaker_preview_has_guessed_role(self, monkeypatch):
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_get",
            lambda jid: _AWAITING_ROW if jid == _JOB_ID else None,
        )
        resp = client.get(f"/api/v1/roadshow/jobs/{_JOB_ID}/speaker-preview")
        items = resp.json()
        for item in items:
            assert "guessed_role" in item
            assert "guess_reason" in item
            assert "sample_lines" in item
            assert "word_count" in item
            assert item["word_count"] > 0

    def test_speaker_preview_role_inference_investor(self, monkeypatch):
        """说话人0台词含投资关键词，应推测为GP执行。"""
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_get",
            lambda jid: _AWAITING_ROW if jid == _JOB_ID else None,
        )
        resp = client.get(f"/api/v1/roadshow/jobs/{_JOB_ID}/speaker-preview")
        items = resp.json()
        sp0 = next(i for i in items if i["speaker_id"] == "0")
        # 含 IRR、赛道、投资逻辑 → 应被推测为 GP执行
        assert sp0["guessed_role"] == "GP执行"

    def test_speaker_preview_role_inference_company(self, monkeypatch):
        """说话人1台词含企业方关键词，应推测为企业方创始人。"""
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_get",
            lambda jid: _AWAITING_ROW if jid == _JOB_ID else None,
        )
        resp = client.get(f"/api/v1/roadshow/jobs/{_JOB_ID}/speaker-preview")
        items = resp.json()
        sp1 = next(i for i in items if i["speaker_id"] == "1")
        # 含 产品、商业模式、客户 → 应被推测为企业方创始人
        assert sp1["guessed_role"] == "企业方创始人"

    def test_speaker_preview_404_unknown_job(self, monkeypatch):
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_get", lambda jid: None
        )
        resp = client.get(f"/api/v1/roadshow/jobs/nonexistent/speaker-preview")
        assert resp.status_code == 404

    def test_speaker_preview_400_wrong_status(self, monkeypatch):
        """状态不是 awaiting_speakers/completed 时返回400。"""
        row = {**_AWAITING_ROW, "status": "pending"}
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_get", lambda jid: row
        )
        resp = client.get(f"/api/v1/roadshow/jobs/{_JOB_ID}/speaker-preview")
        assert resp.status_code == 400


# ── 测试：POST /jobs/{id}/confirm-speakers ────────────────────────────────────

class TestConfirmSpeakers:
    _speakers = [
        {"speaker_id": "0", "real_name": "张明", "institution": "某VC", "role": "GP执行", "title": "合伙人"},
        {"speaker_id": "1", "real_name": "王磊", "institution": "我司", "role": "企业方创始人", "title": "CEO"},
    ]

    def test_confirm_speakers_triggers_analysis(self, monkeypatch):
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_get",
            lambda jid: _AWAITING_ROW if jid == _JOB_ID else None,
        )
        # resume_roadshow_analysis 是 BackgroundTask，不需要真正运行
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.resume_roadshow_analysis",
            lambda **kw: None,
        )
        resp = client.post(
            f"/api/v1/roadshow/jobs/{_JOB_ID}/confirm-speakers?tenant_id={_TENANT}",
            json={"confirmed_by": "王波", "speakers": self._speakers},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["job_id"] == _JOB_ID

    def test_confirm_speakers_400_empty_confirmed_by(self, monkeypatch):
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_get",
            lambda jid: _AWAITING_ROW if jid == _JOB_ID else None,
        )
        resp = client.post(
            f"/api/v1/roadshow/jobs/{_JOB_ID}/confirm-speakers?tenant_id={_TENANT}",
            json={"confirmed_by": "   ", "speakers": self._speakers},
        )
        assert resp.status_code == 400

    def test_confirm_speakers_400_wrong_status(self, monkeypatch):
        row = {**_AWAITING_ROW, "status": "completed"}
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_get", lambda jid: row
        )
        resp = client.post(
            f"/api/v1/roadshow/jobs/{_JOB_ID}/confirm-speakers?tenant_id={_TENANT}",
            json={"confirmed_by": "王波", "speakers": self._speakers},
        )
        assert resp.status_code == 400

    def test_confirm_speakers_404_unknown_job(self, monkeypatch):
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_get", lambda jid: None
        )
        resp = client.post(
            f"/api/v1/roadshow/jobs/nonexistent/confirm-speakers?tenant_id={_TENANT}",
            json={"confirmed_by": "王波", "speakers": []},
        )
        assert resp.status_code == 404

    def test_confirm_speakers_invalid_role_normalized_to_qita(self, monkeypatch):
        """非法角色值应被规范化为"其他"，而不是报错。"""
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_get",
            lambda jid: _AWAITING_ROW if jid == _JOB_ID else None,
        )
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.resume_roadshow_analysis",
            lambda **kw: None,
        )
        speakers_with_invalid_role = [
            {**self._speakers[0], "role": "外星人"},
            self._speakers[1],
        ]
        resp = client.post(
            f"/api/v1/roadshow/jobs/{_JOB_ID}/confirm-speakers?tenant_id={_TENANT}",
            json={"confirmed_by": "王波", "speakers": speakers_with_invalid_role},
        )
        # 应该成功，非法角色被静默规范化为"其他"
        assert resp.status_code == 200


# ── 测试：GET /jobs/{id}/report ───────────────────────────────────────────────

class TestRoadshowReport:
    def test_report_returns_full_structure(self, monkeypatch):
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_get",
            lambda jid: _COMPLETED_ROW if jid == _JOB_ID else None,
        )
        resp = client.get(f"/api/v1/roadshow/jobs/{_JOB_ID}/report")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == _JOB_ID
        assert "report" in data
        assert data["report"]["meeting_atmosphere"] == "warm"
        assert data["report"]["dominant_speaker"] == "0"
        assert "confirmed_speakers" in data
        assert isinstance(data["confirmed_speakers"], list)
        assert data["referrer"] == "红杉推荐"

    def test_report_400_not_completed(self, monkeypatch):
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_get",
            lambda jid: _AWAITING_ROW if jid == _JOB_ID else None,
        )
        resp = client.get(f"/api/v1/roadshow/jobs/{_JOB_ID}/report")
        assert resp.status_code == 400

    def test_report_404_unknown_job(self, monkeypatch):
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_get", lambda jid: None
        )
        resp = client.get(f"/api/v1/roadshow/jobs/nonexistent/report")
        assert resp.status_code == 404

    def test_report_404_no_report_field(self, monkeypatch):
        row = {**_COMPLETED_ROW, "original_report": None}
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_get", lambda jid: row
        )
        resp = client.get(f"/api/v1/roadshow/jobs/{_JOB_ID}/report")
        assert resp.status_code == 404


# ── 测试：transcript_parser 解析器 ────────────────────────────────────────────

class TestTranscriptParser:
    def test_parse_speaker_a_colon_format(self):
        from cangjie_fos.services.transcript_parser import parse_transcript_to_words
        text = "说话人A：你好，我是投资方。\n说话人B：你好，我是创始人。"
        words = parse_transcript_to_words(text)
        assert len(words) > 0
        # 两个说话人应有不同 speaker_id
        sids = {w.speaker_id for w in words}
        assert len(sids) == 2

    def test_parse_speaker_bracket_format(self):
        from cangjie_fos.services.transcript_parser import parse_transcript_to_words
        text = "[A] 我们主要关注这个赛道。\n[B] 我们的产品很有竞争力。"
        words = parse_transcript_to_words(text)
        assert len(words) > 0
        sids = {w.speaker_id for w in words}
        assert len(sids) == 2

    def test_parse_no_speaker_marks(self):
        """无说话人标记时，全部归入 speaker_id=0。"""
        from cangjie_fos.services.transcript_parser import parse_transcript_to_words
        text = "这是一段没有说话人标记的对话。大家都在讨论融资的事情。"
        words = parse_transcript_to_words(text)
        assert len(words) > 0
        sids = {w.speaker_id for w in words}
        assert sids == {"0"}

    def test_parse_empty_text(self):
        from cangjie_fos.services.transcript_parser import parse_transcript_to_words
        words = parse_transcript_to_words("")
        assert words == []

    def test_parse_preserves_word_index_order(self):
        from cangjie_fos.services.transcript_parser import parse_transcript_to_words
        text = "说话人A：第一句话。\n说话人B：第二句话，更长一些。"
        words = parse_transcript_to_words(text)
        for i, w in enumerate(words):
            assert w.word_index == i

    def test_parse_timestamps_are_zero(self):
        """文字稿来源，时间戳全为0。"""
        from cangjie_fos.services.transcript_parser import parse_transcript_to_words
        text = "A：测试内容。\nB：第二句。"
        words = parse_transcript_to_words(text)
        assert all(w.start_time == 0.0 for w in words)
        assert all(w.end_time == 0.0 for w in words)


# ── Bug 4 回归测试：路演情报 HTML 报告导出 ────────────────────────────────────

# 使用真实报告数据结构的 _COMPLETED_ROW（key_questions 等字段用 RoadshowIntelReport 格式）
_ROADSHOW_INTEL_ROW: dict[str, Any] = {
    "job_id": _JOB_ID,
    "tenant_id": _TENANT,
    "status": "completed",
    "interviewee": "路演_2026-05-11_某VC",
    "referrer": "红杉推荐",
    "created_at": 1_715_000_000.0,
    "original_report": {
        "report_type": "roadshow_intel",
        "meeting_atmosphere": "warm",
        "meeting_stage": "first_contact",
        "atmosphere_summary": "整体氛围积极，投资方展现了较强的兴趣。",
        "key_questions": [
            {
                "verbatim": "你们的IRR预期是多少？",
                "underlying_concern": "对回报预期的担忧",
                "priority": "high",
                "speaker_id": "0",
            }
        ],
        "interest_signals": [
            {
                "verbatim": "这个AI技术壁垒我们很感兴趣",
                "signal_type": "positive",
                "interpretation": "对技术壁垒的认可",
                "speaker_id": "0",
            }
        ],
        "hidden_concerns": ["市场规模可能被高估"],
        "key_verbatim_moments": ["这个赛道IRR回报怎么算？"],
        "institution_update": "该机构重点看AI+SaaS赛道",
        "next_actions": [
            {
                "action": "发送财务模型",
                "actor": "企业方",
                "priority": "urgent",
                "source": "commitment",
            }
        ],
        "referrer": "红杉推荐",
        "dominant_speaker": "0",
        "competitor_mentions": [],
        "timeline_signals": "Q3前完成决策",
    },
    "edited_report": None,
    "html_report_path": None,
}


class TestRoadshowHtmlReport:
    """Roadshow Bug 4 — HTML 报告生成和下载。"""

    def test_generate_html_report_returns_ok(self, monkeypatch, tmp_path):
        """POST /html-report：生成后返回 ok=True 和路径。"""
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_get",
            lambda jid: _ROADSHOW_INTEL_ROW if jid == _JOB_ID else None,
        )
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_update", lambda *a, **kw: None
        )
        # 重定向输出目录到 tmp_path
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.get_backend_root",
            lambda: tmp_path,
        )
        resp = client.post(f"/api/v1/roadshow/jobs/{_JOB_ID}/html-report")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "html_path" in data
        assert "generated_at" in data

    def test_generate_html_creates_file_on_disk(self, monkeypatch, tmp_path):
        """生成后 HTML 文件应确实写入磁盘。"""
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_get",
            lambda jid: _ROADSHOW_INTEL_ROW if jid == _JOB_ID else None,
        )
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_update", lambda *a, **kw: None
        )
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.get_backend_root",
            lambda: tmp_path,
        )
        client.post(f"/api/v1/roadshow/jobs/{_JOB_ID}/html-report")
        html_file = tmp_path / "data" / "html_reports" / f"{_JOB_ID}.html"
        assert html_file.exists()
        content = html_file.read_text(encoding="utf-8")
        # 内容应包含机构名、关键词
        assert "路演情报报告" in content
        assert "IRR" in content  # 来自 key_questions.verbatim

    def test_generate_html_report_404_no_report(self, monkeypatch):
        """无 original_report 时返回 404。"""
        row = {**_ROADSHOW_INTEL_ROW, "original_report": None}
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_get", lambda jid: row
        )
        resp = client.post(f"/api/v1/roadshow/jobs/{_JOB_ID}/html-report")
        assert resp.status_code == 404

    def test_generate_html_report_404_unknown_job(self, monkeypatch):
        """未知 job 返回 404。"""
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_get", lambda jid: None
        )
        resp = client.post(f"/api/v1/roadshow/jobs/unknown/html-report")
        assert resp.status_code == 404

    def test_get_html_report_404_before_generation(self, monkeypatch, tmp_path):
        """生成前 GET 请求应返回 404。"""
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.get_backend_root",
            lambda: tmp_path,
        )
        resp = client.get(f"/api/v1/roadshow/jobs/{_JOB_ID}/html-report")
        assert resp.status_code == 404

    def test_html_content_includes_all_sections(self, monkeypatch, tmp_path):
        """生成的 HTML 应包含所有报告章节。"""
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_get",
            lambda jid: _ROADSHOW_INTEL_ROW if jid == _JOB_ID else None,
        )
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.db_job_update", lambda *a, **kw: None
        )
        monkeypatch.setattr(
            "cangjie_fos.api.routes.roadshow.get_backend_root",
            lambda: tmp_path,
        )
        client.post(f"/api/v1/roadshow/jobs/{_JOB_ID}/html-report")
        html_file = tmp_path / "data" / "html_reports" / f"{_JOB_ID}.html"
        content = html_file.read_text(encoding="utf-8")

        # 各章节标题
        assert "对方关键问题" in content
        assert "兴趣信号" in content
        assert "隐性顾虑" in content
        assert "关键原声" in content
        assert "机构档案更新建议" in content
        assert "下一步行动" in content
        # 数据内容
        assert "某VC" in content or "路演_2026-05-11" in content
        assert "市场规模可能被高估" in content
        assert "发送财务模型" in content
