"""Wiki API 端点测试。"""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from cangjie_fos.main import app
from cangjie_fos.services.pitch_job_db import _connect, db_wiki_entity_upsert, db_wiki_link_upsert


@pytest.fixture(autouse=True)
def clean_wiki():
    conn = _connect()
    conn.execute("DELETE FROM wiki_entities")
    conn.execute("DELETE FROM wiki_links")
    conn.execute("DELETE FROM wiki_episodes")
    conn.commit()
    conn.close()
    yield


@pytest.fixture
def client():
    return TestClient(app)


# ── GET /api/v1/wiki/entities ──────────────────────────────────────────────

def test_list_entities_empty(client):
    r = client.get("/api/v1/wiki/entities")
    assert r.status_code == 200
    data = r.json()
    assert data["entities"] == []
    assert data["total"] == 0


def test_list_entities_returns_created(client):
    db_wiki_entity_upsert(name="红杉资本", entity_type="institution", summary="头部基金")
    r = client.get("/api/v1/wiki/entities")
    assert r.status_code == 200
    names = [e["name"] for e in r.json()["entities"]]
    assert "红杉资本" in names


def test_list_entities_filter_by_type(client):
    db_wiki_entity_upsert(name="红杉资本", entity_type="institution")
    db_wiki_entity_upsert(name="水导激光", entity_type="technology")
    r = client.get("/api/v1/wiki/entities?entity_type=institution")
    assert r.status_code == 200
    assert len(r.json()["entities"]) == 1
    assert r.json()["entities"][0]["name"] == "红杉资本"


# ── GET /api/v1/wiki/entities/{name} ──────────────────────────────────────

def test_get_entity_page_found(client):
    db_wiki_entity_upsert(name="红杉资本", entity_type="institution", summary="头部基金")
    r = client.get("/api/v1/wiki/entities/红杉资本")
    assert r.status_code == 200
    assert r.json()["name"] == "红杉资本"
    assert "links" in r.json()


def test_get_entity_page_not_found(client):
    r = client.get("/api/v1/wiki/entities/不存在的实体XYZ")
    assert r.status_code == 404


# ── GET /api/v1/wiki/graph ──────────────────────────────────────────────────

def test_get_graph_structure(client):
    db_wiki_entity_upsert(name="红杉资本", entity_type="institution")
    db_wiki_entity_upsert(name="团队稳定性", entity_type="risk")
    db_wiki_link_upsert(
        source_name="红杉资本", target_name="团队稳定性",
        relationship="concerned_about", context="路演追问"
    )
    r = client.get("/api/v1/wiki/graph")
    assert r.status_code == 200
    data = r.json()
    assert "nodes" in data
    assert "edges" in data
    assert len(data["nodes"]) >= 2
    assert len(data["edges"]) >= 1


# ── POST /api/v1/wiki/ingest ────────────────────────────────────────────────

def test_ingest_endpoint_with_mocked_llm(client):
    fake_output = json.dumps({
        "entities": [
            {"name": "测试机构", "type": "institution", "new_facts": ["有兴趣"],
             "current_status": "初步接触", "timeline_event": None}
        ],
        "relationships": [],
    })
    with patch("cangjie_fos.services.wiki_extractor.OpenAI") as MockOpenAI:
        mock_c = MagicMock()
        MockOpenAI.return_value = mock_c
        mock_c.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=fake_output))]
        )
        r = client.post("/api/v1/wiki/ingest", json={
            "text": "这是一段包含测试机构相关内容的足够长的文本，用于测试摄入端点",
            "source_type": "manual_note",
            "source_id": "test_src_001",
        })

    assert r.status_code == 200
    data = r.json()
    assert data["entities_updated"] >= 1
    assert "episode_id" in data


def test_ingest_endpoint_missing_text_returns_422(client):
    r = client.post("/api/v1/wiki/ingest", json={"source_type": "manual_note"})
    assert r.status_code == 422
