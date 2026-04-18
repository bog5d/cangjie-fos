import axios from "axios";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { summaryForJobRow } from "../lib/pitchJobErrorDisplay";

export type PitchJobSummaryRow = {
  job_id: string;
  status: string;
  tenant_id: string;
  created_at: number;
  has_report?: boolean;
  error_summary?: string | null;
  error_detail?: string | null;
  error_code?: string | null;
  /** 兼容旧 API；勿直接用于首屏展示 */
  error?: string | null;
};

export type TaskRailProps = {
  tenantId: string;
  onJobCompleted?: (jobId: string) => void;
  onOpenReport?: (jobId: string) => void;
};

const STATUS_LABEL: Record<string, string> = {
  pending: "排队",
  transcribing: "转写",
  evaluating: "评估",
  completed: "完成",
  failed: "失败",
};

function shortId(id: string) {
  return id.length > 10 ? `${id.slice(0, 6)}…${id.slice(-4)}` : id;
}

function TaskFailSummaryChip({
  jobId,
  row,
}: {
  jobId: string;
  row: PitchJobSummaryRow;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const summary = summaryForJobRow(row);
  const detail = (row.error_detail ?? "").trim();
  const code = (row.error_code ?? "").trim();
  const chip = summary.length > 36 ? `${summary.slice(0, 34)}…` : summary;

  useEffect(() => {
    if (!open) return;
    const onDoc = (ev: MouseEvent) => {
      if (ref.current && !ref.current.contains(ev.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        className="max-w-full rounded-sm border border-rose-500/50 bg-rose-700 px-2 py-1 text-left text-[9px] font-bold leading-snug text-white shadow-[0_0_0_1px_rgba(0,0,0,0.35)] hover:bg-rose-600"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        title={summary.length > 40 ? `${summary.slice(0, 80)}…` : summary}
      >
        {chip}
      </button>
      {open ? (
        <div
          className="absolute left-0 right-0 top-full z-40 mt-1 max-h-52 overflow-auto rounded-lg border border-white/12 bg-[#04040a]/98 p-2.5 text-[10px] leading-relaxed text-slate-200 shadow-2xl backdrop-blur-md"
          role="dialog"
          aria-label="错误详情"
        >
          <p className="mb-1.5 font-bold text-rose-100">{summary}</p>
          {code ? (
            <p className="mb-2 font-mono text-[9px] text-slate-500">
              code: <span className="text-cyan-200/90">{code}</span>
            </p>
          ) : null}
          {detail ? (
            <pre className="max-h-36 overflow-auto whitespace-pre-wrap break-words font-mono text-[9px] text-slate-400">
              {detail}
            </pre>
          ) : (
            <p className="text-[9px] text-slate-500">无附加技术详情</p>
          )}
          <p className="mt-2 font-mono text-[9px] text-slate-600">job_id {jobId}</p>
          <button
            type="button"
            className="mt-2 w-full rounded border border-white/15 py-1 text-[9px] text-slate-400 hover:border-cyan/30 hover:text-slate-200"
            onClick={() => setOpen(false)}
          >
            关闭
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function TaskRail({ tenantId, onJobCompleted, onOpenReport }: TaskRailProps) {
  const [rows, setRows] = useState<PitchJobSummaryRow[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const prevStatus = useRef<Map<string, string>>(new Map());
  const bootstrapped = useRef(false);

  const onJobCompletedRef = useRef(onJobCompleted);
  onJobCompletedRef.current = onJobCompleted;

  useEffect(() => {
    prevStatus.current = new Map();
    bootstrapped.current = false;
  }, [tenantId]);

  const tick = useCallback(async () => {
    try {
      const { data } = await api.get<PitchJobSummaryRow[]>("/api/pitch/jobs", {
        params: { tenant_id: tenantId, limit: 24 },
      });
      setErr(null);
      const list = Array.isArray(data) ? data : [];
      setRows(list);
        if (!bootstrapped.current) {
          for (const r of list) {
            prevStatus.current.set(r.job_id, r.status);
          }
          bootstrapped.current = true;
          return;
        }
        for (const r of list) {
          const prev = prevStatus.current.get(r.job_id);
          prevStatus.current.set(r.job_id, r.status);
          const trulyDone = r.status === "completed" && r.has_report === true;
          if (trulyDone && prev !== undefined && prev !== "completed") {
            onJobCompletedRef.current?.(r.job_id);
          }
        }
    } catch (e: unknown) {
      let msg = "任务列表拉取失败";
      if (axios.isAxiosError(e)) {
        msg = e.message;
      } else if (e instanceof Error) {
        msg = e.message;
      }
      setErr(msg);
    }
  }, [tenantId]);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      if (cancelled) return;
      await tick();
    };
    void run();
    const id = window.setInterval(() => void tick(), 950);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [tick]);

  if (!tenantId) return null;

  return (
    <div className="border-b border-cyan/20 bg-gradient-to-r from-black/80 via-plasma/10 to-black/80 px-3 py-2">
      <div className="mb-1 flex items-center justify-between gap-2">
        <p className="font-display text-[9px] font-bold uppercase tracking-[0.4em] text-cyan/90">Task Rail</p>
        {err ? <span className="text-[10px] text-rose-400">{err}</span> : null}
      </div>
      <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-thin">
        {rows.length === 0 ? (
          <span className="text-[10px] text-slate-600">暂无上传任务 · 提交向导或「上传录音」后出现轨道</span>
        ) : (
          rows.map((r) => {
            const pulse = r.status === "pending" || r.status === "transcribing" || r.status === "evaluating";
            const failed = r.status === "failed";
            const done = r.status === "completed";
            const canOpenReport = done && r.has_report === true;
            return (
              <div
                key={r.job_id}
                className={`flex min-w-[140px] shrink-0 flex-col gap-1 rounded-lg border px-2 py-1.5 ${
                  failed
                    ? "border-rose-500/40 bg-rose-950/25"
                    : done
                      ? "border-emerald-500/35 bg-emerald-500/10"
                      : "border-cyan/30 bg-cyan/5 shadow-[0_0_12px_rgba(34,211,238,0.12)]"
                } ${pulse && !failed ? "motion-safe:animate-pulse" : ""}`}
              >
                <div className="flex items-center justify-between gap-1">
                  <span className="font-mono text-[10px] text-slate-300">{shortId(r.job_id)}</span>
                  <span
                    className={`text-[9px] font-bold uppercase tracking-wider ${
                      failed ? "text-rose-300" : done ? "text-emerald-300" : "text-cyan-200"
                    }`}
                  >
                    {STATUS_LABEL[r.status] ?? r.status}
                  </span>
                </div>
                {canOpenReport ? (
                  <button
                    type="button"
                    className="rounded border border-emerald-400/40 bg-black/30 px-1.5 py-0.5 text-[10px] font-bold text-emerald-200 hover:bg-emerald-500/20"
                    onClick={() => onOpenReport?.(r.job_id)}
                  >
                    查看报告
                  </button>
                ) : done && !r.has_report ? (
                  <span className="text-[9px] text-slate-500">报告生成中…</span>
                ) : null}
                {failed ? <TaskFailSummaryChip jobId={r.job_id} row={r} /> : null}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
