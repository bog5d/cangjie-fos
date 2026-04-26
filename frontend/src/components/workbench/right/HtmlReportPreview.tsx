import { useState } from "react";
import { api } from "../../../api/client";

interface HtmlReportPreviewProps {
  jobId: string;
  isDirty?: boolean;
  onCommitFirst?: () => Promise<void>;
}

interface GenerateResponse {
  html_path: string;
  generated_at: number;
}

type State =
  | { phase: "idle" }
  | { phase: "committing" }
  | { phase: "loading" }
  | { phase: "done"; generatedAt: number }
  | { phase: "error"; message: string };

export default function HtmlReportPreview({ jobId, isDirty, onCommitFirst }: HtmlReportPreviewProps) {
  const [state, setState] = useState<State>({ phase: "idle" });

  async function handleGenerate() {
    // 若有未提交的改动，先自动 commit，再生成报告
    if (isDirty && onCommitFirst) {
      setState({ phase: "committing" });
      try {
        await onCommitFirst();
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : "提交改动失败，请手动点「锁定」后重试";
        setState({ phase: "error", message });
        return;
      }
    }

    setState({ phase: "loading" });
    try {
      const res = await api.post<GenerateResponse>(
        `/api/pitch/jobs/${jobId}/html-report`
      );
      setState({ phase: "done", generatedAt: res.data.generated_at });
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "生成失败，请重试";
      setState({ phase: "error", message });
    }
  }

  function handleOpenReport() {
    window.open(
      `/reports/${jobId}.html`,
      "_blank",
      "noopener,noreferrer"
    );
  }

  return (
    <div className="bg-white/5 rounded-xl p-4">
      <p className="text-[10px] uppercase tracking-widest text-slate-500 mb-3">
        HTML 报告预览
      </p>

      {isDirty && state.phase === "idle" && (
        <p className="mb-2 text-[11px] text-amber-300/90">
          ⚠️ 有未锁定的改动，生成时将自动保存。
        </p>
      )}

      {state.phase === "idle" && (
        <button
          onClick={handleGenerate}
          className="text-xs px-3 py-1.5 rounded-lg bg-cyan-500/20 text-cyan-300 hover:bg-cyan-500/30 transition-colors"
        >
          生成 HTML 报告
        </button>
      )}

      {state.phase === "committing" && (
        <p className="text-slate-400 text-xs animate-pulse">正在保存改动…</p>
      )}

      {state.phase === "loading" && (
        <p className="text-slate-400 text-xs animate-pulse">正在生成报告…</p>
      )}

      {state.phase === "done" && (
        <div className="space-y-2">
          <p className="text-xs text-emerald-400">
            ✓ 报告已生成 &nbsp;
            <span className="text-slate-500">
              {new Date(state.generatedAt * 1000).toLocaleString("zh-CN")}
            </span>
          </p>
          <div className="flex gap-2">
            <button
              onClick={handleOpenReport}
              className="text-xs px-3 py-1.5 rounded-lg bg-cyan-500/20 text-cyan-300 hover:bg-cyan-500/30 transition-colors"
            >
              在新窗口打开报告
            </button>
            <button
              onClick={handleGenerate}
              className="text-xs px-3 py-1.5 rounded-lg bg-white/5 text-slate-400 hover:bg-white/10 transition-colors"
            >
              重新生成
            </button>
          </div>
        </div>
      )}

      {state.phase === "error" && (
        <div className="space-y-2">
          <p className="text-rose-300 text-xs">{state.message}</p>
          <button
            onClick={handleGenerate}
            className="text-xs px-3 py-1.5 rounded-lg bg-white/5 text-slate-400 hover:bg-white/10 transition-colors"
          >
            重试
          </button>
        </div>
      )}
    </div>
  );
}
