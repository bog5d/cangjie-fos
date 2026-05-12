/**
 * 参与人身份确认弹层（Phase 6.6）
 *
 * 触发条件：job 变为 completed 且 participants_confirmed = false
 * 弹层强制展示，不可不确认关闭（只能 skip — 打标但不写入）。
 */
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";

const VALID_ROLES = [
  "企业方创始人",
  "企业方高管",
  "企业方投融资",
  "GP执行",
  "LP投资方",
  "政府招商",
  "其他",
] as const;

type Role = (typeof VALID_ROLES)[number];

interface SpeakerSummary {
  speaker_id: string;
  sample_lines: string[];
  word_count: number;
}

interface ParticipantRow {
  speaker_id: string;
  real_name: string;
  institution: string;
  role: Role;
  title: string;
}

interface Props {
  jobId: string;
  interviewee?: string | null;
  tenantId: string;
  confirmedBy: string;
  /** 可传已知机构列表供 datalist 自动补全 */
  institutions?: string[];
  onConfirmed: () => void;
  onSkip: () => void;
}

export function ParticipantConfirmModal({
  jobId,
  interviewee,
  tenantId,
  confirmedBy,
  institutions = [],
  onConfirmed,
  onSkip,
}: Props) {
  const [speakers, setSpeakers] = useState<SpeakerSummary[]>([]);
  const [rows, setRows] = useState<ParticipantRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  // Esc 键 → 跳过（稍后确认）
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onSkip();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [busy, onSkip]);

  useEffect(() => {
    setLoading(true);
    api
      .get<SpeakerSummary[]>(`/api/v1/pitch/jobs/${jobId}/speaker-summary`)
      .then((r) => {
        setSpeakers(r.data);
        setRows(
          r.data.map((s) => ({
            speaker_id: s.speaker_id,
            real_name: "",
            institution: "",
            role: "其他" as Role,
            title: "",
          })),
        );
      })
      .catch(() => setErr("无法加载说话人信息，请刷新后重试"))
      .finally(() => setLoading(false));
  }, [jobId]);

  const updateRow = (idx: number, patch: Partial<ParticipantRow>) => {
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  };

  const handleConfirm = async () => {
    // 坑5：confirmedBy（指挥官名称）必填校验
    if (!confirmedBy.trim()) {
      setErr("⚠️ 请先在主界面顶部填写「指挥官名称」，否则无法记录确认人。");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await api.post(`/api/v1/pitch/jobs/${jobId}/participants`, {
        confirmed_by: confirmedBy.trim(),
        participants: rows,
      });
      onConfirmed();
    } catch {
      setErr("提交失败，请重试");
    } finally {
      setBusy(false);
    }
  };

  const listId = `institutions-${jobId}`;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center pointer-events-none"
    >
      {/* backdrop — 事件直接绑在有背景色的遮罩上，外层 wrapper 无 pointer-events
          避免 Chrome backdrop-filter 合成层 bug 造成透明遮罩拦截全页点击 */}
      <div
        className="absolute inset-0 bg-black/80 backdrop-blur-sm pointer-events-auto"
        onMouseDown={(e) => {
          if (cardRef.current && !cardRef.current.contains(e.target as Node)) {
            onSkip();
          }
        }}
      />

      <div
        ref={cardRef}
        className="relative w-full max-w-xl max-h-[90vh] flex flex-col rounded-2xl border border-cyan/30 bg-gradient-to-b from-[#070712] via-[#06061a] to-black shadow-[0_0_64px_rgba(34,211,238,0.2)] pointer-events-auto"
      >
        {/* header */}
        <div className="flex items-center justify-between border-b border-white/10 px-6 py-4">
          <div>
            <p className="font-display text-[10px] uppercase tracking-[0.4em] text-cyan/70">必填步骤</p>
            <h2 className="font-display text-lg font-semibold text-white">确认本场参与人身份</h2>
            {interviewee ? (
              <p className="mt-0.5 text-xs text-slate-400">
                路演记录：<span className="text-cyan/80">{interviewee}</span>
              </p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onSkip}
            disabled={busy}
            title="关闭（或按 Esc）"
            className="rounded-lg border border-white/20 bg-white/5 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:bg-white/10 hover:text-white"
          >
            ✕ 稍后确认
          </button>
        </div>

        {/* body */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {err}
            </p>
          ) : null}

          {loading ? (
            <p className="animate-pulse text-xs text-slate-500">加载说话人数据中…</p>
          ) : speakers.length === 0 ? (
            <p className="text-xs text-slate-500">未识别到说话人（文字稿可能无标记），可跳过此步。</p>
          ) : null}

          {/* datalist for institution autocomplete */}
          <datalist id={listId}>
            {institutions.map((inst) => (
              <option key={inst} value={inst} />
            ))}
          </datalist>

          {speakers.map((s, idx) => {
            const row = rows[idx];
            if (!row) return null;
            return (
              <div
                key={s.speaker_id}
                className="rounded-xl border border-white/10 bg-white/[0.03] p-4"
              >
                {/* speaker badge + samples */}
                <div className="mb-3 flex items-start gap-3">
                  <span className="shrink-0 rounded-lg border border-cyan/30 bg-cyan/10 px-2 py-1 font-display text-xs font-bold text-cyan">
                    说话人 {s.speaker_id}
                  </span>
                  <div className="flex flex-col gap-1">
                    {s.sample_lines.map((line, li) => (
                      <p key={li} className="text-[11px] leading-relaxed text-slate-400">
                        「{line}」
                      </p>
                    ))}
                    <p className="text-[10px] text-slate-600">共 {s.word_count} 条发言</p>
                  </div>
                </div>

                {/* form */}
                <div className="grid grid-cols-2 gap-2">
                  <label className="flex flex-col gap-1">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">姓名</span>
                    <input
                      type="text"
                      value={row.real_name}
                      onChange={(e) => updateRow(idx, { real_name: e.target.value })}
                      placeholder="王总、李局长…"
                      className="rounded-lg border border-white/10 bg-black/40 px-2 py-1.5 text-xs text-white outline-none focus:border-cyan/50"
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">职位</span>
                    <input
                      type="text"
                      value={row.title}
                      onChange={(e) => updateRow(idx, { title: e.target.value })}
                      placeholder="管理合伙人、招商局长…"
                      className="rounded-lg border border-white/10 bg-black/40 px-2 py-1.5 text-xs text-white outline-none focus:border-cyan/50"
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">所属机构</span>
                    <input
                      type="text"
                      list={listId}
                      value={row.institution}
                      onChange={(e) => updateRow(idx, { institution: e.target.value })}
                      placeholder="新川基金"
                      className="rounded-lg border border-white/10 bg-black/40 px-2 py-1.5 text-xs text-white outline-none focus:border-cyan/50"
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                      角色 <span className="text-rose-400">*</span>
                    </span>
                    <select
                      value={row.role}
                      onChange={(e) => updateRow(idx, { role: e.target.value as Role })}
                      className="rounded-lg border border-white/10 bg-black/40 px-2 py-1.5 text-xs text-white outline-none focus:border-cyan/50"
                    >
                      {VALID_ROLES.map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              </div>
            );
          })}
        </div>

        {/* footer */}
        <div className="border-t border-white/10 px-6 py-4 flex items-center justify-between">
          <p className="text-[11px] text-slate-600">
            确认后数据将写入复盘记录和机构档案
          </p>
          <button
            type="button"
            disabled={busy || loading || speakers.length === 0}
            onClick={() => void handleConfirm()}
            className="rounded-xl bg-gradient-to-r from-cyan/80 to-plasma/70 px-6 py-2 font-display text-xs font-bold uppercase tracking-widest text-white shadow-lg shadow-cyan/20 disabled:opacity-40"
          >
            {busy ? "提交中…" : "确认参与人"}
          </button>
        </div>
      </div>
    </div>
  );
}
