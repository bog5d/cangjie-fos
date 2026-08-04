"""文字稿脱敏 API（上传前防敏感信息外泄）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cangjie_fos.services import desensitize_service as svc

router = APIRouter(prefix="/api/v1/desensitize", tags=["desensitize"])


class DesensitizeRequest(BaseModel):
    text: str
    tenant_id: str = "default"
    categories: list[str] | None = None  # 缺省=全部三类


class TermRequest(BaseModel):
    tenant_id: str = "default"
    category: str  # identity | secret | military
    term: str
    replacement: str = ""


@router.post("/preview")
def preview(req: DesensitizeRequest) -> dict:
    """脱敏预览：返回脱敏文本 + 命中清单，供人工复核后再用去分析。"""
    cats = tuple(req.categories) if req.categories else ("identity", "secret", "military")
    return svc.desensitize(req.text, tenant_id=req.tenant_id, categories=cats)


@router.get("/terms")
def get_terms(tenant_id: str = "default", category: str = "") -> list[dict]:
    """列出团队脱敏词典。"""
    return svc.list_terms(tenant_id, category=category)


@router.post("/terms")
def post_term(req: TermRequest) -> dict:
    """新增一条团队脱敏词条（人名/商密/涉军）。"""
    try:
        tid = svc.add_term(req.tenant_id, req.category, req.term, req.replacement)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "id": tid}


@router.delete("/terms/{term_id}")
def remove_term(term_id: str) -> dict:
    svc.delete_term(term_id)
    return {"ok": True}
