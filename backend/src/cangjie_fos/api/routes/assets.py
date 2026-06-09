"""资产台账 API — 读取 FSS 写入的 asset_index.json 和 FOS 内建扫描功能。"""
from __future__ import annotations

import logging
import uuid
from typing import Any, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from cangjie_fos.core.paths import get_fos_bridge_data_dir
from cangjie_fos.services.asset_index_io import load_asset_index_dict
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
    db_asset_wiki_summary,
    db_institution_archive_get,
    db_institution_briefing,
    db_institution_match_profile,
    db_institutions_list,
    db_match_outcome_batch_save,
    db_match_session_create,
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


@router.get("/api/v1/institutions/{institution_name}/profile", tags=["assets"])
def get_institution_profile_route(institution_name: str) -> dict[str, Any]:
    """返回指定机构的匹配偏好画像（用于诊断学习飞轮效果）。

    响应字段：
      - institution: 机构名称
      - total_sessions: 历史匹配次数
      - total_selected: 累计选中文件数
      - avg_selected_per_session: 平均每次选中数
      - preferred_paths: 偏好文件列表（按选中频率降序）
      - preferred_tags: 偏好标签聚合（从偏好文件 join assets 表）
      - last_contact: 最近一次匹配的时间戳
    """
    return db_institution_match_profile(institution_name)


@router.get("/api/v1/institutions/{institution_name}/briefing", tags=["assets"])
def get_institution_briefing_route(institution_name: str) -> dict[str, Any]:
    """返回机构智慧简报：历史画像摘要 + 缺口检测。

    比 /profile 多返回 gap_hints（历史上要过但无法满足的材料清单）。
    设计用于匹配前展示给用户，帮助提前了解该机构的已知缺口。
    """
    return db_institution_briefing(institution_name)


@router.get("/api/v1/assets/wiki/{relative_path:path}", tags=["assets"])
def get_asset_wiki_route(relative_path: str) -> dict[str, Any]:
    """返回指定资产的 wiki 摘要：选用历史、关联机构、选中率。

    `relative_path` 使用路径参数（支持含 `/` 的多级路径）。
    数据来源：match_outcomes 表聚合，零延迟。
    """
    return db_asset_wiki_summary(relative_path)


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

    # 写入匹配结果记忆（学习飞轮）—— bundle 直接打包等同于"全部选中"
    try:
        selected_paths = [f.get("relative_path", "") for f in body.files if f.get("relative_path")]
        selected_names = [f.get("filename", "") for f in body.files]
        if selected_paths:
            db_match_outcome_batch_save(
                session_id=session_id,
                institution=body.institution,
                selected_paths=selected_paths,
                candidate_paths=selected_paths,   # bundle 中全选，候选即选中
                selected_names=selected_names,
                candidate_names=selected_names,
            )
    except Exception:  # noqa: BLE001
        logger.warning("bundle match_outcomes 写入失败，不阻断打包流程", exc_info=True)

    return {
        "session_id": session_id,
        "status": "confirmed",
        "file_count": len(body.files),
        "institution": body.institution,
    }
