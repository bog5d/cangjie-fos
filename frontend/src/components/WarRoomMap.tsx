import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import { api } from "../api/client";
import type { DashboardStatus } from "../types/dashboard";
import type { MilestoneStats } from "../types/institution";
import { ReflectionSettleModal } from "./ReflectionSettleModal";

interface Props {
  dashboard: DashboardStatus | null;
  loading: boolean;
  error: string | null;
  tenantId: string;
  onRequestRefresh?: () => void;
  milestoneRefreshKey?: number;
}

interface PipelineCount {
  stage: string;
  label: string;
  count: number;
}

interface RecentRoadshow {
  institution: string;
  status: string;
  date: string;
  exp_delta: number;
  interviewee: string;
}

interface PendingFollowup {
  id: string;
  actor: string;
  action: string;
  priority: string;
  institution: string;
}

interface LiveIntel {
  pipeline_counts: PipelineCount[];
  recent_roadshows: RecentRoadshow[];
  pending_followups: PendingFollowup[];
}

const STAGE_TOOLTIP: Record<string, string> = {
  teaser: "Teaser：初步接触阶段，向投资机构发送初步材料并完成首次沟通",
  dd: "DD（Due Diligence）：尽职调查，投资机构深度核查阶段，通常为签约前最后一步",
  term_sheet: "Term Sheet：投资意向书，机构表达投资意向并协商条款",
  closed: "Closed：已签约完成，资金到账",
};

const STATUS_ROADSHOW: Record<string, string> = {
  completed: "✅",
  pending: "⏳",
  processing: "🔄",
  failed: "❌",
};

