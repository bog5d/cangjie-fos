

interface WorkbenchHeaderProps {
  jobId: string;
  status: string;
  isCommitted: boolean;
  committedAt: string | null;
  isDirty: boolean;
  onBack: () => void;
  onCommit: () => void;
  onUnlock?: () => void;
  committing: boolean;
  unlocking?: boolean;
}

function StatusBadge({ status }: { status: string }) {
  const upper = status.toUpperCase();
  if (upper === 'COMPLETED') {
    return (
      <span className="text-xs font-mono text-green-400 border border-green-400/30 px-1.5 py-0.5 rounded">
        {upper}
      </span>
    );
  }
  if (upper === 'FAILED') {
    return (
      <span className="text-xs font-mono text-red-400 border border-red-400/30 px-1.5 py-0.5 rounded">
        {upper}
      </span>
    );
  }
  return (
    <span className="text-xs font-mono text-slate-400 border border-slate-400/30 px-1.5 py-0.5 rounded">
      {upper}
    </span>
  );
}

export default function WorkbenchHeader({
  jobId,
  status,
  isCommitted,
  committedAt,
  isDirty,
  onBack,
  onCommit,
  onUnlock,
  committing,
  unlocking,
}: WorkbenchHeaderProps) {
  const commitDisabled = committing || isCommitted || !isDirty;

  return (
    <header className="h-12 flex items-center justify-between px-4 border-b border-white/10 bg-[#0a0a14]">
      {/* Left: back button */}
      <button
        onClick={onBack}
        className="text-xs text-slate-400 hover:text-cyan-400 transition-colors px-2 py-1 rounded hover:bg-white/5"
      >
        ← 返回
      </button>

      {/* Center: job id + status + committed info */}
      <div className="flex items-center gap-3">
        <span className="font-mono text-xs text-slate-500">{jobId}</span>
        <StatusBadge status={status} />
        {isCommitted && committedAt && (
          <span className="text-xs text-slate-500">
            ✓ 已审查 {committedAt}
          </span>
        )}
      </div>

      {/* Right: unlock + commit buttons */}
      <div className="flex items-center gap-2">
        {isCommitted && onUnlock && (
          <button
            onClick={onUnlock}
            disabled={unlocking}
            className="bg-amber-800/60 hover:bg-amber-700/80 text-amber-300 text-xs px-3 py-1.5 rounded-lg disabled:opacity-40 transition-colors border border-amber-600/30"
          >
            {unlocking ? '解锁中…' : '🔓 解锁编辑'}
          </button>
        )}
        <button
          onClick={onCommit}
          disabled={commitDisabled}
          className="bg-cyan-600 hover:bg-cyan-500 text-white text-xs px-3 py-1.5 rounded-lg disabled:opacity-40 transition-colors"
        >
          {isCommitted ? '已锁定 ✓' : '锁定 ▶'}
        </button>
      </div>
    </header>
  );
}
