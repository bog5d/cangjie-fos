"""Phase 6：机构 Pipeline API。"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from cangjie_fos.schemas.institution import InstitutionProfile, InstitutionProfileCreate, InstitutionProfileUpdate, PipelineCountsResponse
from cangjie_fos.services.institution_store import (
    count_by_stage,
    create_institution,
    delete_institution,
    get_milestone_stats,
    list_institutions,
    sync_institutions_from_pitch_jobs,
    update_institution,
)
from cangjie_fos.services.pipeline_funnel import build_funnel_from_institutions

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])


def _push_institution_bg(institution_id: str) -> None:
    try:
        from cangjie_fos.services.github_sync import push_institution  # noqa: PLC0415
        push_institution(institution_id)
    except Exception:  # noqa: BLE001
        pass


@router.get("/institutions", response_model=list[InstitutionProfile])
def get_institutions(tenant_id: str = Query(..., min_length=1)) -> list[InstitutionProfile]:
    return list_institutions(tenant_id=tenant_id)


@router.post("/institutions", response_model=InstitutionProfile)
def post_institution(body: InstitutionProfileCreate) -> InstitutionProfile:
    prof = create_institution(body)
    return prof


@router.patch("/institutions/{institution_id}", response_model=InstitutionProfile)
def patch_institution(
    institution_id: str,
    body: InstitutionProfileUpdate,
    tenant_id: str = Query(..., min_length=1),
    background_tasks: BackgroundTasks = BackgroundTasks(),
) -> InstitutionProfile:
    """部分更新机构档案字段，更新后异步推送到 GitHub。"""
    updated = update_institution(
        tenant_id=tenant_id,
        institution_id=institution_id,
        name=body.name,
        stage=body.stage.value if body.stage else None,
        thermal=body.thermal.value if body.thermal else None,
        preferences=body.preferences,
        concerns=body.concerns,
        ai_summary=body.ai_summary,
        contact_name=body.contact_name,
        contact_title=body.contact_title,
        valuation=body.valuation,
        deal_size=body.deal_size,
        probability=body.probability,
        legal_status=body.legal_status,
        nda_signed=body.nda_signed,
        offline_meeting_count=body.offline_meeting_count,
        project_approved=body.project_approved,
        committee_approved=body.committee_approved,
        onsite_dd_done=body.onsite_dd_done,
        external_dd_done=body.external_dd_done,
        agreement_signed=body.agreement_signed,
        deal_closed=body.deal_closed,
        referral_source=body.referral_source,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="not_found")
    background_tasks.add_task(_push_institution_bg, updated.institution_id)
    return updated


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


@router.get("/milestone-stats")
def milestone_stats(tenant_id: str = Query(..., min_length=1)) -> dict:
    """返回里程碑计数 + 引荐方排行，供征途成就墙使用。"""
    return get_milestone_stats(tenant_id=tenant_id)


@router.get("/funnel-debug")
def pipeline_funnel_debug(tenant_id: str = Query(..., min_length=1)) -> dict:
    """供联调：返回与 Dashboard 一致的漏斗 JSON。"""
    return build_funnel_from_institutions(tenant_id=tenant_id).model_dump()


@router.post("/sync-institutions")
def trigger_institution_sync() -> dict:
    """
    手动触发 institutions 补全（从 pitch_jobs 回溯）。
    等价于重启时自动执行的逻辑，可随时调用，幂等。
    """
    result = sync_institutions_from_pitch_jobs()
    return {"ok": True, **result}
