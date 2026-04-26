import { useCallback, useEffect, useRef, useState } from "react";
import type { RiskPoint } from "../../../types/review";
import { RiskPointCard } from "./RiskPointCard";

interface RiskPointListProps {
  points: RiskPoint[];
  isReadonly: boolean;
  onChange: (index: number, updated: RiskPoint) => void;
  onDelete: (index: number) => void;
  intervieweeName?: string | null;
}

export function RiskPointList({
  points,
  isReadonly,
  onChange,
  onDelete,
  intervieweeName,
}: RiskPointListProps) {
  const [navIndex, setNavIndex] = useState(0);
  const n = points.length;
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (navIndex >= n) setNavIndex(Math.max(0, n - 1));
  }, [n, navIndex]);

  const scrollTo = useCallback((i: number) => {
    const el = document.getElementById(`risk-point-${i + 1}`);
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
    setNavIndex(i);
  }, []);

  const goPrev = useCallback(() => {
    if (n < 2) return;
    const j = (navIndex - 1 + n) % n;
    scrollTo(j);
  }, [n, navIndex, scrollTo]);

  const goNext = useCallback(() => {
    if (n < 2) return;
    const j = (navIndex + 1) % n;
    scrollTo(j);
  }, [n, navIndex, scrollTo]);

  return (
    <div ref={listRef} className="space-y-0">
      <div className="mb-2 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-slate-400">
          风险点（{n} 条）
          {intervieweeName?.trim() ? (
            <span className="ml-2 text-cyan-200/80">
              · 被访谈人（答方）「{intervieweeName.trim()}」
            </span>
          ) : null}
        </p>
        {n > 1 && (
          <div className="flex flex-wrap items-center gap-2 text-[11px]">
            <span className="text-slate-500">
              第 {navIndex + 1} / {n} 条
            </span>
            <button
              type="button"
              onClick={goPrev}
              className="rounded border border-white/20 px-2 py-0.5 text-cyan-300 hover:bg-white/5"
            >
              上一条
            </button>
            <button
              type="button"
              onClick={goNext}
              className="rounded border border-white/20 px-2 py-0.5 text-cyan-300 hover:bg-white/5"
            >
              下一条
            </button>
            <div className="hidden sm:flex flex-wrap gap-0.5 max-w-[200px] overflow-x-auto">
              {points.map((pt, i) => (
                <button
                  key={pt._rid ?? `rp-${i}`}
                  type="button"
                  title={`跳至 #${i + 1}`}
                  onClick={() => void scrollTo(i)}
                  className={`min-w-[1.4rem] rounded px-0.5 py-0.5 ${
                    i === navIndex ? "bg-cyan-600/40 text-white" : "text-slate-500 hover:text-cyan-200"
                  }`}
                >
                  {i + 1}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      {points.length === 0 ? (
        <p className="text-xs text-slate-500">暂无风险点</p>
      ) : (
        points.map((pt, i) => (
          <RiskPointCard
            key={pt._rid ?? i}
            point={pt}
            index={i + 1}
            isReadonly={isReadonly}
            onChange={(updated) => onChange(i, updated)}
            onDelete={() => onDelete(i)}
            intervieweeName={intervieweeName}
          />
        ))
      )}
    </div>
  );
}
