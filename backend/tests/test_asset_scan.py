"""向上扫描功能测试：DB层 + 服务层 + API端点。"""
from __future__ import annotations

import pathlib
import time

import pytest
from starlette.testclient import TestClient

from cangjie_fos.main import app as global_app


# ---------------------------------------------------------------------------
# 辅助：隔离 SQLite 到 tmp_path
# ---------------------------------------------------------------------------

@pytest.fixture()
def isolated_db(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """将 DB 路径重定向到临时目录，避免污染开发数据库。"""
    db_file = tmp_path / "test_scan.sqlite"
    monkeypatch.setattr(
        "cangjie_fos.services.pitch_job_db._db_path",
        lambda: str(db_file),
    )
    return tmp_path


# ---------------------------------------------------------------------------
# 1. DB：assets 表可写入并读出
# ---------------------------------------------------------------------------

def test_db_asset_upsert_and_list(isolated_db):
    from cangjie_fos.services.pitch_job_db import db_asset_upsert, db_assets_list

    db_asset_upsert(
        filename="BP.pdf",
        relative_path="docs/BP.pdf",
        full_path="/data/docs/BP.pdf",
        last_modified="2026-04-28",
        summary="商业计划书",
        tags=["融资", "BP"],
        scan_dir="/data",
    )
    rows = db_assets_list()
    assert len(rows) == 1
    assert rows[0]["filename"] == "BP.pdf"
    assert rows[0]["tags"] == ["融资", "BP"]


# ---------------------------------------------------------------------------
# 2. DB：同一 relative_path 二次 upsert 不重复
# ---------------------------------------------------------------------------

def test_db_asset_upsert_idempotent(isolated_db):
    from cangjie_fos.services.pitch_job_db import db_asset_upsert, db_assets_list

    db_asset_upsert(filename="A.pdf", relative_path="A.pdf")
    db_asset_upsert(filename="A_v2.pdf", relative_path="A.pdf", summary="updated")
    rows = db_assets_list()
    assert len(rows) == 1
    assert rows[0]["filename"] == "A_v2.pdf"
    assert rows[0]["summary"] == "updated"


# ---------------------------------------------------------------------------
# 3. DB：scan_config 写入与读取
# ---------------------------------------------------------------------------

def test_db_scan_config_set_and_get(isolated_db):
    from cangjie_fos.services.pitch_job_db import db_scan_config_get, db_scan_config_set

    assert db_scan_config_get() is None
    db_scan_config_set(scan_dir="/some/path", auto_scan=True)
    cfg = db_scan_config_get()
    assert cfg is not None
    assert cfg["scan_dir"] == "/some/path"
    assert cfg["auto_scan"] is True


# ---------------------------------------------------------------------------
# 4. DB：assets_clear 清空记录
# ---------------------------------------------------------------------------

def test_db_assets_clear(isolated_db):
    from cangjie_fos.services.pitch_job_db import db_asset_upsert, db_assets_clear, db_assets_list

    db_asset_upsert(filename="f1.pdf", relative_path="f1.pdf")
    db_asset_upsert(filename="f2.pdf", relative_path="f2.pdf")
    assert len(db_assets_list()) == 2
    deleted = db_assets_clear()
    assert deleted == 2
    assert db_assets_list() == []


# ---------------------------------------------------------------------------
# 5. 服务层：run_scan 扫描真实 tmp 目录
# ---------------------------------------------------------------------------

def test_run_scan_real_dir(isolated_db, tmp_path: pathlib.Path):
    # 在子目录中建文件，避免与 isolated_db 的 sqlite 文件混淆
    scan_root = tmp_path / "assets"
    scan_root.mkdir()
    (scan_root / "subdir").mkdir()
    (scan_root / "BP.pdf").write_bytes(b"%PDF")
    (scan_root / "subdir" / "model.xlsx").write_bytes(b"PK")
    (scan_root / "skip.tmp").write_bytes(b"")  # 应被过滤

    from cangjie_fos.services.asset_scan_service import run_scan

    result = run_scan(scan_dir=str(scan_root))
    assert result["ok"] is True
    assert result["indexed"] == 2   # .tmp 被过滤，2 个有效文件
    assert result["scanned"] == 2


# ---------------------------------------------------------------------------
# 6. 服务层：scan_dir 不存在时返回 ok=False
# ---------------------------------------------------------------------------

def test_run_scan_missing_dir(isolated_db):
    from cangjie_fos.services.asset_scan_service import run_scan

    result = run_scan(scan_dir="/nonexistent/path_xyz_99999")
    assert result["ok"] is False
    assert "error" in result


# ---------------------------------------------------------------------------
# 7. API：POST /api/v1/assets/scan 成功返回 200
# ---------------------------------------------------------------------------

def test_api_scan_trigger_success(isolated_db, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "file.pdf").write_bytes(b"%PDF")

    # patch run_scan so 我们不需要真实文件系统依赖
    monkeypatch.setattr(
        "cangjie_fos.api.routes.assets.run_scan",
        lambda scan_dir=None: {
            "ok": True,
            "scanned": 1,
            "indexed": 1,
            "scan_dir": str(tmp_path),
            "duration_ms": 5,
            "scanned_at": "2026-04-28T00:00:00+00:00",
        },
    )
    with TestClient(global_app) as client:
        resp = client.post("/api/v1/assets/scan")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["indexed"] == 1


# ---------------------------------------------------------------------------
# 8. API：GET /api/v1/assets/scan/config 与 PUT 保存配置
# ---------------------------------------------------------------------------

def test_api_scan_config_get_and_put(isolated_db, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "cangjie_fos.api.routes.assets.get_scan_config",
        lambda: {"scan_dir": "", "auto_scan": False, "configured": False},
    )
    saved = {}

    def fake_save(scan_dir, auto_scan=False):
        saved["scan_dir"] = scan_dir
        saved["auto_scan"] = auto_scan
        return {"scan_dir": scan_dir, "auto_scan": auto_scan, "configured": True}

    monkeypatch.setattr("cangjie_fos.api.routes.assets.save_scan_config", fake_save)

    with TestClient(global_app) as client:
        get_resp = client.get("/api/v1/assets/scan/config")
        assert get_resp.status_code == 200

        put_resp = client.put(
            "/api/v1/assets/scan/config",
            json={"scan_dir": "/my/assets", "auto_scan": True},
        )
    assert put_resp.status_code == 200
    assert saved["scan_dir"] == "/my/assets"
    assert saved["auto_scan"] is True
