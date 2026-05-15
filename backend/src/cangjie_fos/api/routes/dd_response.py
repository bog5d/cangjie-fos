"""尽调响应台 API 路由。"""
from __future__ import annotations
import logging
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from cangjie_fos.services.dd_checklist_parser import parse_checklist
from cangjie_fos.services.dd_export_service import export_to_folder
from cangjie_fos.services.dd_index_service import get_index_by_folder, scan_and_index_folder
from cangjie_fos.services.dd_match_service import (
    create_match_session,
    get_session_items,
    run_matching,
)
from cangjie_fos.services.db_base import _connect

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/dd", tags=["due-diligence"])

# 内存扫描进度（简单实现，足够单机使用）
_scan_status: dict[str, dict] = {}


class ScanRequest(BaseModel):
    folder_path: str
    tenant_id: str = "default"


class ExportRequest(BaseModel):
    output_dir: str


class ItemUpdateRequest(BaseModel):
    matched_file_path: str | None = None
    matched_filename: str | None = None
    confidence: float | None = None
    user_confirmed: bool | None = None
    user_skipped: bool | None = None


# ── 索引相关 ────────────────────────────────────────────────

@router.post("/index")
async def start_indexing(req: ScanRequest, background_tasks: BackgroundTasks):
    """触发后台扫描文件夹，建立材料库索引。"""
    scan_id = f"scan_{int(time.time() * 1000)}"
    _scan_status[scan_id] = {"status": "running", "folder": req.folder_path}

    def _do_scan():
        try:
            result = scan_and_index_folder(req.folder_path, req.tenant_id)
            _scan_status[scan_id].update({"status": "done", **result})
        except Exception as e:
            _scan_status[scan_id] = {"status": "error", "error": str(e)}

    background_tasks.add_task(_do_scan)
    return {"scan_id": scan_id, "status": "started"}


@router.get("/index/status/{scan_id}")
def get_scan_status(scan_id: str):
    """轮询扫描进度。"""
    return _scan_status.get(scan_id, {"status": "not_found"})


@router.get("/index")
def list_index(folder_root: str):
    """列出指定文件夹的已索引文件。"""
    return get_index_by_folder(folder_root)


# ── 清单 session 相关 ────────────────────────────────────────

@router.post("/sessions")
async def create_session(
    file: UploadFile | None = File(None),
    text: str | None = Form(None),
    tenant_id: str = Form("default"),
    folder_root: str = Form(...),
):
    """上传尽调清单文件或粘贴文字，解析为需求项列表，创建匹配 session。"""
    if file and file.filename:
        suffix = Path(file.filename).suffix.lower()
        type_map = {".xlsx": "excel", ".xls": "excel", ".docx": "word",
                    ".doc": "word", ".pdf": "pdf"}
        source_type = type_map.get(suffix, "text")
        content = await file.read()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        items = parse_checklist(tmp_path, source_type)
        checklist_name = file.filename
    elif text:
        items = parse_checklist(text, "text")
        checklist_name = "粘贴文字"
    else:
        raise HTTPException(400, "必须提供 file 或 text")

    session_id = create_match_session(tenant_id, checklist_name, folder_root, items)
    return {"session_id": session_id, "items": items, "count": len(items)}


@router.post("/sessions/{session_id}/match")
async def trigger_matching(
    session_id: str,
    folder_root: str,
    background_tasks: BackgroundTasks,
):
    """后台触发 AI 批量匹配。"""
    background_tasks.add_task(run_matching, session_id, folder_root)
    return {"status": "matching_started", "session_id": session_id}


@router.get("/sessions/{session_id}/items")
def list_session_items(session_id: str):
    """获取 session 所有需求项及当前匹配结果。"""
    items = get_session_items(session_id)
    if not items:
        raise HTTPException(404, f"Session {session_id} 不存在或无需求项")
    return items


@router.patch("/sessions/{session_id}/items/{item_id}")
def update_item(session_id: str, item_id: str, req: ItemUpdateRequest):
    """用户手动修改某一项的匹配结果（确认 / 替换 / 标记缺失）。"""
    updates: dict = {}
    if req.matched_file_path is not None:
        updates["matched_file_path"] = req.matched_file_path
    if req.matched_filename is not None:
        updates["matched_filename"] = req.matched_filename
    if req.confidence is not None:
        updates["confidence"] = req.confidence
    if req.user_confirmed is not None:
        updates["user_confirmed"] = 1 if req.user_confirmed else 0
    if req.user_skipped is not None:
        updates["user_skipped"] = 1 if req.user_skipped else 0

    if not updates:
        return {"ok": True}

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with _connect() as conn:
        conn.execute(
            f"UPDATE dd_match_items SET {set_clause} WHERE id = ? AND session_id = ?",
            (*updates.values(), item_id, session_id),
        )
    return {"ok": True}


@router.post("/sessions/{session_id}/export")
def export_session(session_id: str, req: ExportRequest):
    """将已确认的匹配文件导出到本地文件夹，生成缺失清单。"""
    result = export_to_folder(session_id, req.output_dir)
    return result
