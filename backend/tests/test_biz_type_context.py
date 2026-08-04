"""业务类型不再硬编码(J2) + 机构背景自动带入(J3) 测试。游梦秋 #08。"""
from __future__ import annotations

import pytest
from types import SimpleNamespace

from cangjie_fos.services import institution_store as store
from cangjie_fos.schemas.institution import InstitutionProfileCreate


# ── J2：多业务类型都走情报分析分支 ────────────────────────────────────────────

@pytest.mark.parametrize("cat", ["01_机构路演", "03_客户访谈", "04_供应商访谈", "05_高管访谈"])
def test_intel_categories_route_to_intel_branch(monkeypatch, cat):
    from cangjie_fos.services import pitch_graph_service as pgs

    called = {}
    def fake_intel(words, *, model_choice="deepseek", explicit_context=None, on_notice=None):
        called["biz_type"] = (explicit_context or {}).get("biz_type")
        return SimpleNamespace(model_dump=lambda: {"report_type": "roadshow_intel"})
    monkeypatch.setattr(pgs, "run_roadshow_intel_analysis", fake_intel)

    report, _ = pgs.PitchGraphService.run_evaluation_with_state(
        tenant_id="t1", words=[], explicit_context={"biz_type": cat})
    assert called["biz_type"] == cat  # 走了情报分支且带上真实业务类型


def test_scoring_category_not_intel(monkeypatch):
    """非情报类（如空/其它）不走情报分支。"""
    from cangjie_fos.services import pitch_graph_service as pgs
    intel_called = []
    monkeypatch.setattr(pgs, "run_roadshow_intel_analysis",
                        lambda *a, **k: intel_called.append(1))
    monkeypatch.setattr(pgs, "run_meeting_minutes_analysis", lambda *a, **k: None)
    # 常规评分分支
    monkeypatch.setattr(
        "cangjie_fos.services.pitch_graph_service.run_pitch_evaluation_via_langgraph_with_state",
        lambda **k: (SimpleNamespace(model_dump=lambda: {}), {}),
    )
    monkeypatch.setattr(
        "cangjie_fos.services.institution_intel_extract.extract_and_persist_institution_intel",
        lambda **k: None,
    )
    pgs.PitchGraphService.run_evaluation_with_state(
        tenant_id="t1", words=[], explicit_context={"biz_type": "99_其它"})
    assert intel_called == []


# ── J3：机构背景自动带入 ──────────────────────────────────────────────────────

@pytest.fixture()
def _iso_inst(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db_path", lambda: str(tmp_path / "inst.sqlite"))


def test_institution_background_from_crm(_iso_inst):
    from cangjie_fos.services.pitch_upload_pipeline import _institution_background

    p = store.create_institution(InstitutionProfileCreate(tenant_id="zt", name="红杉资本"))
    store.update_institution(tenant_id="zt", institution_id=p.institution_id,
                             ai_summary="关注硬科技早期", concerns="估值偏高、退出路径")
    bg = _institution_background("zt", "红杉资本")
    assert "红杉资本" in bg
    assert "硬科技" in bg
    assert "估值偏高" in bg


def test_institution_background_placeholder_empty(_iso_inst):
    from cangjie_fos.services.pitch_upload_pipeline import _institution_background
    assert _institution_background("zt", "待确认_2026-08-04") == ""
    assert _institution_background("zt", "") == ""
    assert _institution_background("zt", "查无此机构") == ""


# ── 路由：biz_type 存为 category ──────────────────────────────────────────────

def test_roadshow_start_stores_biz_type():
    import urllib.parse
    from fastapi.testclient import TestClient
    from cangjie_fos.main import create_app
    from cangjie_fos.services.pitch_job_db import db_job_get

    tx = urllib.parse.quote("说话人A：我们的产品……", safe="")
    with TestClient(create_app()) as c:
        r = c.post(f"/api/v1/roadshow/start?tenant_id=t1&roadshow_date=2026-08-04"
                   f"&biz_type=05_高管访谈&transcript_text={tx}")
        assert r.status_code == 200, r.text
        job_id = r.json()["job_id"]
        assert db_job_get(job_id)["category"] == "05_高管访谈"


def test_roadshow_start_invalid_biz_type_falls_back():
    import urllib.parse
    from fastapi.testclient import TestClient
    from cangjie_fos.main import create_app
    from cangjie_fos.services.pitch_job_db import db_job_get

    tx = urllib.parse.quote("说话人A：测试", safe="")
    with TestClient(create_app()) as c:
        r = c.post(f"/api/v1/roadshow/start?tenant_id=t1&roadshow_date=2026-08-04"
                   f"&biz_type=乱填&transcript_text={tx}")
        job_id = r.json()["job_id"]
        assert db_job_get(job_id)["category"] == "01_机构路演"
