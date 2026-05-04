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
    get_default_matcher,
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
    db_asset_status_update,
    db_institution_archive_get,
    db_institution_match_profile,
    db_institutions_list,
    db_match_outcome_batch_save,
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
    """返回完整资产列表（优先读 FOS 内建扫描的 SQLite；若 SQLite 为空则回退到 FSS 桥接文件）。"""
    db_rows = db_assets_list(limit=2000)
    if db_rows:
        cfg = get_scan_config()
        # 取最新一条的 indexed_at 作为 generated_at
        latest_ts = db_rows[0].get("indexed_at")
        try:
            from datetime import datetime, timezone  # noqa: PLC0415
            generated_at = datetime.fromtimestamp(latest_ts, tz=timezone.utc).isoformat() if latest_ts else None
        except Exception:  # noqa: BLE001
            generated_at = None
        assets = [
            AssetItem(
                filename=r.get("filename", ""),
                relative_path=r.get("relative_path", ""),
                full_path=r.get("full_path", "") or "",
                last_modified=r.get("last_modified", "") or "",
                summary=r.get("summary", "") or "",
                tags=r.get("tags") or [],
            )
            for r in db_rows
        ]
        return AssetIndexResponse(
            generated_at=generated_at,
            total_files=len(assets),
            assets=assets,
            source_dir=cfg.get("scan_dir", ""),
            bridge_dir=str(get_fos_bridge_data_dir().resolve()),
        )
    # 回退：SQLite 为空时读 FSS 桥接文件
    try:
        data = _load_safe()
    except Exception:  # noqa: BLE001
        data = _EMPTY_RESPONSE
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
    sub = q.strip().casefold()

    def _matches(filename: str, summary: str, tags: list) -> bool:
        if sub in (filename or "").casefold():
            return True
        if sub in (summary or "").casefold():
            return True
        return any(sub in (t or "").casefold() for t in tags)

    # 优先从 SQLite 搜索
    db_rows = db_assets_list(limit=2000)
    if db_rows:
        filtered = [
            r for r in db_rows
            if _matches(r.get("filename", ""), r.get("summary", ""), r.get("tags") or [])
        ]
        cfg = get_scan_config()
        assets = [AssetItem(
            filename=r.get("filename", ""), relative_path=r.get("relative_path", ""),
            full_path=r.get("full_path", "") or "", last_modified=r.get("last_modified", "") or "",
            summary=r.get("summary", "") or "", tags=r.get("tags") or [],
        ) for r in filtered]
        return AssetIndexResponse(
            generated_at=None, total_files=len(assets), assets=assets,
            source_dir=cfg.get("scan_dir", ""),
            bridge_dir=str(get_fos_bridge_data_dir().resolve()),
        )

    # 回退：SQLite 为空时搜索 FSS 桥接文件
    try:
        data = _load_safe()
    except Exception:  # noqa: BLE001
        data = _EMPTY_RESPONSE
    all_raw = data.get("assets", [])
    filtered_raw = [
        a for a in all_raw
        if _matches(a.get("filename", ""), a.get("summary", ""), a.get("tags") or [])
    ]
    assets = [AssetItem(**a) for a in filtered_raw]
    return AssetIndexResponse(
        generated_at=data.get("generated_at"),
        total_files=len(assets),
        assets=assets,
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
# 文件状态管理
# ---------------------------------------------------------------------------

_VALID_STATUSES = frozenset({"draft", "approved", "sent", "archived"})


class AssetStatusIn(BaseModel):
    relative_paths: list[str]
    status: str  # "draft" | "approved" | "sent" | "archived"


@router.put("/api/v1/assets/status", tags=["assets"])
def put_asset_status_route(body: AssetStatusIn) -> dict[str, Any]:
    """批量更新文件状态。"""
    if body.status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail={"code": "E_INVALID_STATUS", "message": f"状态必须是 {sorted(_VALID_STATUSES)} 之一"},
        )
    if not body.relative_paths:
        raise HTTPException(
            status_code=422,
            detail={"code": "E_EMPTY_PATHS", "message": "至少提供一个文件路径"},
        )
    updated = db_asset_status_update(body.relative_paths, body.status)
    return {"updated": updated, "status": body.status}


# ---------------------------------------------------------------------------
# 机构档案
# ---------------------------------------------------------------------------


@router.get("/api/v1/institutions", tags=["assets"])
def get_institutions_route() -> dict[str, Any]:
    """返回所有有已确认 bundle 的机构列表。"""
    institutions = db_institutions_list()
    return {"institutions": institutions, "total": len(institutions)}


@router.get("/api/v1/institutions/{institution_name}", tags=["assets"])
def get_institution_archive_route(institution_name: str) -> dict[str, Any]:
    """返回指定机构的档案（已发文件、打包历史）。"""
    return db_institution_archive_get(institution_name)


# ---------------------------------------------------------------------------
# 尽调响应台 MatchMaker V5.0
# ---------------------------------------------------------------------------


class BundleIn(BaseModel):
    institution: str = ""
    files: list[dict]  # [{"filename": ..., "full_path": ..., "relative_path": ...}]


