import { useLayoutEffect, useMemo, useRef, useState } from "react";
import type { RiskPoint } from "../../../types/review";
import { formatSpeakerIdForUi, inferRiskPointSpeakers } from "../../../lib/riskPointSpeakers";
import { AudioSnippetPlayer } from "../AudioSnippetPlayer";
import { useWorkbench } from "../WorkbenchContext";

interface RiskPointCardProps {
  point: RiskPoint;
  index: number;
  isReadonly: boolean;
  onChange: (updated: RiskPoint) => void;
  onDelete: () => void;
  /** 上传向导中的被访谈人，用于与 ASR 说话人并列展示 */
  intervieweeName?: string | null;
}

const LEVEL_BADGE: Record<RiskPoint["risk_level"], string> = {
  严重: "bg-red-900/60 text-red-300",
  一般: "bg-amber-900/60 text-amber-300",
  轻微: "bg-slate-700 text-slate-300",
};

const TA_CLASS =
  "w-full min-h-[7rem] rounded-lg border border-white/15 bg-black/35 px-3 py-2.5 text-sm text-white/95 outline-none focus:border-cyan-400/50";
const RO_CLASS =
  "w-full min-h-[7rem] rounded-lg border border-white/8 bg-black/20 px-3 py-2.5 text-sm text-slate-200/95 whitespace-pre-wrap break-words leading-relaxed";

