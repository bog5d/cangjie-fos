"""Phase 6：Pipeline HTTP 路由。"""
from __future__ import annotations

from starlette.testclient import TestClient

from cangjie_fos.main import app
from cangjie_fos.schemas.institution import InstitutionProfileCreate, PipelineStage


def test_pipeline_institutions_crud_http(monkeypatch, tmp_path) -> None:
    root = tmp_path / "fos_backend"
    (root / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("cangjie_fos.core.paths.get_backend_root", lambda: root)
    c = TestClient(app)
    r0 = c.get("/api/v1/pipeline/institutions", params={"tenant_id": "http-t1"})
    assert r0.status_code == 200
    assert r0.json() == []
    r1 = c.post(
        "/api/v1/pipeline/institutions",
        json={
            "tenant_id": "http-t1",
            "name": "高瓴资本",
            "stage": PipelineStage.PITCHED.value,
            "preferences": "消费+科技",
        },
    )
    assert r1.status_code == 200
    iid = r1.json()["institution_id"]
    r2 = c.get("/api/v1/pipeline/institutions", params={"tenant_id": "http-t1"})
    assert len(r2.json()) == 1
    r3 = c.get("/api/v1/pipeline/status", params={"tenant_id": "http-t1"})
    assert r3.status_code == 200
    assert r3.json()["total"] == 1
    assert r3.json()["counts"]["pitched"] == 1
    r4 = c.delete(f"/api/v1/pipeline/institutions/{iid}", params={"tenant_id": "http-t1"})
    assert r4.status_code == 200


def test_pipeline_status_empty_tenant(monkeypatch, tmp_path) -> None:
    root = tmp_path / "fos_backend"
    (root / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("cangjie_fos.core.paths.get_backend_root", lambda: root)
    c = TestClient(app)
    r = c.get("/api/v1/pipeline/status", params={"tenant_id": "no-one-here"})
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_pipeline_funnel_debug(monkeypatch, tmp_path) -> None:
    root = tmp_path / "fos_backend"
    (root / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("cangjie_fos.core.paths.get_backend_root", lambda: root)
    c = TestClient(app)
    c.post(
        "/api/v1/pipeline/institutions",
        json={"tenant_id": "f1", "name": "A", "stage": PipelineStage.DD.value},
    )
    r = c.get("/api/v1/pipeline/funnel-debug", params={"tenant_id": "f1"})
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_id"] == "f1"
    assert len(body["stages"]) == 5
