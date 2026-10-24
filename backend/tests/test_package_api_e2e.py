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
    assert body["categories"] == ["财务税务", "法务合规", "业务经营", "团队组织", "技术研发"]
    assert len(body["items"]) >= 45


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
    assert have and have[0]["requirement"] == "营业执照（最新）"

    # 完整度评分随结果出现
    assert 0 < status["summary"]["score"] <= 100


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


# ── 模板管理 API（多套复用 + 在线编辑）────────────────────────

def test_template_list_and_builtin(client):
    rows = client.get("/api/v1/package/templates?tenant_id=apie2e").json()
    assert len(rows) == 1
    assert rows[0]["template_id"] == "standard"
    assert rows[0]["is_builtin"] == 1


def test_template_create_edit_reuse(client):
    # 另存为
    r = client.post("/api/v1/package/templates",
                    json={"name": "并购包", "tenant_id": "apie2e", "copy_from": "standard"})
    assert r.status_code == 200
    tid = r.json()["template_id"]
    # 在线编辑：整体替换
    r2 = client.put(f"/api/v1/package/templates/{tid}/items",
                    json={"tenant_id": "apie2e", "items": [
                        {"category": "财务", "requirement": "审计报告", "importance": "core"},
                        {"category": "法务", "requirement": "公司章程", "importance": "normal"},
                    ]})
    assert r2.json()["item_count"] == 2
    # 复用：基于该模板建会话
    r3 = client.post("/api/v1/package/sessions",
                     json={"folder_root": "/data/tpl", "tenant_id": "apie2e",
                           "template_id": tid, "rescan": False})
    assert r3.status_code == 200
    assert r3.json()["count"] == 2


def test_template_edit_empty_rejected(client):
    r = client.post("/api/v1/package/templates", json={"name": "空包", "tenant_id": "apie2e"})
    tid = r.json()["template_id"]
    r2 = client.put(f"/api/v1/package/templates/{tid}/items",
                    json={"tenant_id": "apie2e", "items": [{"requirement": "  "}]})
    assert r2.status_code == 400


def test_template_builtin_not_deletable(client):
    assert client.delete("/api/v1/package/templates/standard?tenant_id=apie2e").status_code == 400


def test_template_reset(client):
    r = client.post("/api/v1/package/templates/standard/reset?tenant_id=apie2e")
    assert r.status_code == 200
    assert r.json()["item_count"] >= 45


# ── 导出 ────────────────────────────────────────────────────

def test_export_session_zip(client, monkeypatch):
    sess = gap.create_session("apie2e", "/data/exp")
    items = gap.list_items(sess["session_id"])
    from cangjie_fos.services.db_base import _connect
    with _connect() as conn:
        conn.execute("UPDATE package_items SET draft_answer='初稿内容' WHERE id=?",
                     (items[0]["id"],))
    r = client.get(f"/api/v1/package/sessions/{sess['session_id']}/export")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert r.content[:2] == b"PK"  # zip magic


def test_export_404(client):
    assert client.get("/api/v1/package/sessions/nope/export").status_code == 404
