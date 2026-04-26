"""资产台账 API — 读取 FSS 写入的 asset_index.json（带校验与路径脱敏）。"""
from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from cangjie_fos.core.paths import get_fos_bridge_data_dir
from cangjie_fos.services.asset_index_io import load_asset_index_dict

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
