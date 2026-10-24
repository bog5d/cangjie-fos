import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";

export interface JobRow {
  job_id: string;
  status: string;
  created_at: number;
  has_report: boolean;
  error_summary?: string | null;
  warnings?: Record<string, string> | null;
  participants_confirmed: boolean;
  interviewee?: string | null;
  category?: string | null;
  institution_id?: string | null;
  has_words_json?: boolean;
}

const STATUS_LABEL: Record<string, string> = {
  pending: "排队中",
  transcribing: "转写中",
  evaluating: "评估中",
  completed: "已完成",
  failed: "失败",
};

const STATUS_COLOR: Record<string, string> = {
  completed: "text-emerald-400",
  failed: "text-rose-400",
  pending: "text-slate-400",
  transcribing: "text-cyan-300",
  evaluating: "text-cyan-300",
};

function fmt(ts: number): string {
  return new Date(ts * 1000).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

interface Props {
  tenantId: string;
  /** 父组件传入，当有待确认 job 时调用（触发弹层） */
  onPendingConfirm?: (jobId: string, interviewee: string | null) => void;
}

export function PitchJobHistory({ tenantId, onPendingConfirm }: Props) {
  const [rows, setRows] = useState<JobRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get<JobRow[]>("/api/pitch/jobs", {
        params: { tenant_id: tenantId, limit: 30 },
      });
      setRows(Array.isArray(data) ? data : []);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  return (
    <div className="mt-6 rounded-2xl border border-white/10 bg-white/[0.03]">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-5 py-3 text-left"
      >
        <span className="font-display text-xs font-bold uppercase tracking-widest text-slate-400">
          复盘历史记录
        </span>
        <span className="text-xs text-slate-500">{open ? "▲ 收起" : "▼ 展开"}</span>
      </button>

      {open && (
        <div className="border-t border-white/10 px-5 py-3">
          {loading ? (
            <p className="text-xs text-slate-500 animate-pulse">加载中…</p>
          ) : rows.length === 0 ? (
            <p className="text-xs text-slate-600">暂无复盘记录，上传录音后自动出现。</p>
          ) : (
            <div className="space-y-1">
              {rows.map((r) => (
                <div
                  key={r.job_id}
                  className="flex items-center gap-3 rounded-lg border border-white/5 bg-black/20 px-3 py-2 text-xs"
                >
                  <span className="w-28 shrink-0 font-mono text-[10px] text-slate-500">
                    {fmt(r.created_at)}
                  </span>
                  <span className={`w-14 shrink-0 font-bold ${STATUS_COLOR[r.status] ?? "text-slate-400"}`}>
                    {STATUS_LABEL[r.status] ?? r.status}
                  </span>
                  {/* 机构名称（优先展示） */}
                  {r.institution_id && !r.institution_id.startsWith("待确认_") && !r.error_summary ? (
                    <span className="truncate max-w-[100px] shrink-0 text-[10px] font-semibold text-cyan-300/80" title={r.institution_id}>
                      🏢 {r.institution_id}
                    </span>
                  ) : null}
                  {/* 被访谈人/路演标识 */}
                  {r.interviewee && !r.error_summary ? (
                    <span className="truncate max-w-[100px] text-[10px] text-slate-400" title={r.interviewee}>
                      {r.interviewee}
                    </span>
                  ) : null}
                  {r.error_summary && (
                    <span className="truncate text-[10px] text-rose-300" title={r.error_summary}>
                      {r.error_summary}
                    </span>
                  )}
                  {r.warnings?.institution_extract && !r.error_summary && (
                    <span className="truncate text-[10px] text-amber-300">
                      ⚠️ 机构未自动抽取
                    </span>
                  )}
                  <div className="ml-auto flex shrink-0 gap-2">
                    {/* 待确认参与人 badge */}
                    {r.status === "completed" && !r.participants_confirmed ? (
                      <button
                        type="button"
                        onClick={() => onPendingConfirm?.(r.job_id, r.interviewee ?? null)}
                        className="rounded border border-amber-400/60 bg-amber-400/10 px-2 py-0.5 text-[10px] font-bold text-amber-300 hover:bg-amber-400/20 animate-pulse"
                      >
                        ⚡ 确认参与人
                      </button>
                    ) : r.status === "completed" && r.participants_confirmed ? (
                      <span className="text-[10px] text-emerald-500/70">✓ 已确认</span>
                    ) : null}
                    {r.has_report && (
                      <button
                        type="button"
                        onClick={() => navigate(`/review/${r.job_id}`)}
                        className="rounded border border-cyan/40 px-2 py-0.5 text-[10px] font-bold text-cyan hover:bg-cyan/10"
                      >
                        打开审查台
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
          <button
            type="button"
            onClick={() => void load()}
            className="mt-2 text-[10px] text-slate-500 hover:text-slate-300"
          >
            刷新
          </button>
        </div>
      )}
    </div>
  );
}
