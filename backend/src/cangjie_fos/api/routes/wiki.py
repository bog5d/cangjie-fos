"""Wiki 知识图谱 API — 查询实体页面、图谱可视化、手动摄入。"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from cangjie_fos.services.pitch_job_db import db_wiki_entity_list
from cangjie_fos.services.wiki_service import get_entity_page, get_entity_graph, ingest_text_to_wiki

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/wiki", tags=["wiki"])


# ── Pydantic 模型 ─────────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    text: str
    source_type: str
    source_id: str = ""
    model_key: str = "deepseek"


# ── 端点 ──────────────────────────────────────────────────────────────────────

@router.get("/entities")
def list_entities(
    entity_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """列出所有实体（可按 entity_type 过滤）。"""
    entities = db_wiki_entity_list(entity_type=entity_type, limit=limit)
    return {"entities": entities, "total": len(entities)}


@router.get("/entities/{name:path}")
def get_entity(name: str) -> dict[str, Any]:
    """获取单个实体页面（含时间线和链接）。"""
    page = get_entity_page(name)
    if page is None:
        raise HTTPException(status_code=404, detail=f"实体「{name}」不存在")
    return page


@router.get("/graph")
def get_graph(limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    """获取全图（节点 + 边），供前端可视化。"""
    return get_entity_graph(limit=limit)


@router.post("/ingest")
def ingest_text(req: IngestRequest) -> dict[str, Any]:
    """手动摄入文本到 wiki（路演转写/会议纪要/邮件）。"""
    if not req.text.strip():
        raise HTTPException(status_code=422, detail="text 不能为空")
    result = ingest_text_to_wiki(
        text=req.text,
        source_type=req.source_type,
        source_id=req.source_id,
        model_key=req.model_key,
    )
    return result
