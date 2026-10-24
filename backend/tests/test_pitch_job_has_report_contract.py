"""列表 API：has_report 仅在 completed 且确有 report 时为 True。"""
from __future__ import annotations

import uuid

from starlette.testclient import TestClient

from cangjie_fos.main import app
from cangjie_fos.schemas.pitch_upload import PitchJobStatus
from cangjie_fos.services.pitch_job_store import job_create, job_update


def test_job_list_has_report_false_while_evaluating_even_if_report_dict_exists() -> None:
    """防止前端竞态：转写/评估中即使内存里误带 report，也不应 has_report。"""
    c = TestClient(app)
    jid = uuid.uuid4().hex
    job_create(jid, "tenant-hr", report={"draft": True}, status=PitchJobStatus.EVALUATING)
    r = c.get("/api/pitch/jobs", params={"tenant_id": "tenant-hr", "limit": 5})
    assert r.status_code == 200
    row = next(x for x in r.json() if x["job_id"] == jid)
    assert row["status"] == "evaluating"
    assert row["has_report"] is False


def test_job_list_has_report_true_when_completed() -> None:
    c = TestClient(app)
    jid = uuid.uuid4().hex
    job_create(jid, "tenant-hr2", status=PitchJobStatus.PENDING)
    job_update(jid, status=PitchJobStatus.COMPLETED, report={"total_score": 1})
    r = c.get("/api/pitch/jobs", params={"tenant_id": "tenant-hr2", "limit": 5})
    assert r.status_code == 200
    row = next(x for x in r.json() if x["job_id"] == jid)
    assert row["status"] == "completed"
    assert row["has_report"] is True