@router.post("/api/v1/assets/bundle", tags=["assets"])
def post_bundle_route(body: BundleIn) -> dict[str, Any]:
    """直接打包选中文件为已确认的尽调包（跳过 BM25 匹配）。"""
    if not body.files:
        raise HTTPException(
            status_code=422,
            detail={"code": "E_EMPTY_FILES", "message": "请至少选择一个文件"},
        )
    session_id = str(uuid.uuid4())
    req_text = f"直接打包 {len(body.files)} 个文件"
    req_dicts = [
        {"description": f.get("filename", ""), "scene_type": "", "time_range": ""}
        for f in body.files
    ]
    db_match_session_create(
        session_id=session_id,
        institution=body.institution,
        req_text=req_text,
        requirements=req_dicts,
        results=[],
    )
    db_match_session_update(
        session_id=session_id,
        status="confirmed",
        confirmed_files=body.files,
    )
    # 自动将打包文件标记为 "sent"
    paths = [f.get("relative_path") or f.get("filename", "") for f in body.files if f.get("relative_path") or f.get("filename")]
    if paths:
        try:
            db_asset_status_update(paths, "sent")
        except Exception:  # noqa: BLE001
            pass  # 状态更新失败不应阻断打包流程
    return {
        "session_id": session_id,
        "status": "confirmed",
        "file_count": len(body.files),
        "institution": body.institution,
    }


class MatchSessionIn(BaseModel):
    institution: str = ""
    req_text: str
    use_llm: bool = False
    top_n: int = 3


class ConfirmIn(BaseModel):
    confirmed_files: list[dict]  # [{"filename": ..., "full_path": ...}, ...]


@router.post("/api/v1/assets/match", tags=["assets"])
def post_match_route(body: MatchSessionIn) -> dict[str, Any]:
    """解析尽调需求文本 → MatcherSkill 匹配（含机构历史偏好加权）→ 持久化会话。

    匹配流程：
      1. 解析需求文本（LLM 或启发式）
      2. 从 match_outcomes 表加载机构历史偏好画像（无历史时跳过）
      3. BM25MatcherSkill 执行匹配 + 历史偏好加权
      4. 持久化 session，返回结果
    """
    if not body.req_text.strip():
        raise HTTPException(status_code=422, detail={"code": "E_EMPTY_REQ", "message": "需求文本不能为空"})

    requirements = parse_requirements_from_text(body.req_text, use_llm=body.use_llm)
    if not requirements:
        raise HTTPException(status_code=422, detail={"code": "E_NO_REQ", "message": "未能解析出任何需求条目"})

    assets = db_assets_list(limit=2000)

    # 注入机构历史偏好画像（有历史数据时加权，无历史时退化为纯 BM25）
    institution_profile: dict | None = None
    if body.institution:
        try:
            profile = db_institution_match_profile(body.institution)
            if profile.get("total_sessions", 0) > 0:
                institution_profile = profile
                logger.info(
                    "机构 %s 历史画像注入：%d 次匹配，%d 个偏好文件",
                    body.institution,
                    profile["total_sessions"],
                    len(profile.get("preferred_paths", [])),
                )
        except Exception:  # noqa: BLE001
            pass  # 画像加载失败不阻断匹配

    matcher = get_default_matcher()
    results = matcher.match(
        requirements,
        assets,
        institution=body.institution,
        institution_profile=institution_profile,
        top_n=body.top_n,
    )

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
        "profile_injected": institution_profile is not None,
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
    """提交人工确认的文件列表，将会话标记为 confirmed，并写入 match_outcomes 记忆。

    每次 confirm 都是飞轮的一圈：
      人工选择 → match_outcomes 记录 → 下次匹配时偏好加权 → 结果更准
    """
    session = db_match_session_get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail={"code": "E_SESSION_NOT_FOUND", "message": "会话不存在"})
    db_match_session_update(
        session_id,
        status="confirmed",
        confirmed_files=body.confirmed_files,
    )

    # 写入匹配结果记忆（学习飞轮）
    try:
        institution = session.get("institution", "")
        # 从 session results 中提取所有候选文件路径
        candidate_paths: list[str] = []
        candidate_names: list[str] = []
        for result in (session.get("results") or []):
            for c in (result.get("candidates") or []):
                path = (c.get("asset") or {}).get("relative_path", "")
                name = (c.get("asset") or {}).get("filename", "")
                if path and path not in candidate_paths:
                    candidate_paths.append(path)
                    candidate_names.append(name)
        # 被选中的文件
        selected_paths = [f.get("relative_path", "") for f in body.confirmed_files if f.get("relative_path")]
        selected_names = [f.get("filename", "") for f in body.confirmed_files]
        db_match_outcome_batch_save(
            session_id=session_id,
            institution=institution,
            selected_paths=selected_paths,
            candidate_paths=candidate_paths,
            selected_names=selected_names,
            candidate_names=candidate_names,
        )
    except Exception:  # noqa: BLE001
        logger.warning("match_outcomes 写入失败，不阻断确认流程", exc_info=True)

    return {"session_id": session_id, "status": "confirmed", "confirmed_count": len(body.confirmed_files)}
