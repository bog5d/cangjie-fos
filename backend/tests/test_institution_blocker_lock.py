"""机构卡点备注（F2）+ 人工确认锁（F4）测试。"""
from __future__ import annotations

import pytest

from cangjie_fos.services import institution_store as s
from cangjie_fos.schemas.institution import InstitutionProfileCreate


@pytest.fixture(autouse=True)
def _isolate_institutions_db(tmp_path, monkeypatch):
    """institutions.sqlite 默认不随 conftest 的 pitch-db 隔离，这里单独隔离，
    避免跨测试/跨运行的机构名冲突污染（ON CONFLICT 会更新旧行导致 get_by_id 落空）。"""
    dbfile = tmp_path / "inst.sqlite"
    monkeypatch.setattr(s, "_db_path", lambda: str(dbfile))


def _mk(name="测试机构"):
    return s.create_institution(InstitutionProfileCreate(tenant_id="t1", name=name))


def test_blocker_note_roundtrip():
    p = _mk("卡点机构")
    assert p.blocker_note == ""
    u = s.update_institution(tenant_id="t1", institution_id=p.institution_id,
                             blocker_note="尽调卡在法务，对方律师休假")
    assert u.blocker_note == "尽调卡在法务，对方律师休假"
    assert s.get_by_id(institution_id=p.institution_id).blocker_note == "尽调卡在法务，对方律师休假"


def test_review_lock_roundtrip():
    p = _mk("锁定机构")
    assert p.review_locked is False
    u = s.update_institution(tenant_id="t1", institution_id=p.institution_id, review_locked=True)
    assert u.review_locked is True
    assert s.get_by_id(institution_id=p.institution_id).review_locked is True


def test_patch_endpoint_sets_blocker_and_lock():
    from fastapi.testclient import TestClient
    from cangjie_fos.main import create_app

    p = _mk("接口机构")
    with TestClient(create_app()) as c:
        r = c.patch(
            f"/api/v1/pipeline/institutions/{p.institution_id}?tenant_id=t1",
            json={"blocker_note": "等对方投委会", "review_locked": True},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["blocker_note"] == "等对方投委会"
        assert body["review_locked"] is True


def test_locked_institution_not_overwritten_by_roadshow():
    """F4：机构被人工锁定后，路演自动 CRM 同步跳过（不覆盖人工版本）。"""
    from cangjie_fos.services.pitch_upload_pipeline import sync_roadshow_institution

    p = _mk("红杉资本")
    s.update_institution(tenant_id="t1", institution_id=p.institution_id,
                         stage="dd", ai_summary="人工确认版画像", review_locked=True)

    wrote = sync_roadshow_institution("t1", "红杉资本", {"meeting_atmosphere": "cold"}, "job-x")
    assert wrote is False  # 锁定 → 跳过
    after = s.get_by_id(institution_id=p.institution_id)
    assert after.ai_summary == "人工确认版画像"  # 人工版本未被覆盖
    assert after.stage.value == "dd"


def test_unlocked_institution_is_synced_by_roadshow():
    """未锁定机构正常被路演同步写入。"""
    from cangjie_fos.services.pitch_upload_pipeline import sync_roadshow_institution

    p = _mk("高瓴资本")  # 默认 review_locked=False
    wrote = sync_roadshow_institution("t1", "高瓴资本", {"meeting_atmosphere": "hot"}, "job-y")
    assert wrote is True
    after = s.get_by_id(institution_id=p.institution_id)
    assert after.thermal.value == "hot"  # 已被同步更新


def test_placeholder_institution_name_skipped():
    from cangjie_fos.services.pitch_upload_pipeline import sync_roadshow_institution
    assert sync_roadshow_institution("t1", "待确认_2026-07-31", {}, "j") is False
    assert sync_roadshow_institution("t1", "", {}, "j") is False
