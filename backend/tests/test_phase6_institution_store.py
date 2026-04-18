"""Phase 6：机构 SQLite CRUD。"""
from __future__ import annotations

import pytest

from cangjie_fos.schemas.institution import (
    InstitutionProfile,
    InstitutionProfileCreate,
    InstitutionThermal,
    PipelineStage,
)
from cangjie_fos.services.institution_store import (
    count_by_stage,
    create_institution,
    delete_institution,
    find_matching_names,
    get_by_name,
    list_institutions,
    upsert_institution,
)


@pytest.fixture
def _inst_db(monkeypatch, tmp_path):
    root = tmp_path / "fos_backend"
    (root / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("cangjie_fos.core.paths.get_backend_root", lambda: root)
    yield


def test_create_list_get(_inst_db) -> None:
    p = create_institution(
        InstitutionProfileCreate(
            tenant_id="t1",
            name="红杉资本",
            stage=PipelineStage.DD,
            thermal=InstitutionThermal.HOT,
            preferences="硬科技",
            concerns="产能",
            ai_summary="一线机构",
        )
    )
    assert len(p.institution_id) >= 8
    rows = list_institutions(tenant_id="t1")
    assert len(rows) == 1
    g = get_by_name(tenant_id="t1", name="红杉资本")
    assert g is not None
    assert g.stage == PipelineStage.DD


def test_count_by_stage(_inst_db) -> None:
    create_institution(InstitutionProfileCreate(tenant_id="t1", name="A", stage=PipelineStage.PITCHED))
    create_institution(InstitutionProfileCreate(tenant_id="t1", name="B", stage=PipelineStage.PITCHED))
    create_institution(InstitutionProfileCreate(tenant_id="t1", name="C", stage=PipelineStage.DD))
    c = count_by_stage(tenant_id="t1")
    assert c["pitched"] == 2
    assert c["dd"] == 1
    assert c["targeted"] == 0


def test_upsert_same_name_updates(_inst_db) -> None:
    create_institution(InstitutionProfileCreate(tenant_id="t1", name="X", preferences="p1"))
    row0 = list_institutions(tenant_id="t1")[0]
    upsert_institution(
        InstitutionProfile(
            institution_id=row0.institution_id,
            tenant_id="t1",
            name="X",
            stage=PipelineStage.TERM_SHEET,
            thermal=InstitutionThermal.WARM,
            preferences="p2",
            concerns="c2",
            ai_summary="s2",
            updated_at=99.0,
        )
    )
    g = get_by_name(tenant_id="t1", name="X")
    assert g is not None
    assert g.preferences == "p2"
    assert g.stage == PipelineStage.TERM_SHEET


def test_delete_institution(_inst_db) -> None:
    p = create_institution(InstitutionProfileCreate(tenant_id="t1", name="Z"))
    assert delete_institution(tenant_id="t1", institution_id=p.institution_id) is True
    assert delete_institution(tenant_id="t1", institution_id="missing") is False


def test_find_matching_names_aliases(_inst_db) -> None:
    create_institution(InstitutionProfileCreate(tenant_id="t1", name="红杉资本", preferences="x"))
    hits = find_matching_names(tenant_id="t1", text="明天要去见红杉，准备材料")
    assert len(hits) == 1
    assert hits[0].name == "红杉资本"
