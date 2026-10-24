"""需求03 — 数据包「扫描缺口 + 引导提问 + AI 合成」API。

流程：
  POST /api/v1/package/sessions          建会话（按所选模板铺项）+ 后台跑缺口分析
  GET  /api/v1/package/sessions/{id}     会话详情 + 缺口汇总（含完整度评分）
  GET  /api/v1/package/sessions/{id}/items  逐项明细（已有/需更新/缺失）
  GET  /api/v1/package/sessions/{id}/status 分析进度（轮询）
  GET  /api/v1/package/sessions/{id}/export 一键导出 zip（缺口报告 + 合成稿）
  GET  /api/v1/package/sessions          历史会话
  POST /api/v1/package/items/{id}/questions   对缺失项生成引导问题
  POST /api/v1/package/items/{id}/synthesize  合成材料初稿（自动带已有材料正文）

模板管理（多套复用 + 在线编辑）：
  GET    /api/v1/package/templates             模板列表
  GET    /api/v1/package/templates/{id}        模板条目
  POST   /api/v1/package/templates             新建/另存为
  PUT    /api/v1/package/templates/{id}/items  整体替换条目（编辑器保存）
  POST   /api/v1/package/templates/standard/reset 恢复内置默认
  DELETE /api/v1/package/templates/{id}        删除（内置不可删）
  GET    /api/v1/package/template              内置默认种子（只读参考）

与尽调台完全隔离（独立表 package_*），但复用其扫描索引与匹配内核。
"""
from __future__ import annotations

import logging

from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response
from pydantic import BaseModel

from cangjie_fos.services import package_export_service as export
from cangjie_fos.services import package_gap_service as gap
from cangjie_fos.services import package_synthesis_service as synth
from cangjie_fos.services import package_template_store as tpl
from cangjie_fos.services.db_base import _connect
from cangjie_fos.services.dd_index_service import scan_and_index_folder
from cangjie_fos.services.package_template import get_standard_template, template_categories

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/package", tags=["package"])


@router.get("/template")
def get_template():
    """返回内置标准数据包模板的默认内容（种子，只读参考）。"""
    return {"categories": template_categories(), "items": get_standard_template()}


# ── 模板管理（多套复用 + 在线编辑）──────────────────────────────
@router.get("/templates")
def list_templates_route(tenant_id: str = "default"):
    return tpl.list_templates(tenant_id)


@router.get("/templates/{template_id}")
def get_template_route(template_id: str, tenant_id: str = "default"):
    if not tpl.template_exists(template_id, tenant_id):
        raise HTTPException(404, f"模板 {template_id} 不存在")
    return {"template_id": template_id, "items": tpl.get_template_items(template_id, tenant_id)}


class CreateTemplateRequest(BaseModel):
    name: str
    tenant_id: str = "default"
    copy_from: str | None = None


@router.post("/templates")
def create_template_route(req: CreateTemplateRequest):
    """新建模板（copy_from 指定时为"另存为"）。"""
    if not req.name.strip():
        raise HTTPException(400, "模板名不能为空")
    if req.copy_from and not tpl.template_exists(req.copy_from, req.tenant_id):
        raise HTTPException(404, f"源模板 {req.copy_from} 不存在")
    return tpl.create_template(req.name, req.tenant_id, req.copy_from)


class TemplateItemsRequest(BaseModel):
    items: list[dict]
    tenant_id: str = "default"


@router.put("/templates/{template_id}/items")
def replace_template_items_route(template_id: str, req: TemplateItemsRequest):
    """整体替换模板条目（在线编辑器提交全量）。"""
    if not tpl.template_exists(template_id, req.tenant_id):
        raise HTTPException(404, f"模板 {template_id} 不存在")
    n = tpl.replace_items(template_id, req.items, req.tenant_id)
    if n == 0:
        raise HTTPException(400, "至少需要一条有效条目（requirement 非空）")
    return {"ok": True, "item_count": n}


@router.post("/templates/standard/reset")
def reset_builtin_route(tenant_id: str = "default"):
    """把内置标准模板恢复为默认内容。"""
    n = tpl.reset_builtin(tenant_id)
    return {"ok": True, "item_count": n}


@router.delete("/templates/{template_id}")
def delete_template_route(template_id: str, tenant_id: str = "default"):
    if template_id == tpl.BUILTIN_ID:
        raise HTTPException(400, "内置标准模板不可删除（可用 reset 恢复默认）")
    if not tpl.delete_template(template_id, tenant_id):
        raise HTTPException(404, f"模板 {template_id} 不存在")
    return {"ok": True}


class CreateSessionRequest(BaseModel):
    folder_root: str
    tenant_id: str = "default"
    title: str = ""
    template_id: str = "standard"
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

    try:
        result = gap.create_session(req.tenant_id, req.folder_root, req.title, req.template_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
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
    """用零碎回答合成材料初稿（经事实护栏）。

    若该项已匹配到材料库文件，自动把其正文节选作为「已有片段」一并喂给合成
    （需更新场景：旧材料 + 新口述 → 新版初稿）。
    """
    _require_item(item_id)
    if not req.fragments.strip() and not req.existing_snippets.strip():
        raise HTTPException(400, "请提供零碎信息或已有片段，至少一项")
    try:
        return synth.synthesize_for_item(item_id, req.fragments, req.existing_snippets)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/sessions/{session_id}/export")
def export_session(session_id: str):
    """一键导出 zip：缺口报告.md + 全部 AI 合成稿（浏览器直接下载）。"""
    try:
        data, fname = export.build_export_zip(session_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}",
        },
    )
