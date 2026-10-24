"""夜间知识整合：清理低置信度实体、更新 summary、报告整合结果。

由 APScheduler 每晚调用，与 nightly_settle 并列运行。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from cangjie_fos.services.pitch_job_db import (
    _connect,
    db_wiki_entity_get,
    db_wiki_entity_list,
    db_wiki_entity_upsert,
)

logger = logging.getLogger(__name__)

_STALE_DAYS = 90  # 超过此天数未更新的实体视为陈旧


def consolidate_wiki() -> dict[str, Any]:
    """执行夜间知识整合，返回整合报告。

    步骤：
    1. 统计当前实体总数和链接总数
    2. 识别陈旧实体（>90 天未更新）
    3. 更新各实体的 summary（基于时间线最新条目）
    4. 返回整合报告

    注意：不删除任何数据，只标记和更新。
    """
    entities = db_wiki_entity_list(limit=2000)
    today = datetime.now(tz=timezone.utc)

    conn = _connect()
    try:
        cur = conn.execute("SELECT COUNT(*) as cnt FROM wiki_links WHERE invalid_at IS NULL")
        active_links = cur.fetchone()["cnt"]
    finally:
        conn.close()

    stale_names: list[str] = []
    updated_summaries = 0

    for entity in entities:
        updated_at = entity.get("updated_at", 0)
        days_since_update = (today.timestamp() - updated_at) / 86400

        if days_since_update > _STALE_DAYS:
            stale_names.append(entity["name"])

        # 如果实体有时间线但 summary 为空，用最新时间线条目更新 summary
        timeline = entity.get("timeline_json", [])
        if timeline and not entity.get("summary"):
            latest_event = timeline[-1]
            auto_summary = latest_event.get("event", "")[:100]
            if auto_summary:
                db_wiki_entity_upsert(
                    name=entity["name"],
                    entity_type=entity["entity_type"],
                    summary=auto_summary,
                )
                updated_summaries += 1

    report = {
        "consolidated_at": today.isoformat(),
        "total_entities": len(entities),
        "total_active_links": active_links,
        "stale_entities": stale_names[:20],
        "stale_count": len(stale_names),
        "summaries_updated": updated_summaries,
    }

    logger.info(
        "wiki_consolidator done: entities=%d links=%d stale=%d summaries_updated=%d",
        len(entities), active_links, len(stale_names), updated_summaries,
    )
    return report
