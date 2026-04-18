import { useState } from "react";
import type { RiskPoint } from "../../../types/review";
import { AudioSnippetPlayer } from "../AudioSnippetPlayer";
import { useWorkbench } from "../WorkbenchContext";

interface RiskPointCardProps {
  point: RiskPoint;
  index: number;
  isReadonly: boolean;
  onChange: (updated: RiskPoint) => void;
  onDelete: () => void;
}

const LEVEL_BADGE: Record<RiskPoint["risk_level"], string> = {
  严重: "bg-red-900/60 text-red-300",
  一般: "bg-amber-900/60 text-amber-300",
  轻微: "bg-slate-700 text-slate-300",
};

const INPUT_CLASS =
  "bg-transparent border-b border-white/20 text-sm text-white focus:border-cyan-400/60 outline-none w-full resize-none";

const FIELD_LABEL_CLASS = "text-xs text-slate-400 mb-1";

export function RiskPointCard({
  point,
  index,
  isReadonly,
  onChange,
  onDelete,
}: RiskPointCardProps) {
  const { jobId } = useWorkbench();
  const [chainOpen, setChainOpen] = useState(false);

  return (
    <div className="bg-white/5 rounded-xl p-4 mb-3 space-y-3">
      {/* 顶栏 */}
      <div className="flex items-center gap-2">
        <span className="font-mono text-xs text-slate-500">#{index}</span>
        <span
          className={`text-xs px-2 py-0.5 rounded-full font-medium ${LEVEL_BADGE[point.risk_level]}`}
        >
          {point.risk_level}
        </span>
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

      {/* 原文实录 */}
      <div>
        <p className={FIELD_LABEL_CLASS}>原文实录</p>
        {isReadonly ? (
          <p className="text-sm text-slate-200">{point.original_text}</p>
        ) : (
          <textarea
            rows={2}
            value={point.original_text}
            onChange={(e) =>
              onChange({ ...point, original_text: e.target.value })
            }
            className={INPUT_CLASS}
          />
        )}
      </div>

      {/* 改进建议 */}
      <div>
        <p className={FIELD_LABEL_CLASS}>改进建议</p>
        {isReadonly ? (
          <p className="text-sm text-slate-200">{point.improvement_suggestion}</p>
        ) : (
          <textarea
            rows={2}
            value={point.improvement_suggestion}
            onChange={(e) =>
              onChange({ ...point, improvement_suggestion: e.target.value })
            }
            className={INPUT_CLASS}
          />
        )}
      </div>

      {/* 扣分 */}
      <div className="flex items-center gap-3">
        <p className={FIELD_LABEL_CLASS + " mb-0"}>扣分</p>
        {isReadonly ? (
          <span className="text-amber-400 text-sm">
            -{point.score_deduction}分
          </span>
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
              className={INPUT_CLASS + " w-16 text-amber-400"}
            />
            <span className="text-amber-400 text-sm">分</span>
          </div>
        )}
      </div>

      {/* 扣分说明 */}
      <div>
        <p className={FIELD_LABEL_CLASS}>扣分说明</p>
        {isReadonly ? (
          <span className="text-xs text-slate-400">{point.deduction_reason}</span>
        ) : (
          <input
            type="text"
            value={point.deduction_reason}
            onChange={(e) =>
              onChange({ ...point, deduction_reason: e.target.value })
            }
            className={INPUT_CLASS + " text-xs"}
          />
        )}
      </div>

      {/* 音频播放 */}
      <AudioSnippetPlayer
        jobId={jobId}
        startWordIndex={point.start_word_index}
        endWordIndex={point.end_word_index}
        isManualEntry={point.is_manual_entry}
      />

      {/* AI 推理链折叠区 */}
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
