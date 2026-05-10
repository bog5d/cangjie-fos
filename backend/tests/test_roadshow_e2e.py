"""路演情报全链路 E2E 测试（Phase 7 P3）

覆盖：
1. 文字稿模式（.txt）+ category=01_机构路演 → wizard runner
2. run_pitch_file_job mock 返回 RoadshowIntelReport
3. DB 验证：status=completed, original_report.report_type=roadshow_intel
4. follow_up_items 自动写入（每条 next_action → 一行 DB 记录）
5. GET /review API 返回路演情报报告（不报「数据异常」）
6. GET /jobs/{job_id}/follow-ups API 返回行动项
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from cangjie_fos.engine.schema import IntelAction, RoadshowIntelReport
from cangjie_fos.main import create_app
from cangjie_fos.services.pitch_job_db import _connect, db_follow_up_list_by_job, db_job_get
from cangjie_fos.services.pitch_job_store import job_create
from cangjie_fos.services.pitch_wizard_runner import run_pitch_wizard_track_job

TENANT = "test-tenant-roadshow-e2e"
JOB_ID = "roadshow-e2e-test-00000001"

# ── Fake 路演情报报告（含 2 条 next_actions）──────────────────────────────────

FAKE_ACTIONS = [
    IntelAction(actor="对方", action="下周安排合伙人会议", priority="urgent", source="commitment"),
    IntelAction(actor="我方", action="补发尽调材料清单", priority="normal", source="suggestion"),
]

FAKE_ROADSHOW_REPORT = RoadshowIntelReport(
    meeting_atmosphere="hot",
    meeting_stage="deep_discussion",
    atmosphere_summary="对方表现出强烈投资兴趣，主动追问尽调时间表。",
    key_questions=[],
    interest_signals=[],
    hidden_concerns=[],
    key_verbatim_moments=["「这个赛道我们一直在看」"],
    institution_update="新川基金偏好有真实ARR的项目",
    next_actions=FAKE_ACTIONS,
)

# model_dump 需要返回可序列化的 dict
FAKE_REPORT_DICT = FAKE_ROADSHOW_REPORT.model_dump()

# 伪造 run_pitch_file_job 的返回值：(words, report)
# words 为空列表（路演情报不需要评分 words）
MOCK_RETURN = ([], FAKE_ROADSHOW_REPORT)


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="module", autouse=True)
def run_roadshow_job(tmp_path_factory):
    """写临时 .txt 文字稿 → 直接调 run_pitch_wizard_track_job（mock 掉 LLM）。"""
    tmp_dir = tmp_path_factory.mktemp("roadshow_txt")
    transcript_file = tmp_dir / "meeting.txt"
    transcript_file.write_text(
        "说话人A: 你们的退出路径是什么？\n说话人B: 我们计划3年内科创板上市。\n",
        encoding="utf-8",
    )

    # 清理上次残留
    conn = _connect()
    conn.execute("DELETE FROM pitch_jobs WHERE job_id = ?", (JOB_ID,))
    conn.execute("DELETE FROM follow_up_items WHERE job_id = ?", (JOB_ID,))
    conn.commit()
    conn.close()

    # 建 job 记录
    job_create(JOB_ID, TENANT)

    with (
        patch("cangjie_fos.services.pitch_wizard_runner.run_pitch_file_job", return_value=MOCK_RETURN),
        patch("cangjie_fos.services.pitch_wizard_runner.PitchFileJobParams", MagicMock(return_value=MagicMock())),
        patch("cangjie_fos.services.pitch_wizard_runner.build_explicit_context", return_value={}),
        patch("cangjie_fos.services.pitch_wizard_runner.HtmlExportOptions", MagicMock(return_value=MagicMock())),
        patch(
            "cangjie_fos.services.pitch_wizard_runner.extract_and_persist_institution_intel",
            side_effect=Exception("skip intel in test"),
            create=True,
        ),
        # report_post_process 的 expand_risk_original_text 对 roadshow report 是局部 import，patch 源模块
        patch("cangjie_fos.services.report_post_process.expand_risk_original_text", return_value=None),
    ):
        run_pitch_wizard_track_job(
            job_id=JOB_ID,
            tenant_id=TENANT,
            audio_path=transcript_file,
            recording_label="meeting.txt",
            category="01_机构路演",
            project_name="测试路演项目",
            interviewee="新川基金——初次路演",
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


# ── DB 层验证 ─────────────────────────────────────────────────────────────────

class TestRoadshowDB:
    def test_status_completed(self):
        row = db_job_get(JOB_ID)
        assert row is not None, "job 未在 DB 中找到"
        assert row["status"] == "completed", f"状态异常: {row['status']}"

    def test_category_written(self):
        row = db_job_get(JOB_ID)
        assert row["category"] == "01_机构路演", f"category 未写入: {row.get('category')}"

    def test_original_report_is_roadshow_intel(self):
        row = db_job_get(JOB_ID)
        report = row.get("original_report")
        assert isinstance(report, dict), "original_report 未写入 SQLite"
        assert report.get("report_type") == "roadshow_intel", (
            f"report_type 错误: {report.get('report_type')}"
        )
        assert report.get("meeting_atmosphere") == "hot"
        assert report.get("meeting_stage") == "deep_discussion"

    def test_follow_up_items_written(self):
        items = db_follow_up_list_by_job(JOB_ID)
        assert len(items) == 2, f"期望 2 条 follow_up_items，实际: {len(items)}"

    def test_follow_up_urgent_action(self):
        items = db_follow_up_list_by_job(JOB_ID)
        urgent = [i for i in items if i["priority"] == "urgent"]
        assert len(urgent) == 1
        assert "合伙人" in urgent[0]["action"]

    def test_follow_up_source_commitment(self):
        items = db_follow_up_list_by_job(JOB_ID)
        committed = [i for i in items if i["source"] == "commitment"]
        assert len(committed) == 1

    def test_follow_up_tenant_id(self):
        items = db_follow_up_list_by_job(JOB_ID)
        for item in items:
            assert item["tenant_id"] == TENANT


# ── Review API 验证 ───────────────────────────────────────────────────────────

class TestRoadshowReviewAPI:
    def test_review_200(self, client):
        resp = client.get(f"/api/pitch/jobs/{JOB_ID}/review")
        assert resp.status_code == 200, f"review API 返回 {resp.status_code}: {resp.text}"

    def test_review_report_type_roadshow_intel(self, client):
        resp = client.get(f"/api/pitch/jobs/{JOB_ID}/review")
        data = resp.json()
        report = data.get("original_report") or {}
        assert report.get("report_type") == "roadshow_intel", (
            f"review API 未返回 roadshow_intel: {report}"
        )

    def test_review_status_completed(self, client):
        resp = client.get(f"/api/pitch/jobs/{JOB_ID}/review")
        data = resp.json()
        assert data["status"] == "completed"

    def test_follow_ups_api(self, client):
        resp = client.get(f"/api/v1/pitch/jobs/{JOB_ID}/follow-ups")
        assert resp.status_code == 200, resp.text
        items = resp.json()
        assert len(items) == 2

    def test_follow_ups_global_list(self, client):
        resp = client.get(f"/api/v1/follow-ups?tenant_id={TENANT}")
        assert resp.status_code == 200, resp.text
        items = resp.json()
        assert len(items) >= 2

    def test_mark_done(self, client):
        resp = client.get(f"/api/v1/pitch/jobs/{JOB_ID}/follow-ups")
        items = resp.json()
        assert items, "行动项为空，无法测试 mark_done"
        item_id = items[0]["id"]
        patch_resp = client.patch(f"/api/v1/follow-ups/{item_id}/done")
        assert patch_resp.status_code == 200, patch_resp.text
        assert patch_resp.json()["ok"] is True

        # 再次查询：默认不含已完成，数量应减少 1
        resp2 = client.get(f"/api/v1/follow-ups?tenant_id={TENANT}")
        pending_ids = [i["id"] for i in resp2.json()]
        assert item_id not in pending_ids, "标记 done 后仍出现在待办列表"
