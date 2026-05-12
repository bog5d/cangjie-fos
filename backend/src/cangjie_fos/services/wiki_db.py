"""Wiki 知识图谱持久化层：实体、链接、Episodes。

所有写操作通过 db_base._write_lock 序列化，连接由 db_base._connect 管理。
"""
from __future__ import annotations

import json
import uuid as _uuid_mod
import time
from typing import Any

from cangjie_fos.services.db_base import _connect, _write_lock


# ─────────────────────────────────────────────────────────────────
# 实体 CRUD
# ─────────────────────────────────────────────────────────────────

def db_wiki_entity_upsert(
    *,
    name: str,
    entity_type: str = "concept",
    aliases: list[str] | None = None,
    profile_json: dict[str, Any] | None = None,
    summary: str = "",
    confidence: float = 1.0,
    timeline_event: dict[str, Any] | None = None,
) -> None:
    """插入或更新实体页面。timeline_event 会追加到时间线，而非覆盖。"""
    now = time.time()
    with _write_lock:
        conn = _connect()
        try:
            cur = conn.execute(
                "SELECT timeline_json FROM wiki_entities WHERE name = ?", (name,)
            )
            row = cur.fetchone()
            if row:
                try:
                    existing_timeline: list[dict[str, Any]] = json.loads(row["timeline_json"])
                except (json.JSONDecodeError, TypeError):
                    existing_timeline = []
            else:
                existing_timeline = []

            if timeline_event:
                existing_timeline.append({
                    "date": timeline_event.get("date") or "",
                    "event": timeline_event.get("event") or "",
                    "recorded_at": now,
                })

            conn.execute(
                """
                INSERT INTO wiki_entities
                    (name, entity_type, aliases, profile_json, timeline_json, summary, confidence, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    entity_type   = excluded.entity_type,
                    aliases       = excluded.aliases,
                    profile_json  = excluded.profile_json,
                    timeline_json = excluded.timeline_json,
                    summary       = CASE WHEN excluded.summary != '' THEN excluded.summary ELSE wiki_entities.summary END,
                    confidence    = excluded.confidence,
                    updated_at    = excluded.updated_at
                """,
                (
                    name,
                    entity_type,
                    json.dumps(aliases or [], ensure_ascii=False),
                    json.dumps(profile_json or {}, ensure_ascii=False),
                    json.dumps(existing_timeline, ensure_ascii=False),
                    summary,
                    confidence,
                    now,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()


def db_wiki_entity_get(name: str) -> dict[str, Any] | None:
    """读取单个实体页面，返回 None 如果不存在。JSON 字段自动解析。"""
    conn = _connect()
    try:
        cur = conn.execute("SELECT * FROM wiki_entities WHERE name = ?", (name,))
        row = cur.fetchone()
        if row is None:
            return None
        d = dict(row)
        for col in ("aliases", "profile_json", "timeline_json"):
            raw = d.get(col)
            if isinstance(raw, str):
                try:
                    d[col] = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    d[col] = [] if col != "profile_json" else {}
        return d
    finally:
        conn.close()


def db_wiki_entity_list(
    entity_type: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """列出所有（或指定类型）实体，按 updated_at 倒序。"""
    conn = _connect()
    try:
        if entity_type:
            cur = conn.execute(
                "SELECT * FROM wiki_entities WHERE entity_type = ? ORDER BY updated_at DESC LIMIT ?",
                (entity_type, limit),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM wiki_entities ORDER BY updated_at DESC LIMIT ?", (limit,)
            )
        rows = cur.fetchall()
    finally:
        conn.close()

    result = []
    for row in rows:
        d = dict(row)
        for col in ("aliases", "profile_json", "timeline_json"):
            raw = d.get(col)
            if isinstance(raw, str):
                try:
                    d[col] = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    d[col] = [] if col != "profile_json" else {}
        result.append(d)
    return result


# ─────────────────────────────────────────────────────────────────
# 链接 CRUD
# ─────────────────────────────────────────────────────────────────

def db_wiki_link_upsert(
    *,
    source_name: str,
    target_name: str,
    relationship: str,
    context: str = "",
    strength: float = 1.0,
    source_doc: str = "",
    invalidate: bool = False,
) -> None:
    """建立或更新双向链接。invalidate=True 时标记该链接为失效（Zep 模式）。"""
    now = time.time()
    with _write_lock:
        conn = _connect()
        try:
            if invalidate:
                conn.execute(
                    """
                    UPDATE wiki_links SET invalid_at = ?
                    WHERE source_name = ? AND target_name = ? AND relationship = ?
                      AND invalid_at IS NULL
                    """,
                    (now, source_name, target_name, relationship),
                )
            else:
                link_id = str(_uuid_mod.uuid4())
                conn.execute(
                    """
                    INSERT INTO wiki_links
                        (id, source_name, target_name, relationship, context, strength, source_doc, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_name, target_name, relationship) DO UPDATE SET
                        context    = excluded.context,
                        strength   = excluded.strength,
                        source_doc = excluded.source_doc,
                        invalid_at = NULL
                    """,
                    (link_id, source_name, target_name, relationship, context, strength, source_doc, now),
                )
            conn.commit()
        finally:
            conn.close()


def db_wiki_links_for(
    entity_name: str,
    include_invalid: bool = False,
) -> list[dict[str, Any]]:
    """返回某实体的所有出向链接（source = entity_name）。"""
    conn = _connect()
    try:
        if include_invalid:
            cur = conn.execute(
                "SELECT * FROM wiki_links WHERE source_name = ? ORDER BY created_at DESC",
                (entity_name,),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM wiki_links WHERE source_name = ? AND invalid_at IS NULL ORDER BY created_at DESC",
                (entity_name,),
            )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────
# Episodes（原始文档摄入记录）
# ─────────────────────────────────────────────────────────────────

def db_wiki_episode_insert(
    *,
    source_type: str,
    source_id: str,
    raw_text: str,
    entity_names: list[str],
) -> str:
    """记录一次摄入事件，返回新建的 episode id。"""
    episode_id = str(_uuid_mod.uuid4())
    now = time.time()
    with _write_lock:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO wiki_episodes (id, source_type, source_id, raw_text, entity_names, extracted_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (episode_id, source_type, source_id, raw_text, json.dumps(entity_names, ensure_ascii=False), now),
            )
            conn.commit()
        finally:
            conn.close()
    return episode_id


def db_wiki_episodes_for_source(source_id: str) -> list[dict[str, Any]]:
    """按 source_id 查询 episodes，entity_names 自动反序列化。"""
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT * FROM wiki_episodes WHERE source_id = ? ORDER BY extracted_at DESC",
            (source_id,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    result = []
    for row in rows:
        d = dict(row)
        raw = d.get("entity_names")
        if isinstance(raw, str):
            try:
                d["entity_names"] = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                d["entity_names"] = []
        result.append(d)
    return result
