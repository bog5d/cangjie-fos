"""Phase 6：战前简报块 + Dashboard 漏斗聚合。"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from cangjie_fos.main import app
from cangjie_fos.schemas.institution import InstitutionProfileCreate, PipelineStage
from cangjie_fos.services.institution_meeting import build_pre_meeting_institution_block
from cangjie_fos.services.institution_store import create_institution
from cangjie_fos.services.pipeline_funnel import build_funnel_from_institutions


@pytest.fixture
def _inst_db(monkeypatch, tmp_path):
    root = tmp_path / "fos_backend"
    (root / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("cangjie_fos.core.paths.get_backend_root", lambda: root)
    yield


def test_pre_meeting_block_when_cue_and_name_hit(_inst_db) -> None:
    create_institution(
        InstitutionProfileCreate(
            tenant_id="meet-1",
            name="经纬中国",
            stage=PipelineStage.PITCHED,
            preferences="SaaS",
            concerns="续费率",
        )
    )
    block = build_pre_meeting_institution_block(
        tenant_id="meet-1",
        user_text="明天我要去见经纬中国，帮我准备提纲",
    )
    assert "经纬中国" in block
    assert "战前简报" in block


def test_pre_meeting_empty_without_cue(_inst_db) -> None:
    create_institution(InstitutionProfileCreate(tenant_id="meet-2", name="真格基金"))
    assert (
        build_pre_meeting_institution_block(tenant_id="meet-2", user_text="真格基金怎么样") == ""
    )


def test_funnel_headline_reflects_counts(_inst_db) -> None:
    create_institution(InstitutionProfileCreate(tenant_id="f-agg", name="I1", stage=PipelineStage.DD))
    create_institution(InstitutionProfileCreate(tenant_id="f-agg", name="I2", stage=PipelineStage.DD))
    funnel = build_funnel_from_institutions(tenant_id="f-agg")
    assert "2" in funnel.headline or "家" in funnel.headline


def test_dashboard_status_uses_pipeline_funnel(monkeypatch, tmp_path) -> None:
    root = tmp_path / "fos_backend"
    (root / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("cangjie_fos.core.paths.get_backend_root", lambda: root)
    monkeypatch.setenv("CANGJIE_FSS_DATA_DIR", str(tmp_path / "fos"))
    monkeypatch.setenv("CANGJIE_DATA_ROOM_ROOT", str(tmp_path / "room"))
    (tmp_path / "fos").mkdir(exist_ok=True)
    (tmp_path / "fos" / "asset_index.json").write_text('{"assets":[]}', encoding="utf-8")

    create_institution(
        InstitutionProfileCreate(tenant_id="dash-p6", name="蓝驰创投", stage=PipelineStage.TARGETED)
    )
    c = TestClient(app)
    r = c.get("/api/dashboard/status", params={"tenant_id": "dash-p6"})
    assert r.status_code == 200
    j = r.json()
    assert "funnel" in j
    assert "Pipeline" in j["funnel"]["headline"] or "机构" in j["funnel"]["headline"]
