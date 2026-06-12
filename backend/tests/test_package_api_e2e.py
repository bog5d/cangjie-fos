"""需求03 — 数据包补全 API E2E（mock 扫描 + 匹配 + 合成）。"""
from __future__ import annotations

import time
import uuid

import pytest
from fastapi.testclient import TestClient

from cangjie_fos.main import create_app
from cangjie_fos.api.routes import package_response as route
from cangjie_fos.services import package_gap_service as gap
from cangjie_fos.services import package_synthesis_service as synth
from cangjie_fos.services.db_base import _connect


@pytest.fixture()
def client():
    return TestClient(create_app(), raise_server_exceptions=False)


def _seed_one_file(folder: str):
    with _connect() as conn:
        conn.execute(
            """INSERT INTO dd_asset_index
               (id, folder_root, file_path, filename, file_type, summary,
                readable, indexed_at, mtime, content_text)
               VALUES (?, ?, ?, '营业执照.pdf', '.pdf', '营业执照', 1, ?, ?, '')""",
            (str(uuid.uuid4()), folder, f"{folder}/营业执照.pdf", time.time(), time.time()),
        )


def test_get_template(client):
    r = client.get("/api/v1/package/template")
    assert r.status_code == 200
    body = r.json()
    assert body["categories"] == ["财务", "法务", "业务"]
    assert len(body["items"]) >= 18


def test_create_session_runs_gap_analysis(client, monkeypatch):
    folder = "/data/e2e_pkg"
    _seed_one_file(folder)
    # 跳过真实扫描；匹配只命中"营业执照"
    monkeypatch.setattr(route, "scan_and_index_folder", lambda f, t: {"indexed": 1})

    def fake_match(items_arg, index_rows):
        for it in items_arg:
            if "营业执照" in it["requirement"]:
                return {it["id"]: {"file_path": f"{folder}/营业执照.pdf",
                                   "filename": "营业执照.pdf", "confidence": 0.95, "reason": "命中"}}
        return {}
    monkeypatch.setattr(gap, "_llm_match_package", fake_match)

    r = client.post("/api/v1/package/sessions", json={"folder_root": folder, "tenant_id": "zt"})
    assert r.status_code == 200
    sid = r.json()["session_id"]

    # BackgroundTask 已在 TestClient 请求结束时执行完
    status = client.get(f"/api/v1/package/sessions/{sid}/status").json()
    assert status["status"] == "done"
    assert status["summary"]["have"] == 1
    assert status["summary"]["missing"] >= 1

    items = client.get(f"/api/v1/package/sessions/{sid}/items").json()
    have = [it for it in items if it["gap_state"] == "have"]
    assert have and have[0]["requirement"] == "营业执照"


def test_create_session_empty_folder_400(client):
    r = client.post("/api/v1/package/sessions", json={"folder_root": "  "})
    assert r.status_code == 400


def test_session_404(client):
    assert client.get("/api/v1/package/sessions/nope").status_code == 404
    assert client.get("/api/v1/package/sessions/nope/items").status_code == 404


def test_item_questions(client, monkeypatch):
    sess = gap.create_session("zt", "/data/q")
    item_id = gap.list_items(sess["session_id"])[0]["id"]
    monkeypatch.setattr(synth, "_llm_questions", lambda req, cat: ["问题1", "问题2"])
    r = client.post(f"/api/v1/package/items/{item_id}/questions")
    assert r.status_code == 200
    assert r.json()["count"] == 2


def test_item_synthesize(client, monkeypatch):
    sess = gap.create_session("zt", "/data/s")
    item_id = gap.list_items(sess["session_id"])[0]["id"]
    monkeypatch.setattr(synth, "_llm_synthesize",
                        lambda req, frag, ex, cat: "合成的材料：注册资本500万。")
    r = client.post(f"/api/v1/package/items/{item_id}/synthesize",
                    json={"fragments": "注册资本500万"})
    assert r.status_code == 200
    assert "500" in r.json()["draft"]
    # 落库
    items = {it["id"]: it for it in gap.list_items(sess["session_id"])}
    assert items[item_id]["draft_answer"]


def test_synthesize_requires_input(client):
    sess = gap.create_session("zt", "/data/s2")
    item_id = gap.list_items(sess["session_id"])[0]["id"]
    r = client.post(f"/api/v1/package/items/{item_id}/synthesize",
                    json={"fragments": "  ", "existing_snippets": ""})
    assert r.status_code == 400


def test_item_questions_404(client):
    assert client.post("/api/v1/package/items/nope/questions").status_code == 404
