import { useCallback, useState } from "react";
import { motion } from "framer-motion";
import { api } from "../api/client";
import type { DashboardStatus } from "../types/dashboard";
import { ReflectionSettleModal } from "./ReflectionSettleModal";

interface Props {
  dashboard: DashboardStatus | null;
  loading: boolean;
  error: string | null;
  tenantId: string;
  onRequestRefresh?: () => void;
}

export function WarRoomMap({ dashboard, loading, error, tenantId, onRequestRefresh }: Props) {
  const [settleOpen, setSettleOpen] = useState(false);
  const [settleBusy, setSettleBusy] = useState(false);
  const [settleGuideline, setSettleGuideline] = useState("");
  const [settleProcessed, setSettleProcessed] = useState(0);

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
    } catch (e) {
      setSettleGuideline(e instanceof Error ? e.message : "结算请求失败");
    } finally {
      setSettleBusy(false);
    }
  }, [tenantId, onRequestRefresh]);
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

  return (
    <div className="relative flex h-full flex-col gap-6 rounded-3xl border border-white/10 bg-gradient-to-b from-white/[0.07] to-white/[0.02] p-6 shadow-2xl backdrop-blur-xl">
      <ReflectionSettleModal
        open={settleOpen}
        busy={settleBusy}
        guideline={settleGuideline}
        processed={settleProcessed}
        onClose={() => setSettleOpen(false)}
      />
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="font-display text-xs uppercase tracking-[0.35em] text-cyan/90">
            War Room Map · API
          </p>
          <h1 className="mt-2 font-display text-2xl font-bold text-white md:text-3xl">
            {dashboard.headline || data.headline}
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            {data.round_name} · tenant{" "}
            <span className="rounded bg-white/10 px-2 py-0.5 font-mono text-xs text-cyan">
              {data.tenant_id}
            </span>
          </p>
        </div>
        <button
          type="button"
          onClick={() => void runReflectionSettle()}
          className="shrink-0 rounded-2xl border border-plasma/40 bg-gradient-to-r from-plasma/30 to-cyan/25 px-4 py-2 font-display text-[10px] font-bold uppercase tracking-[0.2em] text-plasma-100 shadow-lg shadow-plasma/15 transition hover:brightness-110"
        >
          结算进化
        </button>
      </header>

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

      <div className="flex flex-1 flex-col gap-3">
        {data.stages.map((s, idx) => (
          <div
            key={s.key}
            className="group relative overflow-hidden rounded-2xl border border-white/10 bg-black/30 p-4 transition hover:border-cyan/40"
            style={{ animationDelay: `${idx * 60}ms` }}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-display text-lg text-white">{s.title}</span>
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
