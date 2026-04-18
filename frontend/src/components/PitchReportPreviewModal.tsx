export type PitchReportPreviewModalProps = {
  open: boolean;
  jobId: string | null;
  onClose: () => void;
};

export function PitchReportPreviewModal({ open, jobId, onClose }: PitchReportPreviewModalProps) {
  if (!open || !jobId) return null;

  const reviewUrl = `/review/${jobId}${window.location.search}`;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 bg-black/80 backdrop-blur-sm"
        aria-label="关闭"
        onClick={onClose}
      />
      <div
        className="relative w-full max-w-sm rounded-2xl border border-cyan/30 bg-gradient-to-b from-[#0a0a14] to-black p-6 shadow-[0_0_40px_rgba(34,211,238,0.2)] flex flex-col items-center gap-4"
        role="dialog"
        aria-modal="true"
      >
        <p className="font-display text-[10px] uppercase tracking-[0.35em] text-cyan/80">Phase 6.4</p>
        <h2 className="font-display text-lg font-semibold text-white">深度审查台</h2>
        <p className="font-mono text-[10px] text-slate-500">{jobId}</p>
        <p className="text-xs text-slate-400 text-center">
          点击下方按钮进入全屏审查台，支持逐条编辑风险点、音频播放与 HTML 报告生成。
        </p>
        <div className="flex gap-3">
          <a
            href={reviewUrl}
            onClick={(e) => { e.preventDefault(); window.open(reviewUrl, "_self"); }}
            className="rounded-lg bg-cyan-600 hover:bg-cyan-500 px-4 py-2 text-xs font-bold text-white transition-colors"
          >
            进入审查台 →
          </a>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-white/15 px-4 py-2 text-xs text-slate-300 hover:border-cyan/40 hover:text-white"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
