"""follow_up_items CRUD + API + participants 机构绑定测试（Phase 7 P3）

覆盖：
1. db_follow_up_insert / db_follow_up_list / db_follow_up_mark_done / db_follow_up_list_by_job
2. GET /api/v1/follow-ups?tenant_id=X — 列表 + include_done 参数
3. PATCH /api/v1/follow-ups/{id}/done — 标记已完成
4. GET /api/v1/pitch/jobs/{job_id}/follow-ups — 指定 job 行动项
5. GET /api/v1/institutions/{name}/jobs — 机构路演时间线
6. POST /api/v1/pitch/jobs/{job_id}/participants — institution_id 绑定 + follow_up 回填
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.real_db]

from cangjie_fos.main import create_app
from cangjie_fos.services.pitch_job_db import (
    _connect,
    db_follow_up_insert,
    db_follow_up_list,
    db_follow_up_list_by_job,
    db_follow_up_mark_done,
    db_job_bind_institution,
    db_job_get,
)
from cangjie_fos.services.pitch_job_store import job_create

TENANT = "test-fu-tenant"
JOB_ID_A = "fu-test-job-000000a1"
JOB_ID_B = "fu-test-job-000000b1"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="module", autouse=True)
def setup_jobs():
    """清理残留 → 创建两个测试 job。"""
    conn = _connect()
    for jid in (JOB_ID_A, JOB_ID_B):
        conn.execute("DELETE FROM pitch_jobs WHERE job_id = ?", (jid,))
        conn.execute("DELETE FROM follow_up_items WHERE job_id = ?", (jid,))
    conn.commit()
    conn.close()

    job_create(JOB_ID_A, TENANT)
    job_create(JOB_ID_B, TENANT)


# ── 单元：CRUD 函数 ───────────────────────────────────────────────────────────

class TestFollowUpCRUD:
    def test_insert_returns_id(self):
        item_id = db_follow_up_insert(
            tenant_id=TENANT,
            job_id=JOB_ID_A,
            action="联系 LP 确认投委会时间",
            priority="urgent",
            source="commitment",
        )
        assert isinstance(item_id, str) and len(item_id) == 36  # UUID

    def test_list_returns_inserted(self):
        db_follow_up_insert(
            tenant_id=TENANT,
            job_id=JOB_ID_A,
            action="发送尽调问卷",
            priority="normal",
            source="suggestion",
        )
        items = db_follow_up_list(TENANT)
        actions = [i["action"] for i in items]
        assert "发送尽调问卷" in actions

    def test_list_excludes_done_by_default(self):
        item_id = db_follow_up_insert(
            tenant_id=TENANT,
            job_id=JOB_ID_B,
            action="待标记完成的项",
            priority="normal",
            source="suggestion",
        )
        db_follow_up_mark_done(item_id)

        items_pending = db_follow_up_list(TENANT, include_done=False)
        ids_pending = [i["id"] for i in items_pending]
        assert item_id not in ids_pending

        items_all = db_follow_up_list(TENANT, include_done=True)
        ids_all = [i["id"] for i in items_all]
        assert item_id in ids_all

    def test_mark_done_returns_true(self):
        item_id = db_follow_up_insert(
            tenant_id=TENANT,
            job_id=JOB_ID_A,
            action="另一个待完成项",
            priority="normal",
            source="commitment",
        )
        result = db_follow_up_mark_done(item_id)
        assert result is True

    def test_mark_done_not_found_returns_false(self):
        result = db_follow_up_mark_done("non-existent-id-xxxxxxxx")
        assert result is False

    def test_list_by_job(self):
        db_follow_up_insert(
            tenant_id=TENANT,
            job_id=JOB_ID_B,
            action="job_B 专属行动项",
            priority="normal",
            source="commitment",
        )
        items_b = db_follow_up_list_by_job(JOB_ID_B)
        # job_b 有自己的行动项
        actions_b = [i["action"] for i in items_b]
        assert "job_B 专属行动项" in actions_b
        # job_a 的不应该出现在 job_b 列表
        for i in items_b:
            assert i["job_id"] == JOB_ID_B

    def test_institution_bind_backfills_follow_ups(self):
        item_id = db_follow_up_insert(
            tenant_id=TENANT,
            job_id=JOB_ID_A,
            institution_id="",  # 尚未绑定
            action="绑定机构后应回填",
            priority="normal",
            source="suggestion",
        )
        db_job_bind_institution(JOB_ID_A, "明远资本")

        items = db_follow_up_list_by_job(JOB_ID_A)
        target = next((i for i in items if i["id"] == item_id), None)
        assert target is not None
        assert target["institution_id"] == "明远资本", (
            f"institution_id 未回填: {target['institution_id']}"
        )

        # pitch_jobs 也应更新
        row = db_job_get(JOB_ID_A)
        assert row["institution_id"] == "明远资本"


# ── API 层：follow-ups 路由 ──────────────────────────────────────────────────

class TestFollowUpAPI:
    def test_list_api_200(self, client):
        resp = client.get(f"/api/v1/follow-ups?tenant_id={TENANT}")
        assert resp.status_code == 200, resp.text
        assert isinstance(resp.json(), list)

    def test_list_api_404_no_tenant(self, client):
        """tenant_id 是必填参数，缺失应返回 422。"""
        resp = client.get("/api/v1/follow-ups")
        assert resp.status_code == 422

    def test_mark_done_api(self, client):
        # 先插一条
        item_id = db_follow_up_insert(
            tenant_id=TENANT,
            job_id=JOB_ID_B,
            action="API mark_done 测试项",
            priority="normal",
            source="suggestion",
        )
        resp = client.patch(f"/api/v1/follow-ups/{item_id}/done")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["ok"] is True
        assert data["id"] == item_id

    def test_mark_done_404(self, client):
        resp = client.patch("/api/v1/follow-ups/non-existent-id/done")
        assert resp.status_code == 404

    def test_job_follow_ups_api_200(self, client):
        resp = client.get(f"/api/v1/pitch/jobs/{JOB_ID_A}/follow-ups")
        assert resp.status_code == 200, resp.text
        items = resp.json()
        assert isinstance(items, list)

    def test_job_follow_ups_api_404(self, client):
        resp = client.get("/api/v1/pitch/jobs/non-existent-job/follow-ups")
        assert resp.status_code == 404

    def test_institution_timeline_api(self, client):
        # JOB_ID_A 刚刚绑到 "明远资本"
        resp = client.get("/api/v1/institutions/明远资本/jobs")
        assert resp.status_code == 200, resp.text
        jobs = resp.json()
        job_ids = [j["job_id"] for j in jobs]
        assert JOB_ID_A in job_ids, f"机构时间线未包含 JOB_ID_A: {jobs}"

    def test_institution_timeline_empty(self, client):
        resp = client.get("/api/v1/institutions/不存在的机构XXXXX/jobs")
        assert resp.status_code == 200
        assert resp.json() == []


# ── participants confirm → institution 绑定集成测试 ──────────────────────────

class TestParticipantsInstitutionBind:
    def test_confirm_participants_binds_institution(self, client):
        # 先插一条 follow_up，institution_id 为空（模拟分析完成但参与人未确认时的状态）
        item_id = db_follow_up_insert(
            tenant_id=TENANT,
            job_id=JOB_ID_B,
            institution_id="",
            action="等待参与人确认后回填机构",
            priority="normal",
            source="commitment",
        )

        # POST participants
        resp = client.post(
            f"/api/v1/pitch/jobs/{JOB_ID_B}/participants",
            json={
                "participants": [
                    {
                        "speaker_id": "A",
                        "real_name": "张三",
                        "institution": "深盛投资",
                        "role": "GP执行",
                        "title": "合伙人",
                    }
                ],
                "confirmed_by": "test_user",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["ok"] is True
        assert data.get("institution") == "深盛投资"

        # pitch_jobs.institution_id 应更新
        row = db_job_get(JOB_ID_B)
        assert row["institution_id"] == "深盛投资"

        # follow_up_items 的 institution_id 应回填
        items = db_follow_up_list_by_job(JOB_ID_B)
        target = next((i for i in items if i["id"] == item_id), None)
        assert target is not None
        assert target["institution_id"] == "深盛投资", (
            f"participants 确认后 follow_up 的 institution_id 未回填: {target['institution_id']}"
        )
