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


# ── sync_institutions_from_pitch_jobs 测试 ────────────────────────────────────

def test_sync_institutions_creates_new_from_roadshow_jobs(monkeypatch, tmp_path):
    """有已完成路演 pitch_job 时，sync 应写入 institutions。"""
    import time, uuid
    from cangjie_fos.services.db_base import _db_path as _pitch_db_path, _connect as _pitch_connect, _init_db

    # 隔离两个 DB
    root = tmp_path / "fos_backend2"
    (root / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("cangjie_fos.core.paths.get_backend_root", lambda: root)

    # 写一条真实的 pitch_job（is_roadshow=1, completed）
    pitch_db = root / "data" / "pitch_jobs.sqlite"
    monkeypatch.setattr("cangjie_fos.services.db_base._db_path", lambda: str(pitch_db))
    with _pitch_connect() as conn:
        _init_db(conn)
        conn.execute(
            """INSERT INTO pitch_jobs
               (job_id, tenant_id, status, created_at, institution_id, is_roadshow)
               VALUES (?, ?, 'completed', ?, ?, 1)""",
            (uuid.uuid4().hex, "sync-tenant", time.time(), "明远资本"),
        )
        conn.commit()

    from cangjie_fos.services.institution_store import sync_institutions_from_pitch_jobs, list_institutions
    result = sync_institutions_from_pitch_jobs()

    assert result["synced"] == 1
    assert result["errors"] == 0

    insts = list_institutions(tenant_id="sync-tenant")
    assert len(insts) == 1
    assert insts[0].name == "明远资本"
    assert insts[0].stage.value == "pitched"


def test_sync_institutions_skips_daiqueren_placeholder(monkeypatch, tmp_path):
    """institution_id 以"待确认_"开头的 pitch_job 应被跳过。"""
    import time, uuid
    from cangjie_fos.services.db_base import _connect as _pitch_connect, _init_db

    root = tmp_path / "fos_backend3"
    (root / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("cangjie_fos.core.paths.get_backend_root", lambda: root)

    pitch_db = root / "data" / "pitch_jobs.sqlite"
    monkeypatch.setattr("cangjie_fos.services.db_base._db_path", lambda: str(pitch_db))
    with _pitch_connect() as conn:
        _init_db(conn)
        conn.execute(
            """INSERT INTO pitch_jobs
               (job_id, tenant_id, status, created_at, institution_id, is_roadshow)
               VALUES (?, ?, 'completed', ?, ?, 1)""",
            (uuid.uuid4().hex, "skip-tenant", time.time(), "待确认_2026-05-16"),
        )
        conn.commit()

    from cangjie_fos.services.institution_store import sync_institutions_from_pitch_jobs, list_institutions
    result = sync_institutions_from_pitch_jobs()

    assert result["skipped"] >= 1
    insts = list_institutions(tenant_id="skip-tenant")
    assert len(insts) == 0


def test_sync_institutions_no_downgrade(monkeypatch, tmp_path):
    """已有 stage=dd 的机构，sync 后不应降级为 pitched。"""
    import time, uuid
    from cangjie_fos.services.db_base import _connect as _pitch_connect, _init_db
    from cangjie_fos.services.institution_store import create_institution, list_institutions
    from cangjie_fos.schemas.institution import InstitutionProfileCreate, PipelineStage

    root = tmp_path / "fos_backend4"
    (root / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("cangjie_fos.core.paths.get_backend_root", lambda: root)

    # 先建一个 DD 阶段的机构
    create_institution(InstitutionProfileCreate(
        tenant_id="nd-tenant", name="高瓴资本", stage=PipelineStage.DD,
    ))

    # pitch_job 里也有这家机构（但阶段应保留 DD，不降级）
    pitch_db = root / "data" / "pitch_jobs.sqlite"
    monkeypatch.setattr("cangjie_fos.services.db_base._db_path", lambda: str(pitch_db))
    with _pitch_connect() as conn:
        _init_db(conn)
        conn.execute(
            """INSERT INTO pitch_jobs
               (job_id, tenant_id, status, created_at, institution_id, is_roadshow)
               VALUES (?, ?, 'completed', ?, ?, 1)""",
            (uuid.uuid4().hex, "nd-tenant", time.time(), "高瓴资本"),
        )
        conn.commit()

    from cangjie_fos.services.institution_store import sync_institutions_from_pitch_jobs
    result = sync_institutions_from_pitch_jobs()

    assert result["skipped"] >= 1  # 已有 DD 阶段，不写入

    insts = list_institutions(tenant_id="nd-tenant")
    assert len(insts) == 1
    assert insts[0].stage.value == "dd"  # 未被降级


def test_sync_institutions_endpoint(monkeypatch, tmp_path):
    """POST /api/v1/pipeline/sync-institutions 应返回 ok=True。"""
    root = tmp_path / "fos_backend5"
    (root / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("cangjie_fos.core.paths.get_backend_root", lambda: root)

    c = TestClient(app)
    r = c.post("/api/v1/pipeline/sync-institutions")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "synced" in body
    assert "skipped" in body
    assert "errors" in body
