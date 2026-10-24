/**
 * BP vs 访谈 口径比对（吴素实测评为"最有价值"）
 *
 * 粘贴 BP 正文 → 和最近几场高管访谈交叉比 → 标 一致/偏差/矛盾。
 * 揪"BP 写 800 万 vs 访谈说 8 万"这种硬矛盾，投资人一追问就崩。
 */
import { useCallback, useState } from "react";
import { api } from "../api/client";

interface IvStmt { source: string; statement: string; }
interface Comparison {
  topic: string;
  bp_statement: string;
  interview_statements: IvStmt[];
  level: string;
  note: string;
}
interface Report {
  bp_topics: number;
  checked_interviews: string[];
  comparisons: Comparison[];
  hard_conflicts: Comparison[];
  counts: Record<string, number>;
  note: string;
}

interface Props { open: boolean; onClose: () => void; tenantId: string; }

const LEVEL: Record<string, { label: string; cls: string }> = {
  consistent: { label: "一致", cls: "text-emerald-700 bg-emerald-50 border-emerald-200" },
  deviation: { label: "偏差", cls: "text-amber-700 bg-amber-50 border-amber-200" },
  conflict: { label: "矛盾", cls: "text-red-700 bg-red-50 border-red-200" },
  review: { label: "待核", cls: "text-slate-600 bg-slate-50 border-slate-200" },
};

export function BpConsistencyWizard({ open, onClose, tenantId }: Props) {
  const [bpText, setBpText] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const run = useCallback(async () => {
    setError("");
    if (!bpText.trim()) { setError("请先粘贴 BP 正文。"); return; }
    setBusy(true);
    try {
      const { data } = await api.post<Report>("/api/v1/consistency/bp-check", {
        tenant_id: tenantId, bp_text: bpText,
      });
      setReport(data);
    } catch (e) {
      setError(`比对失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }, [bpText, tenantId]);

  const close = useCallback(() => { setBpText(""); setReport(null); setError(""); onClose(); }, [onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-2xl bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-bold text-gray-800">🔍 BP × 访谈 口径比对</h2>
          <button type="button" onClick={close} className="text-gray-400 hover:text-gray-700">✕</button>
        </div>
        <div className="px-6 py-5 space-y-4">
          <p className="text-sm text-gray-600">
            把 BP 正文粘进来，和最近几场高管访谈交叉比，标出一致/偏差/矛盾。
            <span className="text-gray-400">（.pptx 请先复制文字；先跑过几场访谈才有数据比）</span>
          </p>
          {error && <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
          <textarea
            value={bpText} onChange={(e) => setBpText(e.target.value)} rows={6}
            placeholder="粘贴 BP 正文（关键数据/口径所在的页）…"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-800"
          />
          <button type="button" disabled={busy} onClick={run}
                  className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">
            {busy ? "比对中…" : "开始比对"}
          </button>

          {report && (
            <div className="space-y-4">
              <div className="flex flex-wrap gap-3 text-sm">
                <span className="rounded bg-gray-100 px-2 py-1 text-gray-700">BP 口径 {report.bp_topics} 个</span>
                <span className="rounded bg-gray-100 px-2 py-1 text-gray-700">访谈 {report.checked_interviews.length} 场</span>
                {report.counts?.conflict ? (
                  <span className="rounded bg-red-100 px-2 py-1 font-semibold text-red-700">🔴 硬矛盾 {report.counts.conflict}</span>
                ) : null}
                {report.counts?.deviation ? (
                  <span className="rounded bg-amber-100 px-2 py-1 text-amber-700">🟡 偏差 {report.counts.deviation}</span>
                ) : null}
              </div>

              {report.hard_conflicts.length > 0 && (
                <div>
                  <p className="mb-2 text-sm font-bold text-red-700">⚠️ 硬矛盾（投资人一追问就崩，优先对齐）</p>
                  <div className="space-y-2">
                    {report.hard_conflicts.map((c, i) => (
                      <div key={i} className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm">
                        <div className="font-semibold text-red-800">{c.topic} — {c.note}</div>
                        <div className="mt-1 text-gray-700">BP：{c.bp_statement}</div>
                        {c.interview_statements.map((iv, j) => (
                          <div key={j} className="text-gray-600">访谈（{iv.source}）：{iv.statement}</div>
                        ))}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {report.comparisons.length > 0 ? (
                <div>
                  <p className="mb-2 text-sm font-bold text-gray-700">全部比对（{report.comparisons.length}）</p>
                  <div className="space-y-1">
                    {report.comparisons.map((c, i) => {
                      const lv = LEVEL[c.level] ?? LEVEL.review;
                      return (
                        <div key={i} className="flex items-start gap-2 border-b border-gray-100 py-1.5 text-sm">
                          <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[11px] ${lv.cls}`}>{lv.label}</span>
                          <div>
                            <span className="font-medium text-gray-800">{c.topic}</span>
                            {c.note ? <span className="text-gray-500"> — {c.note}</span> : null}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : (
                <p className="text-sm text-gray-500">{report.note}</p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default BpConsistencyWizard;
