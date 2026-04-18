import { useEffect, useState } from "react";
import axios from "axios";
import { api } from "../api/client";

export type PitchReportPreviewModalProps = {
  open: boolean;
  jobId: string | null;
  onClose: () => void;
};

function pickL1Summary(report: Record<string, unknown>): { title: string; lines: string[] } {
  const scene = report.scene_analysis as Record<string, unknown> | undefined;
  const sceneType = typeof scene?.scene_type === "string" ? scene.scene_type : "—";
  const roles = typeof scene?.speaker_roles === "string" ? scene.speaker_roles : "—";
  const score = typeof report.total_score === "number" ? String(report.total_score) : "—";
  const ded =
    typeof report.total_score_deduction_reason === "string" ? report.total_score_deduction_reason.trim() : "";
  const pos = Array.isArray(report.positive_highlights)
    ? (report.positive_highlights as unknown[]).filter((x) => typeof x === "string").slice(0, 5)
    : [];
  const risks = Array.isArray(report.risk_points)
    ? (report.risk_points as unknown[]).filter((x) => typeof x === "string").slice(0, 5)
    : [];
  const lines: string[] = [
    `场景：${sceneType}`,
    `角色：${roles}`,
    `总分：${score}`,
  ];
  if (ded) {
    lines.push(`扣分说明：${ded}`);
  }
  if (pos.length) {
    lines.push(`亮点：${pos.join("；")}`);
  }
  if (risks.length) {
    lines.push(`风险：${risks.join("；")}`);
  }
  return { title: "复盘摘要（L1）", lines };
}

export function PitchReportPreviewModal({ open, jobId, onClose }: PitchReportPreviewModalProps) {
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    if (!open || !jobId) {
      setReport(null);
      setErr(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setErr(null);
    void (async () => {
      try {
        const { data } = await api.get<{
          status?: string;
          report?: Record<string, unknown> | null;
          error_summary?: string | null;
          error_detail?: string | null;
          error_code?: string | null;
        }>(`/api/pitch/jobs/${jobId}`);
        if (cancelled) return;
        if (data.status === "failed") {
          const s = (data.error_summary ?? "").trim() || "任务失败";
          setErr(`该任务已失败：${s}`);
          setReport(null);
          return;
        }
        setReport(data.report && typeof data.report === "object" ? (data.report as Record<string, unknown>) : null);
      } catch (e: unknown) {
        if (!cancelled) {
          let msg = "加载失败";
          if (axios.isAxiosError(e)) {
            const d = e.response?.data as { detail?: string } | undefined;
            msg = (d?.detail && String(d.detail)) || e.message;
          } else if (e instanceof Error) {
            msg = e.message;
          }
          setErr(msg);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, jobId]);

  if (!open || !jobId) return null;

  const l1 = report ? pickL1Summary(report) : { title: "复盘摘要（L1）", lines: [] as string[] };
  const md =
    `# ${l1.title}\n` +
    `job_id: \`${jobId}\`\n\n` +
    l1.lines.map((x) => `- ${x}`).join("\n");

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      <button type="button" className="absolute inset-0 bg-black/80 backdrop-blur-sm" aria-label="关闭" onClick={onClose} />
      <div
        className="relative max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-cyan/30 bg-gradient-to-b from-[#0a0a14] to-black p-5 shadow-[0_0_40px_rgba(34,211,238,0.2)]"
        role="dialog"
        aria-modal="true"
      >
        <header className="mb-4 flex items-start justify-between gap-2">
          <div>
            <p className="font-display text-[10px] uppercase tracking-[0.35em] text-cyan/80">Phase 6.3</p>
            <h2 className="font-display text-lg font-semibold text-white">查看报告</h2>
            <p className="mt-1 font-mono text-[10px] text-slate-500">{jobId}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-white/15 px-2 py-1 text-xs text-slate-300 hover:border-cyan/40 hover:text-white"
          >
            关闭
          </button>
        </header>
        {loading ? <p className="text-sm text-slate-400">载入报告 JSON…</p> : null}
        {err ? <p className="text-sm text-rose-300">{err}</p> : null}
        {!loading && !err && report ? (
          <div className="space-y-3 text-sm text-slate-200">
            <ul className="list-inside list-disc space-y-1 text-slate-300">
              {l1.lines.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
            <div className="flex flex-wrap gap-2 border-t border-white/10 pt-4">
              <button
                type="button"
                className="rounded-lg bg-cyan/80 px-3 py-1.5 text-xs font-bold text-black"
                onClick={() => {
                  void navigator.clipboard.writeText(md).catch(() => {
                    /* ignore */
                  });
                }}
              >
                复制摘要 Markdown
              </button>
              <button
                type="button"
                className="rounded-lg border border-white/20 px-3 py-1.5 text-xs text-slate-200 hover:border-cyan/40"
                onClick={() => {
                  const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
                  const a = document.createElement("a");
                  a.href = URL.createObjectURL(blob);
                  a.download = `pitch-report-${jobId}.json`;
                  a.click();
                  URL.revokeObjectURL(a.href);
                }}
              >
                下载 report.json
              </button>
            </div>
          </div>
        ) : null}
        {!loading && !err && !report ? (
          <p className="text-sm text-slate-500">该任务暂无 report 字段（可能仍在写入或失败）。</p>
        ) : null}
      </div>
    </div>
  );
}
