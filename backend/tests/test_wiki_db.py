"""wiki_entities / wiki_links / wiki_episodes DB CRUD 单元测试。"""
from __future__ import annotations

import time
import pytest
from cangjie_fos.services.pitch_job_db import (
    _connect,
    db_wiki_entity_upsert,
    db_wiki_entity_get,
    db_wiki_entity_list,
    db_wiki_link_upsert,
    db_wiki_links_for,
    db_wiki_episode_insert,
    db_wiki_episodes_for_source,
)


# ── 固件 ──────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_wiki_tables():
    """每个测试前清空 wiki 三张表，保证隔离性。"""
    conn = _connect()
    conn.execute("DELETE FROM wiki_entities")
    conn.execute("DELETE FROM wiki_links")
    conn.execute("DELETE FROM wiki_episodes")
    conn.commit()
    conn.close()
    yield


# ── wiki_entities ─────────────────────────────────────────────────────────────

def test_entity_upsert_and_get_basic():
    """新建实体后能读回，字段完整。"""
    db_wiki_entity_upsert(
        name="红杉资本",
        entity_type="institution",
        summary="头部美元基金",
    )
    e = db_wiki_entity_get("红杉资本")
    assert e is not None
    assert e["name"] == "红杉资本"
    assert e["entity_type"] == "institution"
    assert e["summary"] == "头部美元基金"
    assert isinstance(e["timeline_json"], list)
    assert isinstance(e["profile_json"], dict)
    assert isinstance(e["aliases"], list)


def test_entity_upsert_idempotent():
    """同名实体 upsert 两次不报错，更新 summary。"""
    db_wiki_entity_upsert(name="红杉资本", entity_type="institution", summary="v1")
    db_wiki_entity_upsert(name="红杉资本", entity_type="institution", summary="v2")
    e = db_wiki_entity_get("红杉资本")
    assert e["summary"] == "v2"


def test_entity_upsert_appends_timeline():
    """带 timeline_event 的 upsert 会追加时间线，不覆盖。"""
    db_wiki_entity_upsert(
        name="红杉资本",
        entity_type="institution",
        timeline_event={"date": "2026-03-10", "event": "初次接触"},
    )
    db_wiki_entity_upsert(
        name="红杉资本",
        entity_type="institution",
        timeline_event={"date": "2026-04-15", "event": "二轮会议，提出团队担忧"},
    )
    e = db_wiki_entity_get("红杉资本")
    assert len(e["timeline_json"]) == 2
    assert e["timeline_json"][0]["date"] == "2026-03-10"
    assert e["timeline_json"][1]["date"] == "2026-04-15"


def test_entity_get_nonexistent_returns_none():
    result = db_wiki_entity_get("不存在的实体XYZ")
    assert result is None


def test_entity_list_empty():
    entities = db_wiki_entity_list()
    assert entities == []


def test_entity_list_returns_all():
    db_wiki_entity_upsert(name="红杉资本", entity_type="institution")
    db_wiki_entity_upsert(name="水导激光技术", entity_type="technology")
    entities = db_wiki_entity_list()
    names = [e["name"] for e in entities]
    assert "红杉资本" in names
    assert "水导激光技术" in names


def test_entity_list_filter_by_type():
    db_wiki_entity_upsert(name="红杉资本", entity_type="institution")
    db_wiki_entity_upsert(name="水导激光技术", entity_type="technology")
    institutions = db_wiki_entity_list(entity_type="institution")
    assert len(institutions) == 1
    assert institutions[0]["name"] == "红杉资本"


# ── wiki_links ────────────────────────────────────────────────────────────────

def test_link_upsert_and_query():
    """建立两个实体后写链接，能通过 source 查到。"""
    db_wiki_entity_upsert(name="红杉资本", entity_type="institution")
    db_wiki_entity_upsert(name="团队稳定性", entity_type="risk")
    db_wiki_link_upsert(
        source_name="红杉资本",
        target_name="团队稳定性",
        relationship="concerned_about",
        context="二轮会议追问",
    )
    links = db_wiki_links_for("红杉资本")
    assert len(links) == 1
    assert links[0]["target_name"] == "团队稳定性"
    assert links[0]["relationship"] == "concerned_about"


def test_link_upsert_idempotent():
    """相同 (source, target, relationship) 二次 upsert 不重复。"""
    db_wiki_entity_upsert(name="红杉资本", entity_type="institution")
    db_wiki_entity_upsert(name="团队稳定性", entity_type="risk")
    db_wiki_link_upsert(source_name="红杉资本", target_name="团队稳定性", relationship="concerned_about")
    db_wiki_link_upsert(source_name="红杉资本", target_name="团队稳定性", relationship="concerned_about")
    links = db_wiki_links_for("红杉资本")
    assert len(links) == 1


def test_link_invalidate():
    """invalidate=True 时 invalid_at 被设置，查询时默认过滤掉失效链接。"""
    db_wiki_entity_upsert(name="红杉资本", entity_type="institution")
    db_wiki_entity_upsert(name="团队稳定性", entity_type="risk")
    db_wiki_link_upsert(source_name="红杉资本", target_name="团队稳定性", relationship="concerned_about")
    db_wiki_link_upsert(
        source_name="红杉资本", target_name="团队稳定性",
        relationship="concerned_about", invalidate=True
    )
    links = db_wiki_links_for("红杉资本", include_invalid=False)
    assert links == []
    links_all = db_wiki_links_for("红杉资本", include_invalid=True)
    assert len(links_all) == 1


# ── wiki_episodes ─────────────────────────────────────────────────────────────

def test_episode_insert_and_query():
    episode_id = db_wiki_episode_insert(
        source_type="pitch_recording",
        source_id="job_abc123",
        raw_text="红杉二轮会议录音转写内容",
        entity_names=["红杉资本", "水导激光技术"],
    )
    assert episode_id is not None
    episodes = db_wiki_episodes_for_source("job_abc123")
    assert len(episodes) == 1
    assert episodes[0]["source_type"] == "pitch_recording"
    assert "红杉资本" in episodes[0]["entity_names"]


def test_episode_insert_no_source_id():
    """source_id 为空时也能插入。"""
    episode_id = db_wiki_episode_insert(
        source_type="manual_note",
        source_id="",
        raw_text="手动添加的会议记录",
        entity_names=[],
    )
    assert episode_id is not None
