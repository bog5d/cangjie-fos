"""Wiki 业务协调层：衔接 wiki_extractor（提炼）和 pitch_job_db（写库）。

外部调用入口：ingest_text_to_wiki(text, source_type, source_id)
"""
from __future__ import annotations

import logging
from typing import Any

from cangjie_fos.services.pitch_job_db import (
    db_wiki_entity_get,
    db_wiki_entity_list,
    db_wiki_entity_upsert,
    db_wiki_episode_insert,
    db_wiki_link_upsert,
    db_wiki_links_for,
)
from cangjie_fos.services.wiki_extractor import extract_entities_from_text

logger = logging.getLogger(__name__)


def ingest_text_to_wiki(
    text: str,
    source_type: str,
    source_id: str = "",
    model_key: str = "deepseek",
) -> dict[str, Any]:
    """主入口：提炼文本中的实体，更新实体页面，建立双向链接，记录 episode。

    Returns:
        {
            "entities_updated": int,   # 本次更新/创建的实体数
            "links_updated": int,      # 本次建立/更新的链接数
            "episode_id": str,         # 本次摄入的 episode ID
        }
    """
    extraction = extract_entities_from_text(text=text, source_type=source_type, model_key=model_key)
    entities = extraction["entities"]
    relationships = extraction["relationships"]

    if not entities and not relationships:
        logger.debug("wiki_service.ingest: 无实体提炼结果，跳过 source_id=%s", source_id)
        episode_id = db_wiki_episode_insert(
            source_type=source_type, source_id=source_id, raw_text=text[:500], entity_names=[]
        )
        return {"entities_updated": 0, "links_updated": 0, "episode_id": episode_id}

    entity_names: list[str] = []
    for e in entities:
        db_wiki_entity_upsert(
            name=e["name"],
            entity_type=e["type"],
            summary=e["current_status"],
            timeline_event=e["timeline_event"],
        )
        entity_names.append(e["name"])
        logger.debug("wiki_service: 更新实体 %r (type=%s)", e["name"], e["type"])

    links_updated = 0
    for rel in relationships:
        src, tgt = rel["source"], rel["target"]
        # 仅链接已被本次提炼识别的实体，避免幽灵链接
        if src not in entity_names or tgt not in entity_names:
            continue
        db_wiki_link_upsert(
            source_name=src,
            target_name=tgt,
            relationship=rel["relationship"],
            context=rel["context"],
            source_doc=source_id,
        )
        links_updated += 1

    episode_id = db_wiki_episode_insert(
        source_type=source_type,
        source_id=source_id,
        raw_text=text[:500],
        entity_names=entity_names,
    )

    logger.info(
        "wiki_service.ingest done source_id=%s entities=%d links=%d episode=%s",
        source_id, len(entity_names), links_updated, episode_id,
    )
    return {
        "entities_updated": len(entity_names),
        "links_updated": links_updated,
        "episode_id": episode_id,
    }


def get_entity_page(name: str) -> dict[str, Any] | None:
    """获取单个实体页面，附带出向链接。"""
    entity = db_wiki_entity_get(name)
    if entity is None:
        return None
    entity["links"] = db_wiki_links_for(name, include_invalid=False)
    return entity


def get_entity_graph(limit: int = 50) -> dict[str, Any]:
    """返回全图：实体节点 + 链接列表，供前端可视化。"""
    from cangjie_fos.services.pitch_job_db import _connect
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT * FROM wiki_links WHERE invalid_at IS NULL ORDER BY created_at DESC LIMIT 200"
        )
        all_links = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

    entities = db_wiki_entity_list(limit=limit)
    return {
        "nodes": [{"name": e["name"], "type": e["entity_type"], "summary": e["summary"]} for e in entities],
        "edges": [
            {
                "source": lk["source_name"],
                "target": lk["target_name"],
                "relationship": lk["relationship"],
                "context": lk["context"],
            }
            for lk in all_links
        ],
    }
