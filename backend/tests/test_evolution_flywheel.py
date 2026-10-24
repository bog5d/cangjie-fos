"""进化飞轮测试：capture + extractor + PATCH 端点集成。"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from cangjie_fos.main import create_app
from cangjie_fos.services.evolution_capture import compute_diff_summary, capture_review_diff
from cangjie_fos.services.evolution_extractor import run_preference_extraction
from cangjie_fos.services.pitch_job_db import (
    _connect,
    db_diff_list_pending,
    db_diff_mark_extracted,
    db_pref_list_for_tenant,
)
from cangjie_fos.services.pitch_job_store import job_create

# ── 常量 ─────────────────────────────────────────────────────────────────────

TENANT = "evo-test-tenant"
JOB_ID = "evo-test-job-00000001"

ORIGINAL = {
    "total_score": 70,
    "risk_points": [
        {
            "original_text": "信息披露不足",
            "risk_level": "一般",
            "tier1_general_critique": "披露问题",
            "score_deduction": 5,
        },
        {
            "original_text": "财务数据异常",
            "risk_level": "严重",
            "tier1_general_critique": "财务问题",
            "score_deduction": 15,
        },
    ],
    "positive_highlights": ["团队背景强"],
}

EDITED = {
    "total_score": 65,          # 下调 5
    "risk_points": [
        {
            "original_text": "信息披露不足",
            "risk_level": "严重",              # 一般→严重
            "tier1_general_critique": "披露问题（升级）",
            "score_deduction": 10,
        },
        # 财务问题被删除
        {
            "original_text": "竞争壁垒不足",  # 新增
            "risk_level": "一般",
            "tier1_general_critique": "竞争问题",
            "score_deduction": 5,
        },
    ],
    "positive_highlights": ["团队背景强", "市场空间大"],  # 新增亮点
}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_db():
    """每个测试前清理测试数据。"""
    conn = _connect()
    conn.execute("DELETE FROM review_diffs WHERE tenant_id = ?", (TENANT,))
    conn.execute("DELETE FROM investor_prefs WHERE tenant_id = ?", (TENANT,))
    conn.execute("DELETE FROM pitch_jobs WHERE job_id = ?", (JOB_ID,))
    conn.commit()
    conn.close()
    job_create(JOB_ID, TENANT)


@pytest.fixture
def client():
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        yield c


# ── compute_diff_summary 单元测试 ─────────────────────────────────────────────

class TestComputeDiffSummary:
    def test_score_delta(self):
        diff = compute_diff_summary(ORIGINAL, EDITED)
        assert diff["score_delta"] == -5

    def test_risk_added(self):
        diff = compute_diff_summary(ORIGINAL, EDITED)
        texts = [rp["original_text"] for rp in diff["risk_points_added"]]
        assert "竞争壁垒不足" in texts

    def test_risk_removed(self):
        diff = compute_diff_summary(ORIGINAL, EDITED)
        texts = [rp["original_text"] for rp in diff["risk_points_removed"]]
        assert "财务数据异常" in texts

    def test_risk_changed(self):
        diff = compute_diff_summary(ORIGINAL, EDITED)
        assert len(diff["risk_points_changed"]) >= 1
        changed = diff["risk_points_changed"][0]
        assert changed["original"]["risk_level"] == "一般"
        assert changed["edited"]["risk_level"] == "严重"

    def test_highlight_added(self):
        diff = compute_diff_summary(ORIGINAL, EDITED)
        assert "市场空间大" in diff["highlights_added"]

    def test_no_original(self):
        diff = compute_diff_summary(None, EDITED)
        assert diff["score_delta"] == 0
        assert len(diff["risk_points_added"]) == len(EDITED["risk_points"])


# ── capture_review_diff 集成测试 ───────────────────────────────────────────────

class TestCaptureReviewDiff:
    def test_diff_written_to_db(self):
        diff_id = capture_review_diff(
            job_id=JOB_ID,
            tenant_id=TENANT,
            committed_at=time.time(),
            original_report=ORIGINAL,
            edited_report=EDITED,
        )
        assert isinstance(diff_id, int) and diff_id > 0

    def test_diff_pending_flag(self):
        capture_review_diff(
            job_id=JOB_ID,
            tenant_id=TENANT,
            committed_at=time.time(),
            original_report=ORIGINAL,
            edited_report=EDITED,
        )
        pending = db_diff_list_pending()
        assert any(d["job_id"] == JOB_ID for d in pending)

    def test_mark_extracted_clears_pending(self):
        diff_id = capture_review_diff(
            job_id=JOB_ID,
            tenant_id=TENANT,
            committed_at=time.time(),
            original_report=ORIGINAL,
            edited_report=EDITED,
        )
        db_diff_mark_extracted(diff_id)
        pending = db_diff_list_pending()
        assert not any(d["id"] == diff_id for d in pending)


# ── run_preference_extraction 集成测试 ────────────────────────────────────────

class TestRunPreferenceExtraction:
    def _seed_diff(self):
        return capture_review_diff(
            job_id=JOB_ID,
            tenant_id=TENANT,
            committed_at=time.time(),
            original_report=ORIGINAL,
            edited_report=EDITED,
        )

    def test_returns_processed_count(self):
        self._seed_diff()
        count = run_preference_extraction(tenant_id=TENANT)
        assert count >= 1

    def test_prefs_written(self):
        self._seed_diff()
        run_preference_extraction(tenant_id=TENANT)
        prefs = db_pref_list_for_tenant(TENANT)
        assert len(prefs) > 0

    def test_score_bias_pref_present(self):
        self._seed_diff()
        run_preference_extraction(tenant_id=TENANT)
        prefs = db_pref_list_for_tenant(TENANT)
        types = {p["pref_type"] for p in prefs}
        assert "score_bias" in types

    def test_risk_level_adjustment_pref(self):
        self._seed_diff()
        run_preference_extraction(tenant_id=TENANT)
        prefs = db_pref_list_for_tenant(TENANT)
        keys = {p["pref_key"] for p in prefs}
        assert any("upgrade" in k for k in keys)

    def test_idempotent_no_double_process(self):
        self._seed_diff()
        run_preference_extraction(tenant_id=TENANT)
        prefs_first = db_pref_list_for_tenant(TENANT)
        run_preference_extraction(tenant_id=TENANT)
        prefs_second = db_pref_list_for_tenant(TENANT)
        assert len(prefs_first) == len(prefs_second)


# ── PATCH /review 端点集成测试 ────────────────────────────────────────────────

class TestPatchReviewEndpoint:
    def _seed_job_with_report(self):
        from cangjie_fos.services.pitch_job_db import db_job_update
        db_job_update(
            JOB_ID,
            status="completed",
            original_report=ORIGINAL,
        )

    def test_patch_returns_200(self, client):
        self._seed_job_with_report()
        r = client.patch(
            f"/api/pitch/jobs/{JOB_ID}/review",
            json={"edited_report": EDITED},
        )
        assert r.status_code == 200

    def test_patch_response_has_committed_at(self, client):
        self._seed_job_with_report()
        r = client.patch(
            f"/api/pitch/jobs/{JOB_ID}/review",
            json={"edited_report": EDITED},
        )
        data = r.json()
        assert "committed_at" in data
        assert data["job_id"] == JOB_ID

    def test_patch_unknown_job_returns_404(self, client):
        r = client.patch(
            "/api/pitch/jobs/nonexistent-job/review",
            json={"edited_report": EDITED},
        )
        assert r.status_code == 404

    def test_patch_empty_report_returns_422(self, client):
        self._seed_job_with_report()
        r = client.patch(
            f"/api/pitch/jobs/{JOB_ID}/review",
            json={"edited_report": {}},
        )
        assert r.status_code == 422
