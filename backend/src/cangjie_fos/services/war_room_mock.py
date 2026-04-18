"""战局漏斗 Mock 数据生成。"""
from __future__ import annotations

from cangjie_fos.schemas.war_room import (
    FunnelStage,
    FunnelStageKey,
    WarRoomFunnelResponse,
)


def build_funnel_mock(*, tenant_id: str) -> WarRoomFunnelResponse:
    return WarRoomFunnelResponse(
        tenant_id=tenant_id,
        round_name="Series A",
        headline="A 轮战局 · 漏斗态势（Mock）",
        stages=[
            FunnelStage(
                key=FunnelStageKey.MATERIALS,
                title="资料室",
                subtitle="BP / 数据包 / 模型",
                progress_pct=100,
                status="done",
            ),
            FunnelStage(
                key=FunnelStageKey.TEASER,
                title="Teaser",
                subtitle="非机密一页流",
                progress_pct=88,
                status="active",
            ),
            FunnelStage(
                key=FunnelStageKey.PARTNER_MEET,
                title="Partner 会",
                subtitle="核心条款对齐",
                progress_pct=52,
                status="active",
            ),
            FunnelStage(
                key=FunnelStageKey.TERM_SHEET,
                title="Term Sheet",
                subtitle="估值与治理",
                progress_pct=24,
                status="pending",
            ),
            FunnelStage(
                key=FunnelStageKey.CLOSING,
                title="交割",
                subtitle="Close checklist",
                progress_pct=8,
                status="pending",
            ),
        ],
        momentum_score=72,
    )