function useAutoTextareaHeight(value: string) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.max(el.scrollHeight, 112)}px`;
  }, [value]);
  return ref;
}

function splitImprovement(s: string): { lead: string; rest: string } {
  const t = s || "";
  const n = t.indexOf("\n");
  if (n === -1) return { lead: t.trim(), rest: "" };
  return { lead: t.slice(0, n).trim(), rest: t.slice(n + 1).trim() };
}

export function RiskPointCard({
  point,
  index,
  isReadonly,
  onChange,
  onDelete,
  intervieweeName,
}: RiskPointCardProps) {
  const { jobId, wordsMap } = useWorkbench();
  const [chainOpen, setChainOpen] = useState(false);
  const taImp = useAutoTextareaHeight(point.improvement_suggestion);

  const { impLead, impRest } = useMemo(
    () => {
      const { lead, rest } = splitImprovement(point.improvement_suggestion);
      return { impLead: lead, impRest: rest };
    },
    [point.improvement_suggestion],
  );

  const speakerInfo = useMemo(() => {
    if (point.is_manual_entry) {
      return { line: "手工条目（无词级说话人）", multi: false };
    }
    const { dominant, uniqueIds, multiSpeaker } = inferRiskPointSpeakers(
      wordsMap,
      point.start_word_index,
      point.end_word_index,
    );
    if (!uniqueIds.length) {
      return { line: "本段无词级说话人 id", multi: false };
    }
    const idLabel = formatSpeakerIdForUi(dominant);
    const iv = (intervieweeName || "").trim();
    const who =
      multiSpeaker
        ? `多说话人交织（主：${idLabel}；共 ${uniqueIds.length} 人）`
        : `本段主说话人：${idLabel}`;
    const cap = iv ? ` · 答方（提交）：「${iv}」` : "";
    return { line: who + cap, multi: multiSpeaker };
  }, [wordsMap, point, intervieweeName]);

  const focusHint = (point.risk_type || "").trim() || (point.deduction_reason || "").split(/[。\n]/)[0]?.trim() || "";

  return (
    <div
      className="bg-white/5 rounded-xl p-4 mb-3 space-y-3 scroll-mt-24"
      id={`risk-point-${index}`}
    >
      <div className="flex items-start gap-2 flex-wrap">
        <span className="font-mono text-xs text-slate-500">#{index}</span>
        <span
          className={`text-xs px-2 py-0.5 rounded-full font-medium ${LEVEL_BADGE[point.risk_level]}`}
        >
          {point.risk_level}
        </span>
        {point.risk_type && (
          <span className="text-[10px] px-2 py-0.5 rounded border border-cyan-500/30 text-cyan-200/90">
            {point.risk_type}
          </span>
        )}
        <div className="flex-1" />
        {!isReadonly && (
          <button
            type="button"
            onClick={onDelete}
            className="text-xs text-rose-400 hover:text-rose-300 transition-colors"
          >
            删除
          </button>
        )}
      </div>

      {speakerInfo.line && (
        <p className="text-[11px] text-cyan-200/85 leading-snug border-l-2 border-cyan-500/40 pl-2">
          {speakerInfo.line}
        </p>
      )}

      {point.problem_summary && (point.problem_summary || "").trim() ? (
        <p className="text-xs text-amber-200/90 font-medium line-clamp-2">
          本条在讲什么：{point.problem_summary.trim()}
        </p>
      ) : null}

      <div>
        <p className="text-xs text-slate-400 mb-1">改进建议</p>
        {isReadonly ? (
          <div>
            {impLead ? (
              <p className="text-sm font-semibold text-white mb-1.5 border-b border-white/10 pb-1.5">
                {impLead}
              </p>
            ) : null}
            {impRest ? (
              <div className={RO_CLASS + " min-h-0 text-slate-300/95"}>{impRest}</div>
            ) : impLead ? null : (
              <div className={RO_CLASS}>{point.improvement_suggestion}</div>
            )}
          </div>
        ) : (
          <textarea
            ref={taImp}
            value={point.improvement_suggestion}
            onChange={(e) =>
              onChange({ ...point, improvement_suggestion: e.target.value })
            }
            className={TA_CLASS}
            rows={4}
            placeholder="首行可写一条结论/指令，回车后写展开范例与说明"
            spellCheck={false}
          />
        )}
      </div>

      <div className="flex flex-wrap items-start gap-3">
        <div>
          <p className="text-xs text-slate-400 mb-0.5">扣分</p>
          {isReadonly ? (
            <span className="text-amber-400 text-sm">-{point.score_deduction}分</span>
          ) : (
            <div className="flex items-center gap-1">
              <span className="text-amber-400 text-sm">-</span>
              <input
                type="number"
                value={point.score_deduction}
                min={0}
                onChange={(e) =>
                  onChange({
                    ...point,
                    score_deduction: Number(e.target.value),
                  })
                }
                className="bg-transparent border-b border-white/20 text-sm text-amber-400 outline-none w-16"
              />
              <span className="text-amber-400 text-sm">分</span>
            </div>
          )}
        </div>
        {focusHint ? (
          <p className="text-[11px] text-slate-500 max-w-md flex-1 min-w-[12rem]">
            <span className="text-slate-500">本条重点（练）：</span>
            <span className="text-slate-400">{focusHint}</span>
          </p>
        ) : null}
      </div>

      <div>
        <p className="text-xs text-slate-400 mb-1">扣分说明</p>
        {isReadonly ? (
          <p className="text-xs text-slate-400 whitespace-pre-wrap">{point.deduction_reason}</p>
        ) : (
          <textarea
            value={point.deduction_reason}
            onChange={(e) =>
              onChange({ ...point, deduction_reason: e.target.value })
            }
            className={TA_CLASS + " min-h-[3rem] text-sm"}
            rows={2}
          />
        )}
      </div>

      <AudioSnippetPlayer
        jobId={jobId}
        startWordIndex={point.start_word_index}
        endWordIndex={point.end_word_index}
        isManualEntry={point.is_manual_entry}
      />

      <div>
        <button
          type="button"
          onClick={() => setChainOpen((prev) => !prev)}
          className="text-[10px] text-slate-500 cursor-pointer hover:text-slate-400 transition-colors"
        >
          {chainOpen ? "AI 推理链 ▲" : "AI 推理链 ▼"}
        </button>
        {chainOpen && (
          <div className="mt-2 bg-black/30 rounded-lg p-2 text-xs text-slate-400 space-y-2">
            <div>
              <span className="text-slate-500">Tier1（VC视角）：</span>
              {point.tier1_general_critique}
            </div>
            <div>
              <span className="text-slate-500">Tier2（QA对齐）：</span>
              {point.tier2_qa_alignment}
            </div>
            <div>
              <span className="text-slate-500">扣分依据：</span>
              {point.deduction_reason}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
