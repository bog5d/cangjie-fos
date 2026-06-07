"""Tests for Phase 2 materials & contributions API."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

import cangjie_fos.services.pitch_job_db as _db_module
from cangjie_fos.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch, tmp_path):
    db_file = tmp_path / "pitch_jobs.sqlite"
    monkeypatch.setattr(_db_module, "_db_path", lambda: str(db_file))
    yield


# ---------------------------------------------------------------------------
# GET /api/materials/health
# ---------------------------------------------------------------------------


def test_materials_health_empty_returns_200():
    """Empty material_contributions table → 200 with empty list."""
    resp = client.get("/api/materials/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "assets" in data
    assert isinstance(data["assets"], list)


def test_materials_health_with_data():
    from cangjie_fos.services.pitch_job_db import db_material_contribution_upsert

    db_material_contribution_upsert("deck.pptx", "docs/deck.pptx", tags=["pitch"], usage_count_delta=3)
    resp = client.get("/api/materials/health")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["assets"]) >= 1
    asset = data["assets"][0]
    assert asset["asset_filename"] == "deck.pptx"
    assert asset["usage_count"] == 3


# ---------------------------------------------------------------------------
# POST /api/materials/match
# ---------------------------------------------------------------------------

_MOCK_ASSET_INDEX = {
    "generated_at": "2026-04-28T00:00:00",
    "total_files": 2,
    "source_dir": "/mock",
    "assets": [
        {
            "filename": "term_sheet.pdf",
            "relative_path": "legal/term_sheet.pdf",
            "full_path": "/mock/legal/term_sheet.pdf",
            "last_modified": "2026-04-01T00:00:00",
            "summary": "投资条款清单",
            "tags": ["legal", "investment"],
        },
        {
            "filename": "deck.pptx",
            "relative_path": "pitch/deck.pptx",
            "full_path": "/mock/pitch/deck.pptx",
            "last_modified": "2026-04-10T00:00:00",
            "summary": "融资路演材料",
            "tags": ["pitch", "deck"],
        },
    ],
}


def test_materials_match_returns_200():
    with patch("cangjie_fos.api.routes.materials.load_asset_index_dict", return_value=_MOCK_ASSET_INDEX):
        resp = client.post("/api/materials/match", json={"institution_id": "inst-abc"})
    assert resp.status_code == 200
    data = resp.json()
    assert "institution_id" in data
    assert data["institution_id"] == "inst-abc"
    assert "matches" in data
    assert isinstance(data["matches"], list)


def test_materials_match_missing_institution_id():
    resp = client.post("/api/materials/match", json={})
    assert resp.status_code == 422


def test_materials_match_saves_to_history():
    from cangjie_fos.services.pitch_job_db import db_material_matches_list

    with patch("cangjie_fos.api.routes.materials.load_asset_index_dict", return_value=_MOCK_ASSET_INDEX):
        client.post("/api/materials/match", json={"institution_id": "inst-xyz"})
    history = db_material_matches_list("inst-xyz")
    assert len(history) > 0


def test_materials_match_no_asset_index():
    with patch(
        "cangjie_fos.api.routes.materials.load_asset_index_dict",
        side_effect=OSError("not found"),
    ):
        resp = client.post("/api/materials/match", json={"institution_id": "inst-err"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["matches"] == []
