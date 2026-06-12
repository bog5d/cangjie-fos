"""需求03 — 数据包「扫描缺口 + 引导提问 + AI 合成」API。

流程：
  POST /api/v1/package/sessions          建会话（按标准模板铺项）+ 后台跑缺口分析
  GET  /api/v1/package/sessions/{id}     会话详情 + 缺口汇总
  GET  /api/v1/package/sessions/{id}/items  逐项明细（已有/需更新/缺失）
  GET  /api/v1/package/sessions/{id}/status 分析进度（轮询）
  GET  /api/v1/package/sessions          历史会话
  POST /api/v1/package/items/{id}/questions   对缺失项生成引导问题
  POST /api/v1/package/items/{id}/synthesize  用零碎回答合成材料初稿
  GET  /api/v1/package/template          查看标准模板

与尽调台完全隔离（独立表 package_*），但复用其扫描索引与匹配内核。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from cangjie_fos.services import package_gap_service as gap
from cangjie_fos.services import package_synthesis_service as synth
from cangjie_fos.services.db_base import _connect
from cangjie_fos.services.dd_index_service import scan_and_index_folder
from cangjie_fos.services.package_template import get_standard_template, template_categories

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/package", tags=["package"])


@router.get("/template")
def get_template():
    """返回内置标准数据包模板（维度 + 条目）。"""
    return {"categories": template_categories(), "items": get_standard_template()}


class CreateSessionRequest(BaseModel):
    folder_root: str
    tenant_id: str = "default"
    title: str = ""
    rescan: bool = True


@router.post("/sessions")
def create_package_session(req: CreateSessionRequest, background_tasks: BackgroundTasks):
    """建会话：可选重新扫描材料库 → 铺标准模板 → 后台跑缺口分析。"""
    if not req.folder_root.strip():
        raise HTTPException(400, "folder_root 不能为空")

    if req.rescan:
        try:
            scan_and_index_folder(req.folder_root, req.tenant_id)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception as e:  # noqa: BLE001
            logger.error("数据包扫描失败: %s", e)
            raise HTTPException(500, f"材料库扫描失败：{e}")

    result = gap.create_session(req.tenant_id, req.folder_root, req.title)
    background_tasks.add_task(gap.run_gap_analysis, result["session_id"], req.folder_root)
    return {"session_id": result["session_id"], "count": result["count"], "status": "analyzing"}


@router.get("/sessions")
def list_package_sessions(tenant_id: str = "default", limit: int = 10):
    return gap.list_sessions(tenant_id, limit)


@router.get("/sessions/{session_id}")
def get_package_session(session_id: str):
    session = gap.get_session(session_id)
    if not session:
        raise HTTPException(404, f"会话 {session_id} 不存在")
    session["summary"] = gap.gap_summary(session_id)
    return session


@router.get("/sessions/{session_id}/items")
def get_package_items(session_id: str):
    if not gap.get_session(session_id):
        raise HTTPException(404, f"会话 {session_id} 不存在")
    return gap.list_items(session_id)


@router.get("/sessions/{session_id}/status")
def get_package_status(session_id: str):
    """轮询分析进度：status + 缺口汇总。"""
    session = gap.get_session(session_id)
    if not session:
        raise HTTPException(404, f"会话 {session_id} 不存在")
    return {"status": session["status"], "summary": gap.gap_summary(session_id)}


def _require_item(item_id: str) -> dict:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM package_items WHERE id = ?", (item_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, f"条目 {item_id} 不存在")
    return dict(row)


@router.post("/items/{item_id}/questions")
def gen_item_questions(item_id: str):
    """对一个缺失项生成引导问题。"""
    item = _require_item(item_id)
    questions = synth.generate_guiding_questions(item["requirement"], item.get("category", ""))
    return {"questions": questions, "count": len(questions)}


class SynthesizeRequest(BaseModel):
    fragments: str
    existing_snippets: str = ""


@router.post("/items/{item_id}/synthesize")
def synthesize_item(item_id: str, req: SynthesizeRequest):
    """用用户零碎回答 + 已有片段合成材料初稿（经事实护栏）。"""
    item = _require_item(item_id)
    if not req.fragments.strip() and not req.existing_snippets.strip():
        raise HTTPException(400, "请提供零碎信息或已有片段，至少一项")
    synth.save_fragments(item_id, req.fragments)
    result = synth.synthesize_material(
        item["requirement"], req.fragments, req.existing_snippets, item.get("category", ""),
    )
    synth.save_draft(item_id, result["draft"])
    return result
