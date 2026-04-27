"""素材健康度 & 贡献度 API — Phase 2（FSS JSON → FOS SQLite）。"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Query
from pydantic import BaseModel

from cangjie_fos.services.asset_index_io import load_asset_index_dict
from cangjie_fos.services.pitch_job_db import (
    db_contribution_scores_list,
    db_material_contribution_upsert,
    db_material_contributions_list,
    db_material_match_insert,
    db_material_matches_list,
)

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["materials"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class AssetHealthItem(BaseModel):
    asset_filename: str
    relative_path: str
    usage_count: int
    contribution_score: float
    tags: list[str]
    last_used_at: float | None


class MaterialsHealthResponse(BaseModel):
    total: int
    assets: list[AssetHealthItem]


class MaterialMatchRequest(BaseModel):
    institution_id: str
    keywords: list[str] = []
    limit: int = 10


class MatchedAsset(BaseModel):
    asset_filename: str
    relative_path: str
    score: float
    tags: list[str]
    summary: str


class MaterialMatchResponse(BaseModel):
    institution_id: str
    matches: list[MatchedAsset]
    total: int


class ContributionScore(BaseModel):
    contributor: str
    score: float
    job_count: int


class ContributionsResponse(BaseModel):
    total: int
    scores: list[ContributionScore]


# ---------------------------------------------------------------------------
# 素材评分辅助
# ---------------------------------------------------------------------------


def _score_asset(asset: dict, keywords: list[str]) -> float:
    """Simple scoring: tag/keyword overlap + summary keyword hit."""
    score = 0.0
    tags = [t.casefold() for t in (asset.get("tags") or [])]
    summary = (asset.get("summary") or "").casefold()
    for kw in keywords:
        kw_lower = kw.casefold()
        if kw_lower in tags:
            score += 2.0
        if kw_lower in summary:
            score += 1.0
        if kw_lower in (asset.get("filename") or "").casefold():
            score += 1.5
    # base score so all assets get included even with no keywords
    score += 0.1
    return round(score, 3)


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------


@router.get("/api/materials/health", response_model=MaterialsHealthResponse)
def materials_health() -> MaterialsHealthResponse:
    """返回所有素材的健康度（使用次数 / 贡献分）。"""
    rows = db_material_contributions_list()
    logger.info("materials_health_fetched", count=len(rows))
    assets = [
        AssetHealthItem(
            asset_filename=r["asset_filename"],
            relative_path=r["relative_path"],
            usage_count=int(r["usage_count"]),
            contribution_score=float(r["contribution_score"]),
            tags=r.get("tags") or [],
            last_used_at=r.get("last_used_at"),
        )
        for r in rows
    ]
    return MaterialsHealthResponse(total=len(assets), assets=assets)


@router.post("/api/materials/match", response_model=MaterialMatchResponse)
def materials_match(body: MaterialMatchRequest) -> MaterialMatchResponse:
    """为机构生成素材清单并记录匹配历史。"""
    try:
        index = load_asset_index_dict()
        raw_assets = index.get("assets", [])
    except Exception:  # noqa: BLE001
        logger.warning("asset_index_unavailable", institution_id=body.institution_id)
        return MaterialMatchResponse(institution_id=body.institution_id, matches=[], total=0)

    scored = sorted(
        [(a, _score_asset(a, body.keywords)) for a in raw_assets],
        key=lambda x: x[1],
        reverse=True,
    )[: max(1, body.limit)]

    matches: list[MatchedAsset] = []
    for asset, score in scored:
        db_material_match_insert(
            body.institution_id,
            asset.get("filename", ""),
            asset.get("relative_path", ""),
            score=score,
        )
        db_material_contribution_upsert(
            asset.get("filename", ""),
            asset.get("relative_path", ""),
            tags=asset.get("tags"),
            usage_count_delta=1,
        )
        matches.append(
            MatchedAsset(
                asset_filename=asset.get("filename", ""),
                relative_path=asset.get("relative_path", ""),
                score=score,
                tags=asset.get("tags") or [],
                summary=asset.get("summary") or "",
            )
        )

    logger.info(
        "materials_matched",
        institution_id=body.institution_id,
        matched=len(matches),
        keywords=body.keywords,
    )
    return MaterialMatchResponse(
        institution_id=body.institution_id, matches=matches, total=len(matches)
    )


@router.get("/api/contributions", response_model=ContributionsResponse)
def get_contributions(limit: int = Query(50, ge=1, le=200)) -> ContributionsResponse:
    """返回贡献度排行（按 score DESC）。"""
    rows = db_contribution_scores_list(limit=limit)
    scores = [
        ContributionScore(
            contributor=r["contributor"],
            score=float(r["score"]),
            job_count=int(r["job_count"]),
        )
        for r in rows
    ]
    return ContributionsResponse(total=len(scores), scores=scores)
