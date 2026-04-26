import { useState } from "react";
import type { RiskPoint } from "../../../types/review";

interface AddRiskPointFormProps {
  onAdd: (point: Omit<RiskPoint, "_rid">) => void;
  disabled: boolean;
}

type RiskLevel = RiskPoint["risk_level"];

const DEFAULT_FORM: Omit<RiskPoint, "_rid"> = {
  risk_level: "一般",
  problem_summary: "",
  risk_type: "",
  tier1_general_critique: "",
  tier2_qa_alignment: "",
  improvement_suggestion: "",
  original_text: "",   // kept in data model; not displayed in UI
  start_word_index: 0,
  end_word_index: 0,
  score_deduction: 0,
  deduction_reason: "",
  is_manual_entry: true,
};

const inputCls =
  "bg-transparent border-b border-white/20 text-sm text-white focus:border-cyan-400/60 outline-none w-full";

export default function AddRiskPointForm({ onAdd, disabled }: AddRiskPointFormProps) {
  const [expanded, setExpanded] = useState(false);
  const [form, setForm] = useState<Omit<RiskPoint, "_rid">>(DEFAULT_FORM);

  function handleToggle() {
    if (!disabled) setExpanded((v) => !v);
  }

  function handleChange<K extends keyof Omit<RiskPoint, "_rid">>(
    key: K,
    value: Omit<RiskPoint, "_rid">[K]
  ) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function handleSubmit() {
    onAdd({ ...form, is_manual_entry: true });
    setForm(DEFAULT_FORM);
    setExpanded(false);
  }

  return (
    <div className="bg-white/5 rounded-xl p-4 mb-4">
      {/* 标题行 */}
      <button
        type="button"
        className={`text-xs text-cyan-400 cursor-pointer select-none flex items-center gap-1 ${
          disabled ? "opacity-40 cursor-not-allowed" : ""
        }`}
        onClick={handleToggle}
        disabled={disabled}
      >
        <span>➕</span>
        <span>新增遗漏痛点</span>
      </button>

      {/* 展开表单 */}
      {expanded && (
        <div className="mt-3 space-y-3 text-sm">
          {/* 风险等级 */}
          <div>
            <label className="text-xs text-slate-400 block mb-1">风险等级</label>
            <select
              className="bg-white/10 border border-white/20 text-white text-sm rounded-lg px-2 py-1 outline-none focus:border-cyan-400/60 w-full"
              value={form.risk_level}
              disabled={disabled}
              onChange={(e) =>
                handleChange("risk_level", e.target.value as RiskLevel)
              }
            >
              <option value="严重">严重</option>
              <option value="一般">一般</option>
              <option value="轻微">轻微</option>
            </select>
          </div>

          {/* 改进建议 */}
          <div>
            <label className="text-xs text-slate-400 block mb-1">改进建议</label>
            <textarea
              rows={2}
              className={`${inputCls} resize-none`}
              placeholder="针对该风险点的具体改进建议"
              value={form.improvement_suggestion}
              disabled={disabled}
              onChange={(e) =>
                handleChange("improvement_suggestion", e.target.value)
              }
            />
          </div>

          {/* 扣分分值 */}
          <div>
            <label className="text-xs text-slate-400 block mb-1">扣分分值</label>
            <input
              type="number"
              min={0}
              max={50}
              className={`${inputCls} w-24`}
              value={form.score_deduction}
              disabled={disabled}
              onChange={(e) =>
                handleChange("score_deduction", Number(e.target.value))
              }
            />
          </div>

          {/* 扣分原因 */}
          <div>
            <label className="text-xs text-slate-400 block mb-1">扣分原因</label>
            <input
              className={inputCls}
              placeholder="简述扣分依据"
              value={form.deduction_reason}
              disabled={disabled}
              onChange={(e) => handleChange("deduction_reason", e.target.value)}
            />
          </div>

          {/* 提交按钮 */}
          <div className="flex justify-end pt-1">
            <button
              type="button"
              className="bg-cyan-900/60 hover:bg-cyan-800/80 text-cyan-300 text-xs px-3 py-1.5 rounded-lg disabled:opacity-40 disabled:cursor-not-allowed"
              disabled={disabled}
              onClick={handleSubmit}
            >
              添加
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
