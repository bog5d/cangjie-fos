"""资产台账 API 测试。"""
from __future__ import annotations

import json
import pathlib

import pytest
from starlette.testclient import TestClient

from cangjie_fos.main import app as global_app

_SAMPLE = {
    "generated_at": "2026-04-14T11:04:49",
    "source_dir": "D:\\test\\assets",
    "total_files": 2,
    "assets": [
        {
            "filename": "BP.pdf",
            "relative_path": "",
            "full_path": "D:\\test\\assets\\BP.pdf",
            "last_modified": "2026-04-14",
            "summary": "商业计划书",
            "tags": ["融资", "BP"],
        },
        {
            "filename": "财务模型.xlsx",
            "relative_path": "财务",
            "full_path": "D:\\test\\assets\\财务\\财务模型.xlsx",
            "last_modified": "2026-04-10",
            "summary": "",
            "tags": ["财务"],
        },
    ],
}


@pytest.fixture()
def mock_asset_dir(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """重定向桥目录到临时目录，同时让 SQLite 返回空（强制走桥接文件回退）。"""

    def _tmp() -> pathlib.Path:
        return tmp_path

    monkeypatch.setattr("cangjie_fos.api.routes.assets.get_fos_bridge_data_dir", _tmp)
    monkeypatch.setattr(
        "cangjie_fos.services.asset_index_io._fos_paths.get_fos_bridge_data_dir",
        _tmp,
    )
    # 让 db_assets_list 返回空，强制走 FSS 桥接文件回退分支
    monkeypatch.setattr(
        "cangjie_fos.api.routes.assets.db_assets_list",
        lambda **_: [],
    )
    return tmp_path


def _write_index(d: pathlib.Path, data: dict | None = None) -> None:
    (d / "asset_index.json").write_text(
        json.dumps(data or _SAMPLE, ensure_ascii=False), encoding="utf-8"
    )


# --- GET /api/v1/assets ---

def test_get_assets_returns_200(mock_asset_dir):
    _write_index(mock_asset_dir)
    c = TestClient(global_app)
    r = c.get("/api/v1/assets")
    assert r.status_code == 200
    data = r.json()
    assert data["total_files"] == 2
    assert len(data["assets"]) == 2
    assert data["generated_at"] == "2026-04-14T11:04:49"
    assert data.get("bridge_dir") == str(mock_asset_dir.resolve())


def test_get_assets_file_not_exist_returns_empty(mock_asset_dir):
    # 不写文件 → 空结构 200
    c = TestClient(global_app)
    r = c.get("/api/v1/assets")
    assert r.status_code == 200
    data = r.json()
    assert data["total_files"] == 0
    assert data["assets"] == []
    assert data["generated_at"] is None


def test_get_assets_schema(mock_asset_dir):
    _write_index(mock_asset_dir)
    c = TestClient(global_app)
    r = c.get("/api/v1/assets")
    asset = r.json()["assets"][0]
    assert "filename" in asset
    assert "summary" in asset
    assert isinstance(asset["tags"], list)


# --- GET /api/v1/assets/search ---

def test_search_by_filename(mock_asset_dir):
    _write_index(mock_asset_dir)
    c = TestClient(global_app)
    r = c.get("/api/v1/assets/search?q=BP")
    assert r.status_code == 200
    data = r.json()
    assert data["total_files"] == 1
    assert data["assets"][0]["filename"] == "BP.pdf"


def test_search_by_summary(mock_asset_dir):
    _write_index(mock_asset_dir)
    c = TestClient(global_app)
    r = c.get("/api/v1/assets/search?q=商业计划书")
    assert r.status_code == 200
    assert r.json()["total_files"] == 1


def test_search_by_tag(mock_asset_dir):
    _write_index(mock_asset_dir)
    c = TestClient(global_app)
    r = c.get("/api/v1/assets/search?q=财务")
    assert r.status_code == 200
    filenames = [a["filename"] for a in r.json()["assets"]]
    assert "财务模型.xlsx" in filenames


def test_search_empty_q_returns_all(mock_asset_dir):
    _write_index(mock_asset_dir)
    c = TestClient(global_app)
    r = c.get("/api/v1/assets/search?q=")
    assert r.status_code == 200
    assert r.json()["total_files"] == 2


def test_search_no_match(mock_asset_dir):
    _write_index(mock_asset_dir)
    c = TestClient(global_app)
    r = c.get("/api/v1/assets/search?q=完全不存在的词xyzxyz")
    assert r.status_code == 200
    assert r.json()["total_files"] == 0
    assert r.json()["assets"] == []


def test_search_case_insensitive(mock_asset_dir):
    _write_index(mock_asset_dir)
    c = TestClient(global_app)
    r = c.get("/api/v1/assets/search?q=bp")  # lowercase
    assert r.status_code == 200
    assert r.json()["total_files"] == 1


# --- POST /api/v1/assets/bundle ---

def test_bundle_creates_confirmed_session():
    """直接打包接口：返回 confirmed 状态和 file_count。"""
    c = TestClient(global_app)
    files = [
        {"filename": "BP.pdf", "full_path": "D:\\test\\BP.pdf", "relative_path": ""},
        {"filename": "财务模型.xlsx", "full_path": "D:\\test\\财务模型.xlsx", "relative_path": "财务"},
    ]
    r = c.post("/api/v1/assets/bundle", json={"institution": "红杉资本", "files": files})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "confirmed"
    assert data["file_count"] == 2
    assert data["institution"] == "红杉资本"
    assert "session_id" in data


def test_bundle_empty_files_returns_422():
    """空文件列表应返回 422。"""
    c = TestClient(global_app)
    r = c.post("/api/v1/assets/bundle", json={"institution": "", "files": []})
    assert r.status_code == 422


def test_bundle_no_institution():
    """机构名称可为空。"""
    c = TestClient(global_app)
    files = [{"filename": "BP.pdf", "full_path": "", "relative_path": ""}]
    r = c.post("/api/v1/assets/bundle", json={"institution": "", "files": files})
    assert r.status_code == 200
    assert r.json()["status"] == "confirmed"
