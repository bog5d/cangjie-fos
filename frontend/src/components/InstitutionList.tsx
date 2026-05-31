import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { InstitutionProfile } from "../types/institution";

interface Props {
  tenantId: string;
  items: InstitutionProfile[];
  onUpdate?: (updated: InstitutionProfile) => void;
  onMilestonesChanged?: () => void;
}

interface PitchStat {
  institution: string;
  pitch_count: number;
  last_pitch_at: number | null;
}

const stageLabel: Record<string, string> = {
  targeted: "触达",
  pitched: "路演",
  dd: "尽调",
  term_sheet: "TS",
};

const thermalLabel: Record<string, string> = {
  hot: "🔥 热",
  warm: "☀️ 暖",
  cold: "❄️ 冷",
};

/** 将时间戳格式化为「X 天前」或「今天」 */
function daysAgo(ts: number | null | undefined): string {
  if (!ts) return "";
  const diffMs = Date.now() - ts * 1000;
  const days = Math.floor(diffMs / 86_400_000);
  if (days <= 0) return "今天";
  if (days === 1) return "昨天";
  return `${days} 天前`;
}

interface EditModalProps {
  item: InstitutionProfile;
  tenantId: string;
  onClose: () => void;
  onSaved: (updated: InstitutionProfile) => void;
}

