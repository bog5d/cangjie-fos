"""Step 2：机构里程碑字段与引荐方字段测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cangjie_fos.main import app


def test_milestone_fields_default_values(monkeypatch, tmp_path):
    """新建机构时里程碑字段全部默认为 False/0。"""
    import cangjie_fos.services.institution_store as store
    monkeypatch.setattr(store, "_db_path", lambda: str(tmp_path / "inst.sqlite"))

    from cangjie_fos.schemas.institution import InstitutionProfileCreate, PipelineStage, InstitutionThermal
    inst = store.create_institution(InstitutionProfileCreate(
        tenant_id="t1", name="测试机构X",
        stage=PipelineStage.PITCHED, thermal=InstitutionThermal.WARM,
    ))
    assert inst.nda_signed is False
    assert inst.offline_meeting_count == 0
    assert inst.project_approved is False
    assert inst.committee_approved is False
    assert inst.onsite_dd_done is False
    assert inst.agreement_signed is False
    assert inst.deal_closed is False
    assert inst.referral_source == ""


def test_milestone_update_nda_and_meetings(monkeypatch, tmp_path):
    """更新 nda_signed=True + offline_meeting_count 应持久化。"""
    import cangjie_fos.services.institution_store as store
    monkeypatch.setattr(store, "_db_path", lambda: str(tmp_path / "inst.sqlite"))

    from cangjie_fos.schemas.institution import InstitutionProfileCreate, PipelineStage, InstitutionThermal
    inst = store.create_institution(InstitutionProfileCreate(
        tenant_id="t1", name="签NDA机构",
        stage=PipelineStage.DD, thermal=InstitutionThermal.HOT,
    ))
    updated = store.update_institution(
        tenant_id="t1", institution_id=inst.institution_id,
        nda_signed=True, offline_meeting_count=3,
    )
    assert updated is not None
    assert updated.nda_signed is True
    assert updated.offline_meeting_count == 3


def test_milestone_update_committee_approved(monkeypatch, tmp_path):
    """过会标记更新应生效。"""
    import cangjie_fos.services.institution_store as store
    monkeypatch.setattr(store, "_db_path", lambda: str(tmp_path / "inst.sqlite"))

    from cangjie_fos.schemas.institution import InstitutionProfileCreate, PipelineStage, InstitutionThermal
    inst = store.create_institution(InstitutionProfileCreate(
        tenant_id="t1", name="过会机构",
        stage=PipelineStage.TERM_SHEET, thermal=InstitutionThermal.HOT,
    ))
    updated = store.update_institution(
        tenant_id="t1", institution_id=inst.institution_id,
        committee_approved=True, onsite_dd_done=True,
    )
    assert updated is not None
    assert updated.committee_approved is True
    assert updated.onsite_dd_done is True


def test_referral_source_field(monkeypatch, tmp_path):
    """referral_source 字段应能存储引荐方信息。"""
    import cangjie_fos.services.institution_store as store
    monkeypatch.setattr(store, "_db_path", lambda: str(tmp_path / "inst.sqlite"))

    from cangjie_fos.schemas.institution import InstitutionProfileCreate, PipelineStage, InstitutionThermal
    inst = store.create_institution(InstitutionProfileCreate(
        tenant_id="t1", name="引荐机构",
        stage=PipelineStage.PITCHED, thermal=InstitutionThermal.WARM,
    ))
    updated = store.update_institution(
        tenant_id="t1", institution_id=inst.institution_id,
        referral_source="张 FA",
    )
    assert updated is not None
    assert updated.referral_source == "张 FA"


def test_milestones_persist_in_list(monkeypatch, tmp_path):
    """list_institutions 应包含里程碑字段。"""
    import cangjie_fos.services.institution_store as store
    monkeypatch.setattr(store, "_db_path", lambda: str(tmp_path / "inst.sqlite"))

    from cangjie_fos.schemas.institution import InstitutionProfileCreate, PipelineStage, InstitutionThermal
    inst = store.create_institution(InstitutionProfileCreate(
        tenant_id="t1", name="列表里程碑机构",
        stage=PipelineStage.DD, thermal=InstitutionThermal.WARM,
    ))
    store.update_institution(
        tenant_id="t1", institution_id=inst.institution_id,
        nda_signed=True, committee_approved=True, referral_source="李中介",
    )
    listed = store.list_institutions(tenant_id="t1", limit=10)
    found = next((i for i in listed if i.name == "列表里程碑机构"), None)
    assert found is not None
    assert found.nda_signed is True
    assert found.committee_approved is True
    assert found.referral_source == "李中介"


def test_milestone_stats_endpoint(monkeypatch, tmp_path):
    """GET /api/v1/pipeline/milestone-stats 应返回各里程碑计数。"""
    import cangjie_fos.services.institution_store as store
    monkeypatch.setattr(store, "_db_path", lambda: str(tmp_path / "inst.sqlite"))

    from cangjie_fos.schemas.institution import InstitutionProfileCreate, PipelineStage, InstitutionThermal
    for name in ["机构A", "机构B", "机构C"]:
        inst = store.create_institution(InstitutionProfileCreate(
            tenant_id="t1", name=name,
            stage=PipelineStage.PITCHED, thermal=InstitutionThermal.WARM,
        ))
        store.update_institution(
            tenant_id="t1", institution_id=inst.institution_id,
            nda_signed=(name != "机构C"),
            committee_approved=(name == "机构A"),
        )

    c = TestClient(app)
    r = c.get("/api/v1/pipeline/milestone-stats", params={"tenant_id": "t1"})
    assert r.status_code == 200
    body = r.json()
    assert body["total_contacted"] == 3
    assert body["nda_signed"] == 2
    assert body["committee_approved"] == 1
    assert "top_referrals" in body


def test_api_patch_milestone_fields(monkeypatch, tmp_path):
    """PATCH /api/v1/pipeline/institutions/{id} 应接受里程碑字段。"""
    import cangjie_fos.services.institution_store as store
    monkeypatch.setattr(store, "_db_path", lambda: str(tmp_path / "inst.sqlite"))

    from cangjie_fos.schemas.institution import InstitutionProfileCreate, PipelineStage, InstitutionThermal
    inst = store.create_institution(InstitutionProfileCreate(
        tenant_id="t1", name="PATCH测试机构",
        stage=PipelineStage.DD, thermal=InstitutionThermal.HOT,
    ))

    c = TestClient(app)
    r = c.patch(
        f"/api/v1/pipeline/institutions/{inst.institution_id}",
        json={"nda_signed": True, "offline_meeting_count": 5, "referral_source": "王介绍"},
        params={"tenant_id": "t1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["nda_signed"] is True
    assert body["offline_meeting_count"] == 5
    assert body["referral_source"] == "王介绍"
