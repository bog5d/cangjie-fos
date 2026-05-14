/**
 * 路演情报视图（Phase 7）
 * 当 original_report.report_type === "roadshow_intel" 时渲染此视图。
 * 支持编辑文本摘要字段（atmosphere_summary、institution_update、hidden_concerns）。
 */
import { useState } from "react";
import type { RoadshowIntelReport, IntelQuestion, IntelSignal, IntelAction } from "../../types/review";

const ATMOSPHERE_LABEL: Record<string, { text: string; cls: string }> = {
  hot: { text: "🔥 高度积极", cls: "text-orange-400 border-orange-400/40 bg-orange-400/10" },
  warm: { text: "✅ 正常推进", cls: "text-emerald-400 border-emerald-400/40 bg-emerald-400/10" },
  cold: { text: "❄️ 兴趣不足", cls: "text-slate-400 border-slate-400/40 bg-slate-400/10" },
};

const STAGE_LABEL: Record<string, string> = {
  first_contact: "初次路演",
  deep_discussion: "深度沟通",
  pre_dd: "准尽调",
  unknown: "阶段未知",
};

const PRIORITY_BADGE: Record<string, string> = {
  high: "bg-rose-500/20 text-rose-300 border-rose-500/30",
  medium: "bg-amber-500/20 text-amber-300 border-amber-500/30",
  low: "bg-slate-600/30 text-slate-400 border-slate-600/30",
  urgent: "bg-rose-500/20 text-rose-300 border-rose-500/30",
  normal: "bg-cyan/10 text-cyan border-cyan/30",
  optional: "bg-slate-600/30 text-slate-400 border-slate-600/30",
};

