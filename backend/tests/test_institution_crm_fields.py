"""测试机构档案 CRM 扩展字段（P0-2）。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cangjie_fos.main import app


# ── 数据库层测试 ────────────────────────────────────────────────────────────────

def test_crm_fields_default_values(monkeypatch, tmp_path):
    """新建机构时 CRM 扩展字段应有默认值。"""
    import cangjie_fos.services.institution_store as store
    monkeypatch.setattr(store, "_db_path", lambda: str(tmp_path / "inst.sqlite"))

    from cangjie_fos.schemas.institution import InstitutionProfileCreate, PipelineStage, InstitutionThermal
    inst = store.create_institution(InstitutionProfileCreate(
        tenant_id="t1",
        name="测试机构A",
        stage=PipelineStage.PITCHED,
        thermal=InstitutionThermal.WARM,
    ))
    assert inst.contact_name == ""
    assert inst.contact_title == ""
    assert inst.valuation == ""
    assert inst.deal_size == ""
    assert inst.probability == 0
    assert inst.legal_status == ""


def test_crm_fields_update(monkeypatch, tmp_path):
    """更新机构 CRM 字段后应持久化。"""
    import cangjie_fos.services.institution_store as store
    monkeypatch.setattr(store, "_db_path", lambda: str(tmp_path / "inst.sqlite"))

    from cangjie_fos.schemas.institution import InstitutionProfileCreate, PipelineStage, InstitutionThermal
    inst = store.create_institution(InstitutionProfileCreate(
        tenant_id="t1", name="红杉资本", stage=PipelineStage.DD, thermal=InstitutionThermal.HOT,
    ))

    updated = store.update_institution(
        tenant_id="t1",
        institution_id=inst.institution_id,
        contact_name="张总",
        contact_title="合伙人",
        valuation="2亿",
        deal_size="3000万",
        probability=75,
        legal_status="NDA已签",
    )
    assert updated is not None
    assert updated.contact_name == "张总"
    assert updated.contact_title == "合伙人"
    assert updated.valuation == "2亿"
    assert updated.deal_size == "3000万"
    assert updated.probability == 75
    assert updated.legal_status == "NDA已签"


def test_probability_clamped(monkeypatch, tmp_path):
    """probability 字段应被限制在 0-100。"""
    import cangjie_fos.services.institution_store as store
    monkeypatch.setattr(store, "_db_path", lambda: str(tmp_path / "inst.sqlite"))

    from cangjie_fos.schemas.institution import InstitutionProfileCreate, PipelineStage, InstitutionThermal
    inst = store.create_institution(InstitutionProfileCreate(
        tenant_id="t1", name="高瓴", stage=PipelineStage.PITCHED, thermal=InstitutionThermal.WARM,
    ))

    updated = store.update_institution(
        tenant_id="t1",
        institution_id=inst.institution_id,
        probability=150,  # 超出范围，应被 clamp 到 100
    )
    assert updated is not None
    assert updated.probability == 100


def test_crm_fields_persist_in_list(monkeypatch, tmp_path):
    """list_institutions 返回的机构应包含 CRM 字段。"""
    import cangjie_fos.services.institution_store as store
    monkeypatch.setattr(store, "_db_path", lambda: str(tmp_path / "inst.sqlite"))

    from cangjie_fos.schemas.institution import InstitutionProfileCreate, PipelineStage, InstitutionThermal
    inst = store.create_institution(InstitutionProfileCreate(
        tenant_id="t1", name="民生证券", stage=PipelineStage.DD, thermal=InstitutionThermal.WARM,
    ))
    store.update_institution(
        tenant_id="t1",
        institution_id=inst.institution_id,
        probability=60,
        legal_status="等待TS",
    )

    listed = store.list_institutions(tenant_id="t1", limit=10)
    assert len(listed) >= 1
    found = next((i for i in listed if i.name == "民生证券"), None)
    assert found is not None
    assert found.probability == 60
    assert found.legal_status == "等待TS"


# ── API 层测试 ──────────────────────────────────────────────────────────────────

def test_api_patch_crm_fields(monkeypatch):
    """PATCH /api/v1/pipeline/institutions/{id} 应接受并返回 CRM 字段。"""
    import cangjie_fos.services.institution_store as store

    from cangjie_fos.schemas.institution import InstitutionProfile, PipelineStage, InstitutionThermal

    fake_inst = InstitutionProfile(
        institution_id="inst00001",
        tenant_id="t1",
        name="测试机构",
        stage=PipelineStage.DD,
        thermal=InstitutionThermal.WARM,
        contact_name="李总",
        contact_title="VP",
        valuation="5亿",
        deal_size="5000万",
        probability=80,
        legal_status="TS在谈",
    )

    import cangjie_fos.api.routes.pipeline as pipeline_route
    monkeypatch.setattr(pipeline_route, "update_institution", lambda **kwargs: fake_inst)

    c = TestClient(app)
    r = c.patch(
        "/api/v1/pipeline/institutions/inst00001",
        json={
            "contact_name": "李总",
            "contact_title": "VP",
            "valuation": "5亿",
            "deal_size": "5000万",
            "probability": 80,
            "legal_status": "TS在谈",
        },
        params={"tenant_id": "t1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["contact_name"] == "李总"
    assert body["probability"] == 80
    assert body["legal_status"] == "TS在谈"
