"""尽调响应台 API 路由。"""
from __future__ import annotations
import logging
import os
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
from cangjie_fos.services.github_sync import push_dd_session

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
    """
    轮询扫描进度。

    v0.7.2 改进：当内存 _scan_status 中没有记录（如服务重启后），
    降级查询 dd_asset_index 表，返回最近一次索引时间作为 fallback。
    避免前端在重启后永远看到「not_found」。
    """
    if scan_id in _scan_status:
        return _scan_status[scan_id]

    # ── DB fallback：服务重启后内存清空，但 DB 有历史索引记录 ──
    # 提取 scan_id 中的 folder 信息不够准确（scan_id 是时间戳格式），
    # 改为返回全局最新索引时间，让前端知道「之前扫描过」。
    with _connect() as conn:
        row = conn.execute(
            """SELECT folder_root, MAX(indexed_at) as last_scan,
                      COUNT(*) as file_count
               FROM dd_asset_index"""
        ).fetchone()

    if row and row["last_scan"] is not None:
        return {
            "status": "completed",
            "source": "db_fallback",
            "folder_root": row["folder_root"],
            "last_scan_at": row["last_scan"],
            "file_count": row["file_count"],
            "note": "服务重启后从数据库恢复的索引状态。如需重新扫描请再次触发。",
        }

    return {"status": "not_found"}


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
    institution_name: str = Form(""),
):
    """上传尽调清单文件或粘贴文字，解析为需求项列表，创建匹配 session。"""
    if file and file.filename:
        suffix = Path(file.filename).suffix.lower()
        type_map = {".xlsx": "excel", ".xls": "excel", ".docx": "word",
                    ".doc": "word", ".pdf": "pdf"}
        source_type = type_map.get(suffix, "text")
        content = await file.read()
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            items = parse_checklist(tmp_path, source_type)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
        checklist_name = file.filename
    elif text:
        items = parse_checklist(text, "text")
        checklist_name = "粘贴文字"
    else:
        raise HTTPException(400, "必须提供 file 或 text")

    if not items:
        raise HTTPException(400, "清单解析未找到任何需求项，请检查上传内容格式或清单是否为空")

    session_id = create_match_session(tenant_id, checklist_name, folder_root, items, institution_name)

    # 若指定了机构名，尝试更新机构阶段为 DD
    if institution_name.strip():
        try:
            from cangjie_fos.services.institution_store import update_stage_by_name
            updated = update_stage_by_name(tenant_id=tenant_id, name=institution_name.strip(), stage="dd")
            if updated:
                logger.info("机构 %s 阶段已自动更新为 DD", institution_name)
        except Exception as e:
            logger.warning("更新机构阶段失败（不影响主流程）: %s", e)

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
def export_session(session_id: str, req: ExportRequest, background_tasks: BackgroundTasks):
    """将已确认的匹配文件导出到本地文件夹，生成缺失清单，并异步同步到 GitHub。"""
    result = export_to_folder(session_id, req.output_dir)
    background_tasks.add_task(push_dd_session, session_id)
    return result


@router.get("/sessions")
def list_sessions_route(tenant_id: str = "default", limit: int = 10):
    """列出最近的匹配会话（含需求项数量统计）。"""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT s.session_id, s.tenant_id, s.checklist_name, s.folder_root,
                      s.status, s.created_at, s.completed_at, s.institution_name,
                      COUNT(i.id) AS item_count,
                      SUM(CASE WHEN i.user_confirmed = 1 THEN 1 ELSE 0 END) AS confirmed_count
               FROM dd_match_sessions s
               LEFT JOIN dd_match_items i ON i.session_id = s.session_id
               WHERE s.tenant_id = ?
               GROUP BY s.session_id
               ORDER BY s.created_at DESC
               LIMIT ?""",
            (tenant_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/sessions/{session_id}/items/bulk-confirm")
def bulk_confirm_items(session_id: str, min_confidence: float = 0.8):
    """一键确认所有置信度 >= min_confidence 的未确认、未跳过项。"""
    with _connect() as conn:
        conn.execute(
            """UPDATE dd_match_items
               SET user_confirmed = 1
               WHERE session_id = ? AND confidence >= ?
                 AND user_confirmed = 0 AND user_skipped = 0""",
            (session_id, min_confidence),
        )
        row = conn.execute(
            "SELECT COUNT(*) FROM dd_match_items WHERE session_id = ? AND user_confirmed = 1",
            (session_id,),
        ).fetchone()
    return {"ok": True, "confirmed_count": row[0] if row else 0}