const SIGNAL_BADGE: Record<string, string> = {
  positive: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
  concern: "bg-rose-500/20 text-rose-300 border-rose-500/30",
  neutral: "bg-slate-600/30 text-slate-400 border-slate-600/30",
};
const SIGNAL_LABEL: Record<string, string> = {
  positive: "正面信号",
  concern: "疑虑/抵触",
  neutral: "中性陈述",
};

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="font-display text-[10px] font-bold uppercase tracking-[0.35em] text-cyan/70 mb-3 mt-5 first:mt-0">
      {children}
    </h3>
  );
}

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-white/10 bg-white/[0.03] p-4 ${className}`}>
      {children}
    </div>
  );
}

function Badge({ cls, children }: { cls: string; children: React.ReactNode }) {
  return (
    <span className={`inline-block rounded border px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider ${cls}`}>
      {children}
    </span>
  );
}

function QuestionCard({ q, idx }: { q: IntelQuestion; idx: number }) {
  return (
    <Card>
      <div className="flex items-start gap-2 mb-2">
        <span className="shrink-0 text-[10px] font-mono text-slate-600">#{idx + 1}</span>
        {q.speaker_id && (
          <span className="shrink-0 rounded border border-cyan/30 bg-cyan/10 px-1.5 py-0.5 text-[9px] font-bold text-cyan">
            {q.speaker_id}
          </span>
        )}
        <Badge cls={PRIORITY_BADGE[q.priority] ?? PRIORITY_BADGE.medium}>
          {q.priority === "high" ? "核心" : q.priority === "medium" ? "关注" : "礼节"}
        </Badge>
      </div>
      <p className="text-xs text-slate-200 leading-relaxed mb-2">「{q.verbatim}」</p>
      <p className="text-[11px] text-slate-400">
        <span className="text-slate-600 mr-1">背后关切：</span>
        {q.underlying_concern}
      </p>
    </Card>
  );
}

function SignalCard({ s }: { s: IntelSignal }) {
  return (
    <Card>
      <div className="flex items-center gap-2 mb-2">
        {s.speaker_id && (
          <span className="shrink-0 rounded border border-cyan/30 bg-cyan/10 px-1.5 py-0.5 text-[9px] font-bold text-cyan">
            {s.speaker_id}
          </span>
        )}
        <Badge cls={SIGNAL_BADGE[s.signal_type] ?? SIGNAL_BADGE.neutral}>
          {SIGNAL_LABEL[s.signal_type]}
        </Badge>
      </div>
      <p className="text-xs text-slate-200 leading-relaxed mb-1">「{s.verbatim}」</p>
      <p className="text-[11px] text-slate-400">{s.interpretation}</p>
    </Card>
  );
}

function ActionCard({ a }: { a: IntelAction }) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-white/5 bg-black/20 px-3 py-2">
      <Badge cls={PRIORITY_BADGE[a.priority] ?? PRIORITY_BADGE.normal}>
        {a.priority === "urgent" ? "紧急" : a.priority === "normal" ? "正常" : "可选"}
      </Badge>
      <Badge cls={a.source === "commitment" ? "bg-amber-500/20 text-amber-300 border-amber-500/30" : "bg-slate-600/30 text-slate-400 border-slate-600/30"}>
        {a.source === "commitment" ? "已承诺" : "建议"}
      </Badge>
      <div className="flex-1 min-w-0">
        <p className="text-xs text-slate-200">{a.action}</p>
        {a.actor && a.actor !== "我方" && (
          <p className="text-[10px] text-slate-500 mt-0.5">负责：{a.actor}</p>
        )}
      </div>
    </div>
  );
}

const TA = "w-full rounded-lg border border-white/15 bg-black/35 px-3 py-2 text-sm text-white/95 outline-none focus:border-cyan-400/50 resize-none";

interface Props {
  report: RoadshowIntelReport;
  interviewee?: string | null;
  onSave?: (updated: RoadshowIntelReport) => void;
  saving?: boolean;
}

export default function RoadshowIntelView({ report, interviewee, onSave, saving }: Props) {
  const atm = ATMOSPHERE_LABEL[report.meeting_atmosphere] ?? ATMOSPHERE_LABEL.warm;
  const [editMode, setEditMode] = useState(false);
  const [draft, setDraft] = useState<RoadshowIntelReport>(report);

  function handleSave() {
    onSave?.(draft);
    setEditMode(false);
  }
  function handleCancel() {
    setDraft(report);
    setEditMode(false);
  }

  const cur = editMode ? draft : report;

  return (
    <div className="space-y-1 pb-8">
      {/* Header */}
      <div className="rounded-2xl border border-cyan/20 bg-gradient-to-b from-cyan/5 to-transparent p-5 mb-4">
        <div className="flex items-start justify-between mb-1">
          <p className="font-display text-[10px] uppercase tracking-[0.4em] text-cyan/60">路演情报报告</p>
          {onSave && !editMode && (
            <button
              type="button"
              onClick={() => setEditMode(true)}
              className="text-[10px] text-amber-400 hover:text-amber-300 border border-amber-400/30 rounded px-2 py-0.5 transition-colors"
            >
              ✏️ 编辑摘要
            </button>
          )}
          {editMode && (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleCancel}
                className="text-[10px] text-slate-400 hover:text-slate-300 border border-slate-400/30 rounded px-2 py-0.5 transition-colors"
              >
                取消
              </button>
              <button
                type="button"
                onClick={handleSave}
                disabled={saving}
                className="text-[10px] text-cyan-300 hover:text-cyan-200 border border-cyan-400/40 rounded px-2 py-0.5 transition-colors disabled:opacity-40"
              >
                {saving ? "保存中…" : "💾 保存"}
              </button>
            </div>
          )}
        </div>
        {interviewee && (
          <p className="text-xs text-slate-400 mb-3">
            路演场次：<span className="text-cyan/80">{interviewee}</span>
          </p>
        )}
        <div className="flex items-center gap-3 mb-3">
          <span className={`rounded-lg border px-3 py-1 text-sm font-bold ${atm.cls}`}>
            {atm.text}
          </span>
          <span className="rounded-lg border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-400">
            {STAGE_LABEL[cur.meeting_stage] ?? "阶段未知"}
          </span>
        </div>
        {editMode ? (
          <textarea
            className={TA}
            rows={4}
            value={draft.atmosphere_summary}
            onChange={(e) => setDraft((d) => ({ ...d, atmosphere_summary: e.target.value }))}
            placeholder="会议氛围综述"
          />
        ) : (
          <p className="text-sm text-slate-300 leading-relaxed">{cur.atmosphere_summary}</p>
        )}
      </div>

      {/* Key questions */}
      {cur.key_questions.length > 0 && (
        <>
          <SectionTitle>对方关键问题 ({cur.key_questions.length})</SectionTitle>
          <div className="space-y-2">
            {cur.key_questions.map((q, i) => (
              <QuestionCard key={i} q={q} idx={i} />
            ))}
          </div>
        </>
      )}

      {/* Signals */}
      {cur.interest_signals.length > 0 && (
        <>
          <SectionTitle>兴趣信号 ({cur.interest_signals.length})</SectionTitle>
          <div className="space-y-2">
            {cur.interest_signals.map((s, i) => (
              <SignalCard key={i} s={s} />
            ))}
          </div>
        </>
      )}

      {/* Hidden concerns */}
      {cur.hidden_concerns.length > 0 && (
        <>
          <SectionTitle>隐性顾虑{editMode && <span className="ml-2 text-[9px] text-slate-500 normal-case tracking-normal">（每行一条，保存后生效）</span>}</SectionTitle>
          <Card>
            {editMode ? (
              <textarea
                className={TA}
                rows={4}
                value={draft.hidden_concerns.join("\n")}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, hidden_concerns: e.target.value.split("\n").filter(Boolean) }))
                }
                placeholder="每行一条隐性顾虑"
              />
            ) : (
              <ul className="space-y-2">
                {cur.hidden_concerns.map((c, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-amber-200">
                    <span className="shrink-0 text-amber-400">⚠</span>
                    {c}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}

      {/* Key verbatim */}
      {cur.key_verbatim_moments.length > 0 && (
        <>
          <SectionTitle>关键原声</SectionTitle>
          <Card>
            <ul className="space-y-3">
              {cur.key_verbatim_moments.map((m, i) => (
                <li key={i} className="text-xs text-slate-200 leading-relaxed border-l-2 border-cyan/30 pl-3">
                  {m}
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}

      {/* Institution update */}
      {(cur.institution_update || editMode) && (
        <>
          <SectionTitle>机构档案更新建议</SectionTitle>
          <Card>
            {editMode ? (
              <textarea
                className={TA}
                rows={4}
                value={draft.institution_update ?? ""}
                onChange={(e) => setDraft((d) => ({ ...d, institution_update: e.target.value }))}
                placeholder="关于该机构新获取的洞察，用于更新档案"
              />
            ) : (
              <p className="text-xs text-slate-300 leading-relaxed">{cur.institution_update}</p>
            )}
          </Card>
        </>
      )}

      {/* Actions */}
      {cur.next_actions.length > 0 && (
        <>
          <SectionTitle>下一步行动 ({cur.next_actions.length})</SectionTitle>
          <div className="space-y-2">
            {cur.next_actions.map((a, i) => (
              <ActionCard key={i} a={a} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
