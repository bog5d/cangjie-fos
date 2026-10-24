"""机构 Pipeline 漏斗 — 以里程碑字段为唯一数据源，与征途成就墙保持一致。"""
from __future__ import annotations

from cangjie_fos.schemas.war_room import FunnelStage, FunnelStageKey, WarRoomFunnelResponse
from cangjie_fos.services.institution_store import get_milestone_stats


def _pct(n: int, total: int) -> int:
    if total <= 0:
        return 0
    return min(100, int(100 * n / total))


def build_funnel_from_institutions(*, tenant_id: str) -> WarRoomFunnelResponse:
    ms = get_milestone_stats(tenant_id=tenant_id)
    total = ms["total_contacted"]
    nda = ms["nda_signed"]
    proj = ms["project_approved"]
    comm = ms["committee_approved"]
    closed = ms["deal_closed"]
    agr = ms["agreement_signed"]
    i_dd = ms["onsite_dd_done"]
    e_dd = ms["external_dd_done"]
    max_dd = max(i_dd, e_dd)

    headline = (
        f"Pipeline 实盘 · {total} 家机构在列"
        if total
        else "Pipeline 实盘 · 尚无机构画像（上传路演后将自动抽取）"
    )

    stages = [
        FunnelStage(
            key=FunnelStageKey.MATERIALS,
            title="路演接触",
            subtitle=f"共 {total} 家机构",
            progress_pct=100 if total else 0,
            status="active" if total else "pending",
        ),
        FunnelStage(
            key=FunnelStageKey.TEASER,
            title="NDA 签署",
            subtitle=f"{nda} 家已签 NDA",
            progress_pct=_pct(nda, total),
            status="active" if nda else "pending",
        ),
        FunnelStage(
            key=FunnelStageKey.PARTNER_MEET,
            title="立项 / 尽调",
            subtitle=f"{proj} 家立项  ·  内部尽调 {i_dd} / 外部尽调 {e_dd}",
            progress_pct=_pct(max(proj, max_dd), total),
            status="active" if proj or max_dd else "pending",
        ),
        FunnelStage(
            key=FunnelStageKey.TERM_SHEET,
            title="投决过会",
            subtitle=f"{comm} 家通过投决会",
            progress_pct=_pct(comm, total),
            status="active" if comm else "pending",
        ),
        FunnelStage(
            key=FunnelStageKey.CLOSING,
            title="协议 / 交割",
            subtitle=f"{agr} 家签协议  ·  {closed} 家交割完成",
            progress_pct=_pct(closed, total) if closed else _pct(agr, total),
            status="done" if closed else ("active" if agr else "pending"),
        ),
    ]

    momentum = min(
        100,
        int(
            (stages[1].progress_pct + stages[2].progress_pct +
             stages[3].progress_pct + stages[4].progress_pct) / 4
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
