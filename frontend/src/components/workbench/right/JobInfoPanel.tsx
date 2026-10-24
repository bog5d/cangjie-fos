import React from "react";

interface JobInfoPanelProps {
  jobId: string;
  status: string;
  createdAt?: number;
  totalWords: number;
  durationSec: number;
  originalScore: number;
  currentScore: number;
  committedAt: number | null;
  /** 上传向导填写的被访谈人 */
  interviewee?: string | null;
}

const STATUS_BADGE: Record<string, string> = {
  COMPLETED: "bg-emerald-500/20 text-emerald-400",
  FAILED: "bg-rose-500/20 text-rose-400",
};

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_BADGE[status] ?? "bg-slate-500/20 text-slate-400";
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${cls}`}>
      {status}
    </span>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-2">
      <span className="text-slate-500 shrink-0">{label}</span>
      <span className="text-slate-300 text-right">{children}</span>
    </div>
  );
}

export default function JobInfoPanel({
  jobId,
  status,
  createdAt,
  totalWords,
  durationSec,
  originalScore,
  currentScore,
  committedAt,
  interviewee,
}: JobInfoPanelProps) {
  const scoreModified = originalScore !== currentScore;

  return (
    <div className="bg-white/5 rounded-xl p-4">
      <p className="text-[10px] uppercase tracking-widest text-slate-500 mb-3">
        任务信息
      </p>

      <div className="space-y-1.5 text-xs">
        <Row label="Job ID">
          <span className="font-mono text-slate-400 break-all">{jobId}</span>
        </Row>

        <Row label="状态">
          <StatusBadge status={status} />
        </Row>

        {interviewee && interviewee.trim() ? (
          <Row label="被访谈人">
            <span className="text-cyan-200/90">{interviewee.trim()}</span>
          </Row>
        ) : null}

        {createdAt !== undefined && (
          <Row label="创建时间">
            {new Date(createdAt * 1000).toLocaleString("zh-CN")}
          </Row>
        )}

        <Row label="转写词数">{totalWords} 词</Row>

        <Row label="时长">{Math.round(durationSec)} 秒</Row>

        <Row label="评分">
          <span>
            {originalScore} → {currentScore}
            {scoreModified && (
              <span className="ml-1 text-amber-400">已修改</span>
            )}
          </span>
        </Row>

        <Row label="审查状态">
          {committedAt !== null ? (
            <span className="text-emerald-400">
              ✓ {new Date(committedAt * 1000).toLocaleString("zh-CN")}
            </span>
          ) : (
            <span className="text-slate-500">未审查</span>
          )}
        </Row>
      </div>
    </div>
  );
}