function EditModal({ item, tenantId, onClose, onSaved }: EditModalProps) {
  const [draft, setDraft] = useState({
    ai_summary: item.ai_summary,
    concerns: item.concerns,
    preferences: item.preferences,
    stage: item.stage,
    thermal: item.thermal,
    contact_name: item.contact_name ?? "",
    contact_title: item.contact_title ?? "",
    valuation: item.valuation ?? "",
    deal_size: item.deal_size ?? "",
    probability: item.probability ?? 0,
    legal_status: item.legal_status ?? "",
    nda_signed: item.nda_signed ?? false,
    offline_meeting_count: item.offline_meeting_count ?? 0,
    project_approved: item.project_approved ?? false,
    committee_approved: item.committee_approved ?? false,
    onsite_dd_done: item.onsite_dd_done ?? false,
    external_dd_done: item.external_dd_done ?? false,
    agreement_signed: item.agreement_signed ?? false,
    deal_closed: item.deal_closed ?? false,
    referral_source: item.referral_source ?? "",
  });
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    setSaving(true);
    try {
      const { data } = await api.patch<InstitutionProfile>(
        `/api/v1/pipeline/institutions/${item.institution_id}`,
        draft,
        { params: { tenant_id: tenantId } },
      );
      onSaved(data);
      onClose();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "保存失败，请重试");
    } finally {
      setSaving(false);
    }
  }

  const input = "w-full bg-white/5 border border-white/15 rounded-lg px-3 py-1.5 text-sm text-white outline-none focus:border-cyan-400/50";
  const ta = `${input} resize-none`;
  const label = "block text-[11px] text-slate-400 mb-1";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="relative w-full max-w-lg rounded-2xl border border-white/15 bg-[#0d0d1a] p-6 shadow-2xl overflow-y-auto max-h-[90vh]">
        <h2 className="font-display text-sm font-bold text-white mb-4">编辑机构档案 — {item.name}</h2>
        <div className="space-y-4">
          <div>
            <label className={label}>综合画像（一句话摘要）</label>
            <textarea
              className={ta}
              rows={2}
              value={draft.ai_summary}
              onChange={(e) => setDraft((d) => ({ ...d, ai_summary: e.target.value }))}
              placeholder="对该机构的一句话综合描述"
            />
          </div>
          <div>
            <label className={label}>核心疑虑 / 追问焦点</label>
            <textarea
              className={ta}
              rows={2}
              value={draft.concerns}
              onChange={(e) => setDraft((d) => ({ ...d, concerns: e.target.value }))}
              placeholder="VC 反复追问的点，或主要顾虑"
            />
          </div>
          <div>
            <label className={label}>投资偏好</label>
            <textarea
              className={ta}
              rows={2}
              value={draft.preferences}
              onChange={(e) => setDraft((d) => ({ ...d, preferences: e.target.value }))}
              placeholder="该机构偏好的赛道、阶段、业务模型等"
            />
          </div>
          <div className="flex gap-4">
            <div className="flex-1">
              <label className={label}>Pipeline 阶段</label>
              <select
                className={input}
                value={draft.stage}
                onChange={(e) => setDraft((d) => ({ ...d, stage: e.target.value as InstitutionProfile["stage"] }))}
              >
                <option value="targeted">触达</option>
                <option value="pitched">路演</option>
                <option value="dd">尽调</option>
                <option value="term_sheet">TS</option>
              </select>
            </div>
            <div className="flex-1">
              <label className={label}>热度</label>
              <select
                className={input}
                value={draft.thermal}
                onChange={(e) => setDraft((d) => ({ ...d, thermal: e.target.value as InstitutionProfile["thermal"] }))}
              >
                <option value="hot">🔥 热</option>
                <option value="warm">☀️ 暖</option>
                <option value="cold">❄️ 冷</option>
              </select>
            </div>
          </div>
          <div className="flex gap-4">
            <div className="flex-1">
              <label className={label}>联系人姓名</label>
              <input
                className={input}
                value={draft.contact_name}
                onChange={(e) => setDraft((d) => ({ ...d, contact_name: e.target.value }))}
                placeholder="如：张总"
              />
            </div>
            <div className="flex-1">
              <label className={label}>职位</label>
              <input
                className={input}
                value={draft.contact_title}
                onChange={(e) => setDraft((d) => ({ ...d, contact_title: e.target.value }))}
                placeholder="如：合伙人"
              />
            </div>
          </div>
          <div className="flex gap-4">
            <div className="flex-1">
              <label className={label}>估值</label>
              <input
                className={input}
                value={draft.valuation}
                onChange={(e) => setDraft((d) => ({ ...d, valuation: e.target.value }))}
                placeholder="如：2亿"
              />
            </div>
            <div className="flex-1">
              <label className={label}>目标融资规模</label>
              <input
                className={input}
                value={draft.deal_size}
                onChange={(e) => setDraft((d) => ({ ...d, deal_size: e.target.value }))}
                placeholder="如：3000万"
              />
            </div>
          </div>
          <div>
            <label className={label}>成功概率：{draft.probability}%</label>
            <input
              type="range"
              min={0}
              max={100}
              value={draft.probability}
              onChange={(e) => setDraft((d) => ({ ...d, probability: Number(e.target.value) }))}
              className="w-full accent-cyan-400"
            />
          </div>
          <div>
            <label className={label}>法务进度</label>
            <input
              className={input}
              value={draft.legal_status}
              onChange={(e) => setDraft((d) => ({ ...d, legal_status: e.target.value }))}
              placeholder="如：NDA已签，等待TS草稿"
            />
          </div>
          <div>
            <label className={label}>引荐方/来源FA</label>
            <input
              className={input}
              value={draft.referral_source}
              onChange={(e) => setDraft((d) => ({ ...d, referral_source: e.target.value }))}
              placeholder="如：张 FA、李中介"
            />
          </div>
          <div>
            <label className={label}>线下会面次数</label>
            <input
              className={input}
              type="number"
              min={0}
              value={draft.offline_meeting_count}
              onChange={(e) => setDraft((d) => ({ ...d, offline_meeting_count: Number(e.target.value) }))}
            />
          </div>
          {/* 里程碑勾选 */}
          <div className="col-span-2">
            <label className={label}>融资里程碑</label>
            <div className="grid grid-cols-2 gap-2 mt-1">
              {([
                ["nda_signed", "NDA 已签"],
                ["project_approved", "已立项"],
                ["onsite_dd_done", "内部尽调完成"],
                ["external_dd_done", "外部尽调完成"],
                ["committee_approved", "投决会已过"],
                ["agreement_signed", "协议已签"],
                ["deal_closed", "交割完成"],
              ] as [keyof typeof draft, string][]).map(([key, lbl]) => (
                <label key={key} className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={!!draft[key]}
                    onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.checked }))}
                    className="accent-cyan-400 w-4 h-4"
                  />
                  {lbl}
                </label>
              ))}
            </div>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button
            type="button"
            onClick={onClose}
            className="text-xs text-slate-400 hover:text-slate-300 border border-white/10 rounded-lg px-4 py-1.5 transition-colors"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={saving}
            className="text-xs text-cyan-300 border border-cyan-400/40 bg-cyan-900/30 hover:bg-cyan-800/50 rounded-lg px-4 py-1.5 transition-colors disabled:opacity-40"
          >
            {saving ? "保存中…" : "💾 保存"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function InstitutionList({ tenantId, items, onUpdate, onMilestonesChanged }: Props) {
  const [pitchStats, setPitchStats] = useState<Map<string, PitchStat>>(new Map());
  const [editTarget, setEditTarget] = useState<InstitutionProfile | null>(null);
  const [localItems, setLocalItems] = useState<InstitutionProfile[]>(items);

  // Sync when parent items change
  useEffect(() => { setLocalItems(items); }, [items]);

  useEffect(() => {
    if (!tenantId) return;
    api
      .get<PitchStat[]>("/api/pitch/institution-stats", { params: { tenant_id: tenantId } })
      .then((r) => {
        const map = new Map<string, PitchStat>();
        for (const s of r.data) {
          map.set(s.institution, s);
        }
        setPitchStats(map);
      })
      .catch(() => {
        /* 不影响主界面 */
      });
  }, [tenantId]);

  function handleSaved(updated: InstitutionProfile) {
    setLocalItems((prev) => prev.map((it) => it.institution_id === updated.institution_id ? updated : it));
    onUpdate?.(updated);
    onMilestonesChanged?.();
  }

  return (
    <>
      <section className="mt-8 rounded-3xl border border-white/10 bg-gradient-to-b from-white/[0.05] to-black/30 p-6 shadow-xl backdrop-blur-xl">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="font-display text-[10px] uppercase tracking-[0.35em] text-cyan/80">Phase 6</p>
            <h2 className="font-display text-lg font-bold text-white">机构 Pipeline 看板</h2>
            <p className="text-xs text-slate-500">tenant {tenantId}</p>
          </div>
          <span className="rounded-full border border-white/15 bg-white/5 px-3 py-1 font-mono text-[10px] text-slate-400">
            {localItems.length} active
          </span>
        </div>
        {localItems.length === 0 ? (
          <p className="text-sm text-slate-500">
            暂无机构卡片。上传路演录音并完成复盘后，系统将自动抽取「XX 资本」并推进漏斗。
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {localItems.map((it) => {
              const stat = pitchStats.get(it.name);
              const isEmpty = !it.ai_summary && !it.concerns && !it.preferences;
              return (
                <article
                  key={it.institution_id}
                  onClick={() => setEditTarget(it)}
                  className="group rounded-2xl border border-cyan/20 bg-black/40 p-4 transition hover:border-amber-400/40 hover:shadow-lg hover:shadow-amber-400/10 cursor-pointer"
                >
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="font-display text-base font-semibold text-white">{it.name}</h3>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <span className="rounded-md bg-plasma/20 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-plasma-100">
                        {stageLabel[it.stage] ?? it.stage}
                      </span>
                      <span className="text-[10px] opacity-0 group-hover:opacity-100 text-amber-400/80 transition-opacity">✏️</span>
                    </div>
                  </div>

                  {/* 路演次数 + 热度 + 最近路演 */}
                  <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5">
                    <p className="text-[10px] uppercase tracking-widest text-slate-500">
                      {thermalLabel[it.thermal] ?? it.thermal}
                    </p>
                    {stat && stat.pitch_count > 0 ? (
                      <p className="text-[10px] text-slate-500">
                        ·{" "}
                        <span className="font-semibold text-cyan/80">{stat.pitch_count} 次路演</span>
                        {stat.last_pitch_at ? (
                          <span className="text-slate-600"> · 最近 {daysAgo(stat.last_pitch_at)}</span>
                        ) : null}
                      </p>
                    ) : null}
                  </div>

                  {it.ai_summary ? (
                    <p className="mt-2 line-clamp-2 text-xs text-slate-300">{it.ai_summary}</p>
                  ) : null}
                  {it.concerns ? (
                    <p className="mt-2 border-t border-white/5 pt-2 text-[11px] leading-snug text-amber-100/90">
                      <span className="font-bold text-ember/90">疑虑 </span>
                      {it.concerns}
                    </p>
                  ) : null}
                  {it.preferences ? (
                    <p className="mt-1 text-[11px] text-slate-400">
                      <span className="font-bold text-cyan/80">偏好 </span>
                      {it.preferences}
                    </p>
                  ) : null}
                  {isEmpty && (
                    <p className="mt-2 text-[11px] text-slate-600 italic">
                      暂无摘要 · 点击编辑机构画像
                    </p>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </section>

      {editTarget && (
        <EditModal
          item={editTarget}
          tenantId={tenantId}
          onClose={() => setEditTarget(null)}
          onSaved={handleSaved}
        />
      )}
    </>
  );
}
