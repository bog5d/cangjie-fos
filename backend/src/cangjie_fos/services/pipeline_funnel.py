"""Phase 6：由 Institution 聚合生成 War Room 漏斗。"""
from __future__ import annotations

from cangjie_fos.schemas.institution import PipelineStage
from cangjie_fos.schemas.war_room import FunnelStage, FunnelStageKey, WarRoomFunnelResponse
from cangjie_fos.services.institution_store import count_by_stage


def _stage_progress(count: int, cap: int = 6) -> int:
    if count <= 0:
        return 0
    return min(100, int(100 * count / cap))


def build_funnel_from_institutions(*, tenant_id: str) -> WarRoomFunnelResponse:
    counts = count_by_stage(tenant_id=tenant_id)
    total = sum(counts.values())
    c_t = counts[PipelineStage.TARGETED.value]
    c_p = counts[PipelineStage.PITCHED.value]
    c_d = counts[PipelineStage.DD.value]
    c_ts = counts[PipelineStage.TERM_SHEET.value]

    headline = (
        f"Pipeline 实盘 · {total} 家机构在列"
        if total
        else "Pipeline 实盘 · 尚无机构画像（上传路演后将自动抽取）"
    )

    stages = [
        FunnelStage(
            key=FunnelStageKey.MATERIALS,
            title="触达 / 资料",
            subtitle=f"Targeted：{c_t} 家",
            progress_pct=_stage_progress(c_t),
            status="active" if c_t else "pending",
        ),
        FunnelStage(
            key=FunnelStageKey.TEASER,
            title="路演 / Teaser",
            subtitle=f"Pitched：{c_p} 家",
            progress_pct=_stage_progress(c_p),
            status="active" if c_p else "pending",
        ),
        FunnelStage(
            key=FunnelStageKey.PARTNER_MEET,
            title="尽调 DD",
            subtitle=f"DD：{c_d} 家",
            progress_pct=_stage_progress(c_d),
            status="active" if c_d else "pending",
        ),
        FunnelStage(
            key=FunnelStageKey.TERM_SHEET,
            title="Term Sheet",
            subtitle=f"TS：{c_ts} 家",
            progress_pct=_stage_progress(c_ts),
            status="active" if c_ts else "pending",
        ),
        FunnelStage(
            key=FunnelStageKey.CLOSING,
            title="交割准备",
            subtitle="Closing checklist",
            progress_pct=_stage_progress(1 if c_ts else 0, cap=2),
            status="done" if c_ts else "pending",
        ),
    ]

    momentum = min(
        100,
        int(
            (stages[0].progress_pct + stages[1].progress_pct + stages[2].progress_pct + stages[3].progress_pct) / 4
            + (5 if total else 0)
        ),
    )

    return WarRoomFunnelResponse(
        tenant_id=tenant_id,
        round_name="Series A",
        headline=headline,
        stages=stages,
        momentum_score=momentum,
    )
