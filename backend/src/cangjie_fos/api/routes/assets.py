"""资产台账 API — 读取 FSS 写入的 asset_index.json 和 FOS 内建扫描功能。"""
from __future__ import annotations

import logging
import uuid
from typing import Any, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from cangjie_fos.core.paths import get_fos_bridge_data_dir
from cangjie_fos.services.asset_index_io import load_asset_index_dict
from cangjie_fos.engine.matchmaker import (
    parse_requirements_from_text,
    result_to_dict,
    run_matching,
)
from cangjie_fos.services.asset_health_service import (
    get_health_dashboard,
    take_health_snapshot,
)
from cangjie_fos.services.asset_scan_service import (
    get_scan_config,
    get_scan_status,
    run_scan,
    save_scan_config,
)
from cangjie_fos.services.pitch_job_db import (
    db_assets_list,
    db_match_session_create,
    db_match_session_get,
    db_match_session_update,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_EMPTY_RESPONSE: dict = {
    "generated_at": None,
    "total_files": 0,
    "assets": [],
    "source_dir": "",
}


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class AssetItem(BaseModel):
    filename: str
    relative_path: str
    full_path: str
    last_modified: str
    summary: str
    tags: List[str]


class AssetIndexResponse(BaseModel):
    generated_at: str | None
    total_files: int
    assets: List[AssetItem]
    source_dir: str
    bridge_dir: str = ""


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _load_safe() -> dict:
    try:
        return load_asset_index_dict()
    except ValueError as e:
        logger.exception("资产索引不合法: %s", e)
        raise HTTPException(
            status_code=500, detail={"code": "E_ASSET_INDEX_INVALID", "message": str(e)}
        ) from e
    except OSError as e:
        logger.exception("资产索引读失败: %s", e)
        raise HTTPException(
            status_code=500, detail={"code": "E_ASSET_INDEX_IO", "message": str(e)}
        ) from e


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------


@router.get("/api/v1/assets", response_model=AssetIndexResponse, tags=["assets"])
def get_assets() -> AssetIndexResponse:
    """返回完整 asset_index（generated_at / total_files / assets / source_dir）。"""
    data = _load_safe()
    assets = [AssetItem(**a) for a in data.get("assets", [])]
    return AssetIndexResponse(
        generated_at=data.get("generated_at"),
        total_files=int(data.get("total_files", len(assets))),
        assets=assets,
        source_dir=str(data.get("source_dir", "")),
        bridge_dir=str(get_fos_bridge_data_dir().resolve()),
    )


@router.get("/api/v1/assets/search", response_model=AssetIndexResponse, tags=["assets"])
def search_assets(
    q: str = Query(default="", description="关键词，在 filename/summary/tags 中匹配（不区分大小写）"),
) -> AssetIndexResponse:
    if not q.strip():
        return get_assets()
    data = _load_safe()
    sub = q.strip().casefold()
    raw_assets = data.get("assets", [])
    filtered = []
    for a in raw_assets:
        if sub in (a.get("filename") or "").casefold():
            filtered.append(a)
            continue
        if sub in (a.get("summary") or "").casefold():
            filtered.append(a)
            continue
        tags = a.get("tags") or []
        if any(sub in (t or "").casefold() for t in tags):
            filtered.append(a)
    return AssetIndexResponse(
        generated_at=data.get("generated_at"),
        total_files=len(filtered),
        assets=[AssetItem(**a) for a in filtered],
        source_dir=str(data.get("source_dir", "")),
        bridge_dir=str(get_fos_bridge_data_dir().resolve()),
    )


# ---------------------------------------------------------------------------
# 扫描配置 & 触发
# ---------------------------------------------------------------------------


class ScanConfigIn(BaseModel):
    scan_dir: str
    auto_scan: bool = False


@router.get("/api/v1/assets/scan/config", tags=["assets"])
def get_scan_config_route() -> dict[str, Any]:
    """返回当前扫描配置。"""
    return get_scan_config()


@router.put("/api/v1/assets/scan/config", tags=["assets"])
def put_scan_config_route(body: ScanConfigIn) -> dict[str, Any]:
    """保存扫描配置（scan_dir + auto_scan）。"""
    return save_scan_config(scan_dir=body.scan_dir, auto_scan=body.auto_scan)


@router.post("/api/v1/assets/scan", tags=["assets"])
def trigger_scan_route(scan_dir: str | None = None) -> dict[str, Any]:
    """触发向上扫描。scan_dir 为空则使用已保存配置的目录。"""
    result = run_scan(scan_dir=scan_dir)
    if not result.get("ok"):
        raise HTTPException(
            status_code=422,
            detail={"code": result.get("error"), "message": result.get("message")},
        )
    return result


# ---------------------------------------------------------------------------
# 资产活力雷达
# ---------------------------------------------------------------------------


@router.get("/api/v1/assets/health", tags=["assets"])
def get_health_route() -> dict[str, Any]:
    """返回最新健康快照 + 趋势数据（前端仪表盘）。"""
    return get_health_dashboard()


@router.post("/api/v1/assets/health/snapshot", tags=["assets"])
def post_health_snapshot_route() -> dict[str, Any]:
    """立即计算当前资产健康分并写入快照表。"""
    return take_health_snapshot()


# ---------------------------------------------------------------------------
# 尽调响应台 MatchMaker V5.0
# ---------------------------------------------------------------------------


class MatchSessionIn(BaseModel):
    institution: str = ""
    req_text: str
    use_llm: bool = False
    top_n: int = 3


class ConfirmIn(BaseModel):
    confirmed_files: list[dict]  # [{"filename": ..., "full_path": ...}, ...]


@router.post("/api/v1/assets/match", tags=["assets"])
def post_match_route(body: MatchSessionIn) -> dict[str, Any]:
    """解析尽调需求文本 → BM25 匹配 → 持久化会话，返回 session_id + 结果。"""
    if not body.req_text.strip():
        raise HTTPException(status_code=422, detail={"code": "E_EMPTY_REQ", "message": "需求文本不能为空"})

    requirements = parse_requirements_from_text(body.req_text, use_llm=body.use_llm)
    if not requirements:
        raise HTTPException(status_code=422, detail={"code": "E_NO_REQ", "message": "未能解析出任何需求条目"})

    assets = db_assets_list(limit=2000)
    results = run_matching(requirements, assets, top_n=body.top_n)

    session_id = str(uuid.uuid4())
    req_dicts = [{"description": r.description, "scene_type": r.scene_type, "time_range": r.time_range}
                 for r in requirements]
    res_dicts = [result_to_dict(r) for r in results]
    db_match_session_create(
        session_id=session_id,
        institution=body.institution,
        req_text=body.req_text,
        requirements=req_dicts,
        results=res_dicts,
    )
    return {
        "session_id": session_id,
        "institution": body.institution,
        "req_count": len(requirements),
        "results": res_dicts,
    }


@router.get("/api/v1/assets/match/{session_id}", tags=["assets"])
def get_match_session_route(session_id: str) -> dict[str, Any]:
    """按 session_id 取匹配会话详情。"""
    session = db_match_session_get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail={"code": "E_SESSION_NOT_FOUND", "message": "会话不存在"})
    return session


@router.post("/api/v1/assets/match/{session_id}/confirm", tags=["assets"])
def post_match_confirm_route(session_id: str, body: ConfirmIn) -> dict[str, Any]:
    """提交人工确认的文件列表，将会话标记为 confirmed。"""
    session = db_match_session_get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail={"code": "E_SESSION_NOT_FOUND", "message": "会话不存在"})
    db_match_session_update(
        session_id,
        status="confirmed",
        confirmed_files=body.confirmed_files,
    )
    return {"session_id": session_id, "status": "confirmed", "confirmed_count": len(body.confirmed_files)}
