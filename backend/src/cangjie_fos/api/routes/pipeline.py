"""Phase 6：机构 Pipeline API。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from cangjie_fos.adapters.institution_coach_sync import project_institution_to_coach_registry
from cangjie_fos.schemas.institution import InstitutionProfile, InstitutionProfileCreate, PipelineCountsResponse
from cangjie_fos.services.institution_store import (
    count_by_stage,
    create_institution,
    delete_institution,
    list_institutions,
)
from cangjie_fos.services.pipeline_funnel import build_funnel_from_institutions

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])


@router.get("/institutions", response_model=list[InstitutionProfile])
def get_institutions(tenant_id: str = Query(..., min_length=1)) -> list[InstitutionProfile]:
    return list_institutions(tenant_id=tenant_id)


@router.post("/institutions", response_model=InstitutionProfile)
def post_institution(body: InstitutionProfileCreate) -> InstitutionProfile:
    prof = create_institution(body)
    project_institution_to_coach_registry(name=prof.name, tenant_id=prof.tenant_id)
    return prof


@router.delete("/institutions/{institution_id}")
def remove_institution(
    institution_id: str,
    tenant_id: str = Query(..., min_length=1),
) -> dict[str, bool]:
    ok = delete_institution(tenant_id=tenant_id, institution_id=institution_id)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return {"ok": True}


@router.get("/status", response_model=PipelineCountsResponse)
def pipeline_status(tenant_id: str = Query(..., min_length=1)) -> PipelineCountsResponse:
    c = count_by_stage(tenant_id=tenant_id)
    total = sum(c.values())
    return PipelineCountsResponse(tenant_id=tenant_id, counts=c, total=total)


@router.get("/funnel-debug")
def pipeline_funnel_debug(tenant_id: str = Query(..., min_length=1)) -> dict:
    """供联调：返回与 Dashboard 一致的漏斗 JSON。"""
    return build_funnel_from_institutions(tenant_id=tenant_id).model_dump()
