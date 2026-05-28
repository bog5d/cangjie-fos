"""战局大盘 HTTP 入口（Phase 3 SPEC A3）。"""
from __future__ import annotations

import datetime
from typing import Any

from fastapi import APIRouter, Query

from cangjie_fos.schemas.dashboard import DashboardStatusResponse
from cangjie_fos.services.dashboard_status import build_dashboard_status

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/status", response_model=DashboardStatusResponse)
def get_dashboard_status(tenant_id: str = Query(..., min_length=1)) -> DashboardStatusResponse:
    return build_dashboard_status(tenant_id=tenant_id)


@router.get("/live", summary="融资实战情报：机构分布 + 最近路演 + 待办行动项")
def get_live_intel(tenant_id: str = Query(..., min_length=1)) -> dict[str, Any]:
    """
    聚合三路真实数据，供战情地图实时展示。
    无缓存，每次调用直查 SQLite。
    """
    from cangjie_fos.services.institution_store import count_by_stage
    from cangjie_fos.services.pitch_job_db import db_follow_up_list, db_job_list_for_tenant

    # ── 1. 机构各阶段分布 ──────────────────────────────────────────────
    stage_label = {
        "targeted": "目标筛选",
        "pitched": "已路演",
        "dd": "尽调中",
        "term_sheet": "TS谈判",
    }
    counts_raw = count_by_stage(tenant_id=tenant_id)
    pipeline_counts = [
        {"stage": k, "label": stage_label.get(k, k), "count": v}
        for k, v in counts_raw.items()
        if v > 0
    ]

    # ── 2. 最近路演记录 ────────────────────────────────────────────────
    jobs = db_job_list_for_tenant(tenant_id, limit=5)
    recent_roadshows = []
    for _, job in jobs:
        created = job.get("created_at") or 0
        date_str = datetime.datetime.fromtimestamp(float(created)).strftime("%m-%d") if created else ""
        recent_roadshows.append({
            "institution": job.get("institution_id") or "（待确认）",
            "status": job.get("status") or "unknown",
            "date": date_str,
            "exp_delta": job.get("exp_delta") or 0,
            "interviewee": job.get("interviewee") or "",
        })

    # ── 3. 未完成待办行动项 ────────────────────────────────────────────
    raw_followups = db_follow_up_list(tenant_id, limit=8, include_done=False)
    pending_followups = [
        {
            "id": f.get("id"),
            "actor": f.get("actor") or "我方",
            "action": f.get("action") or "",
            "priority": f.get("priority") or "normal",
            "institution": f.get("institution_id") or "",
        }
        for f in raw_followups
    ]

    return {
        "pipeline_counts": pipeline_counts,
        "recent_roadshows": recent_roadshows,
        "pending_followups": pending_followups,
    }

