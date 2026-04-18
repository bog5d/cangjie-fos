"""大盘状态聚合：漏斗由 Pipeline（SQLite）聚合 + 真实资产健康度（Phase 4 SPEC A2）。"""
from __future__ import annotations

from cangjie_fos.schemas.dashboard import DashboardStatusResponse
from cangjie_fos.services.dashboard_real import compute_health_percentages
from cangjie_fos.services.pipeline_funnel import build_funnel_from_institutions


def build_dashboard_status(*, tenant_id: str) -> DashboardStatusResponse:
    funnel = build_funnel_from_institutions(tenant_id=tenant_id)
    docs_h, room_h = compute_health_percentages(tenant_id=tenant_id)
    return DashboardStatusResponse(
        tenant_id=tenant_id,
        funnel=funnel,
        docs_health_pct=docs_h,
        data_room_completeness_pct=room_h,
        headline=funnel.headline,
        exp_hint="漏斗由机构 Pipeline（SQLite）聚合；资料健康度与数据室完成度来自 asset_index / 资料室目录。",
    )