export function WarRoomMap({ dashboard, loading, error, tenantId, onRequestRefresh, milestoneRefreshKey }: Props) {
  const [settleOpen, setSettleOpen] = useState(false);
  const [settleBusy, setSettleBusy] = useState(false);
  const [settleGuideline, setSettleGuideline] = useState("");
  const [settleProcessed, setSettleProcessed] = useState(0);

  const [liveIntel, setLiveIntel] = useState<LiveIntel | null>(null);
  const [liveLoading, setLiveLoading] = useState(false);
  const [milestoneStats, setMilestoneStats] = useState<MilestoneStats | null>(null);
  const [briefingMode, setBriefingMode] = useState(false);

  const fetchLiveIntel = useCallback(async () => {
    if (!tenantId) return;
    setLiveLoading(true);
    try {
      const [liveRes, msRes] = await Promise.allSettled([
        api.get<LiveIntel>("/api/dashboard/live", { params: { tenant_id: tenantId } }),
        api.get<MilestoneStats>("/api/v1/pipeline/milestone-stats", { params: { tenant_id: tenantId } }),
      ]);
      if (liveRes.status === "fulfilled") setLiveIntel(liveRes.value.data);
      if (msRes.status === "fulfilled") setMilestoneStats(msRes.value.data);
    } catch {
      // 静默失败，不破坏主体显示
    } finally {
      setLiveLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    void fetchLiveIntel();
  }, [fetchLiveIntel, milestoneRefreshKey]);

  // 当父组件刷新时，同步刷新 live intel
  const runReflectionSettle = useCallback(async () => {
    setSettleOpen(true);
    setSettleBusy(true);
    setSettleGuideline("");
    setSettleProcessed(0);
    try {
      const { data } = await api.post<{
        processed?: number;
        guideline?: string;
        note?: string;
      }>("/api/v1/reflection/nightly-settle", { tenant_id: tenantId });
      setSettleGuideline(String(data.guideline ?? ""));
      setSettleProcessed(typeof data.processed === "number" ? data.processed : 0);
      onRequestRefresh?.();
      void fetchLiveIntel();
    } catch (e) {
      setSettleGuideline(e instanceof Error ? e.message : "结算请求失败");
    } finally {
      setSettleBusy(false);
    }
  }, [tenantId, onRequestRefresh, fetchLiveIntel]);

  if (loading) {
    return (
      <div className="flex h-full min-h-[420px] items-center justify-center rounded-3xl border border-white/10 bg-white/5 p-8 backdrop-blur">
        <div className="h-12 w-12 animate-spin rounded-full border-2 border-cyan/40 border-t-cyan" />
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-3xl border border-red-500/30 bg-red-950/40 p-6 text-red-200">
        {error}
      </div>
    );
  }
  if (!dashboard) return null;

  const data = dashboard.funnel;
  const totalInstitutions = liveIntel
    ? liveIntel.pipeline_counts.reduce((s, c) => s + c.count, 0)
    : null;

  return (
    <div className="relative flex h-full flex-col gap-5 rounded-3xl border border-white/10 bg-gradient-to-b from-white/[0.07] to-white/[0.02] p-6 shadow-2xl backdrop-blur-xl">
      <ReflectionSettleModal
        open={settleOpen}
        busy={settleBusy}
        guideline={settleGuideline}
        processed={settleProcessed}
        onClose={() => setSettleOpen(false)}
      />

      {/* ── Header ── */}
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="font-display text-xs uppercase tracking-[0.35em] text-cyan/90">
            <span title="机构融资漏斗：追踪各投资机构从接触到签约的进展阶段">Pipeline</span>
            {" · "}
            <span title="War Room Map：融资作战全景看板，汇总机构漏斗与资料健康度">War Room</span>
          </p>
          <h1 className="mt-2 font-display text-2xl font-bold text-white md:text-3xl">
            {dashboard.headline || data.headline}
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            {data.round_name} · tenant{" "}
            <span className="rounded bg-white/10 px-2 py-0.5 font-mono text-xs text-cyan">
              {data.tenant_id}
            </span>
            {totalInstitutions !== null && (
              <span className="ml-2 text-slate-500">
                · 共 <span className="text-white">{totalInstitutions}</span> 家机构在库
              </span>
            )}
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            onClick={() => setBriefingMode((v) => !v)}
            className={`rounded-2xl border px-4 py-2 font-display text-[10px] font-bold uppercase tracking-[0.2em] shadow-lg transition hover:brightness-110 ${
              briefingMode
                ? "border-cyan/60 bg-cyan/20 text-cyan"
                : "border-white/20 bg-white/10 text-slate-400"
            }`}
          >
            {briefingMode ? "📊 完整视图" : "📋 简报模式"}
          </button>
          <button
            type="button"
            onClick={() => void runReflectionSettle()}
            className="shrink-0 rounded-2xl border border-plasma/40 bg-gradient-to-r from-plasma/30 to-cyan/25 px-4 py-2 font-display text-[10px] font-bold uppercase tracking-[0.2em] text-plasma-100 shadow-lg shadow-plasma/15 transition hover:brightness-110"
          >
            结算进化
          </button>
        </div>
      </header>

      {/* ── 征途成就墙 ── */}
      {milestoneStats && (
        <section className="rounded-2xl border border-amber-400/20 bg-amber-950/20 p-4">
          <p className="mb-3 text-[10px] font-bold uppercase tracking-widest text-amber-400/70">
            征途成就墙
          </p>
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-9">
            {[
              { label: "路演接触", value: milestoneStats.total_contacted, icon: "🎤", sub: "" },
              { label: "NDA 签署", value: milestoneStats.nda_signed, icon: "📝", sub: "" },
              {
                label: "线下交流",
                value: milestoneStats.offline_meetings,
                icon: "☕",
                sub: milestoneStats.offline_meeting_sum > 0
                  ? `${milestoneStats.offline_meeting_sum}次`
                  : "",
              },
              { label: "立项", value: milestoneStats.project_approved, icon: "✅", sub: "" },
              { label: "内部尽调", value: milestoneStats.onsite_dd_done, icon: "🔍", sub: "" },
              { label: "外部尽调", value: milestoneStats.external_dd_done, icon: "🏢", sub: "" },
              { label: "投决过会", value: milestoneStats.committee_approved, icon: "🏛️", sub: "" },
              { label: "协议签署", value: milestoneStats.agreement_signed, icon: "✍️", sub: "" },
              { label: "交割", value: milestoneStats.deal_closed, icon: "🎯", sub: "" },
            ].map((m) => (
              <div
                key={m.label}
                className="flex flex-col items-center rounded-xl border border-amber-400/10 bg-black/20 py-2 px-1"
              >
                <span className="text-base">{m.icon}</span>
                <span className="mt-1 font-display text-xl font-bold text-amber-200">
                  {m.value}<span className="text-[10px] font-normal text-amber-400/60">家</span>
                </span>
                {m.sub && (
                  <span className="text-[9px] text-amber-400/40">（{m.sub}）</span>
                )}
                <span className="mt-0.5 text-center text-[9px] text-amber-400/60">{m.label}</span>
              </div>
            ))}
          </div>
          {milestoneStats.top_referrals.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              <span className="text-[10px] text-amber-400/50">引荐来源：</span>
              {milestoneStats.top_referrals.map((r) => (
                <span
                  key={r.source}
                  className="rounded-full border border-amber-400/20 bg-amber-950/30 px-2 py-0.5 text-[10px] text-amber-300"
                >
                  {r.source} ×{r.count}
                </span>
              ))}
            </div>
          )}
        </section>
      )}

      {/* ── 资料健康度 ── */}
      {!briefingMode && (
      <section className="grid gap-3 rounded-2xl border border-white/10 bg-black/25 p-4 md:grid-cols-2">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
            资料健康度
          </p>
          <div className="mt-2 flex items-end gap-2">
            <span className="font-display text-3xl font-bold text-ember">
              {dashboard.docs_health_pct}
            </span>
            <span className="pb-1 text-xs text-slate-500">/ 100</span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/10">
            <motion.div
              className="h-full rounded-full bg-ember/80"
              initial={false}
              animate={{
                width: `${dashboard.docs_health_pct}%`,
                boxShadow:
                  dashboard.docs_health_pct >= 80
                    ? "0 0 16px rgba(251, 146, 60, 0.45)"
                    : "0 0 0 rgba(0,0,0,0)",
              }}
              transition={{ type: "spring", stiffness: 90, damping: 18 }}
            />
          </div>
        </div>
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
            数据室完成度
          </p>
          <div className="mt-2 flex items-end gap-2">
            <span className="font-display text-3xl font-bold text-cyan">
              {dashboard.data_room_completeness_pct}
            </span>
            <span className="pb-1 text-xs text-slate-500">/ 100</span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/10">
            <motion.div
              className="h-full rounded-full bg-cyan/80"
              initial={false}
              animate={{
                width: `${dashboard.data_room_completeness_pct}%`,
                boxShadow:
                  dashboard.data_room_completeness_pct >= 75
                    ? "0 0 14px rgba(34, 211, 238, 0.4)"
                    : "0 0 0 rgba(0,0,0,0)",
              }}
              transition={{ type: "spring", stiffness: 88, damping: 17 }}
            />
          </div>
        </div>
        {dashboard.exp_hint ? (
          <p className="md:col-span-2 text-xs text-slate-400">{dashboard.exp_hint}</p>
        ) : null}
      </section>
      )}

      {/* ── Pipeline 漏斗 ── */}
      <div className="flex flex-col gap-3">
        {data.stages.map((s, idx) => (
          <div
            key={s.key}
            className="group relative overflow-hidden rounded-2xl border border-white/10 bg-black/30 p-4 transition hover:border-cyan/40"
            style={{ animationDelay: `${idx * 60}ms` }}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <span
                    className="font-display text-lg text-white"
                    title={STAGE_TOOLTIP[s.key]}
                  >
                    {s.title}
                  </span>
                  <StatusPill status={s.status} />
                </div>
                <p className="mt-1 text-xs text-slate-400">{s.subtitle}</p>
              </div>
              <span className="font-display text-sm text-cyan">{s.progress_pct}%</span>
            </div>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
              <motion.div
                className="h-full rounded-full bg-gradient-to-r from-cyan via-plasma to-ember"
                initial={false}
                animate={{ width: `${s.progress_pct}%` }}
                transition={{ type: "spring", stiffness: 70, damping: 16 }}
              />
            </div>
          </div>
        ))}
      </div>

      {/* ── 实战情报区块（Live Intel）── */}
      {!briefingMode && liveLoading && !liveIntel && (
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <div className="h-3 w-3 animate-spin rounded-full border border-cyan/40 border-t-cyan" />
          加载实战情报…
        </div>
      )}

      {!briefingMode && liveIntel && (
        <div className="flex flex-col gap-4">
          {/* 机构阶段分布 */}
          {liveIntel.pipeline_counts.length > 0 && (
            <section className="rounded-2xl border border-white/10 bg-black/20 p-4">
              <p className="mb-3 text-[10px] font-bold uppercase tracking-widest text-slate-500">
                机构分布
              </p>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {liveIntel.pipeline_counts.map((c) => (
                  <div
                    key={c.stage}
                    className="rounded-xl border border-white/10 bg-white/5 p-3 text-center"
                  >
                    <p className="font-display text-2xl font-bold text-white">{c.count}</p>
                    <p className="mt-1 text-[10px] text-slate-400">{c.label}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* 最近路演 */}
          {liveIntel.recent_roadshows.length > 0 && (
            <section className="rounded-2xl border border-white/10 bg-black/20 p-4">
              <p className="mb-3 text-[10px] font-bold uppercase tracking-widest text-slate-500">
                最近路演
              </p>
              <div className="flex flex-col gap-2">
                {liveIntel.recent_roadshows.map((r, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between rounded-xl border border-white/5 bg-white/5 px-3 py-2"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm">{STATUS_ROADSHOW[r.status] ?? "📋"}</span>
                      <div>
                        <p className="text-sm font-medium text-white">{r.institution}</p>
                        {r.interviewee && (
                          <p className="text-[10px] text-slate-500">{r.interviewee}</p>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-3 text-right">
                      {r.exp_delta !== 0 && (
                        <span
                          className={`text-xs font-bold ${r.exp_delta > 0 ? "text-emerald-400" : "text-red-400"}`}
                        >
                          {r.exp_delta > 0 ? "+" : ""}{r.exp_delta}
                        </span>
                      )}
                      <span className="text-[11px] text-slate-500">{r.date}</span>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* 待办行动项 */}
          {liveIntel.pending_followups.length > 0 && (
            <section className="rounded-2xl border border-white/10 bg-black/20 p-4">
              <p className="mb-3 text-[10px] font-bold uppercase tracking-widest text-slate-500">
                待办行动{" "}
                <span className="ml-1 rounded-full bg-red-500/20 px-2 py-0.5 text-red-300">
                  {liveIntel.pending_followups.length}
                </span>
              </p>
              <div className="flex flex-col gap-2">
                {liveIntel.pending_followups.map((f) => (
                  <div
                    key={f.id}
                    className="flex items-start gap-2 rounded-xl border border-white/5 bg-white/5 px-3 py-2"
                  >
                    <span className="mt-0.5 text-sm">
                      {f.priority === "high" ? "🔴" : "⚪"}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-white">
                        <span className="text-slate-400">{f.actor}：</span>
                        {f.action}
                      </p>
                      {f.institution && (
                        <p className="mt-0.5 text-[10px] text-slate-500">{f.institution}</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {liveIntel.pipeline_counts.length === 0 &&
            liveIntel.recent_roadshows.length === 0 &&
            liveIntel.pending_followups.length === 0 && (
              <p className="text-center text-xs text-slate-600">
                暂无机构数据 · 通过 Pipeline 或 NPC 对话录入后自动更新
              </p>
            )}
        </div>
      )}

      {/* ── 战局势能 ── */}
      <footer className="flex items-center justify-between rounded-2xl border border-cyan/25 bg-cyan/10 px-4 py-3">
        <span className="text-sm text-slate-300">战局势能</span>
        <div className="flex items-center gap-2">
          <span className="font-display text-2xl font-bold text-cyan">
            {data.momentum_score}
          </span>
          <span className="text-xs text-slate-500">/ 100</span>
        </div>
      </footer>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const map: Record<string, string> = {
    done: "bg-emerald-500/20 text-emerald-200 ring-emerald-400/30",
    active: "bg-ember/20 text-amber-100 ring-ember/40 animate-pulseRing",
    pending: "bg-slate-600/30 text-slate-300 ring-white/10",
  };
  const cls = map[status] ?? map.pending;
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ring-1 ${cls}`}
    >
      {status}
    </span>
  );
}
