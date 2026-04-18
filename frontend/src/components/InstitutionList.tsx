import type { InstitutionProfile } from "../types/institution";

interface Props {
  tenantId: string;
  items: InstitutionProfile[];
}

const stageLabel: Record<string, string> = {
  targeted: "触达",
  pitched: "路演",
  dd: "尽调",
  term_sheet: "TS",
};

export function InstitutionList({ tenantId, items }: Props) {
  return (
    <section className="mt-8 rounded-3xl border border-white/10 bg-gradient-to-b from-white/[0.05] to-black/30 p-6 shadow-xl backdrop-blur-xl">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-display text-[10px] uppercase tracking-[0.35em] text-cyan/80">Phase 6</p>
          <h2 className="font-display text-lg font-bold text-white">机构 Pipeline 看板</h2>
          <p className="text-xs text-slate-500">tenant {tenantId}</p>
        </div>
        <span className="rounded-full border border-white/15 bg-white/5 px-3 py-1 font-mono text-[10px] text-slate-400">
          {items.length} active
        </span>
      </div>
      {items.length === 0 ? (
        <p className="text-sm text-slate-500">
          暂无机构卡片。上传路演录音并完成复盘后，系统将自动抽取「XX 资本」并推进漏斗。
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((it) => (
            <article
              key={it.institution_id}
              className="group rounded-2xl border border-cyan/20 bg-black/40 p-4 transition hover:border-plasma/40 hover:shadow-lg hover:shadow-plasma/10"
            >
              <div className="flex items-start justify-between gap-2">
                <h3 className="font-display text-base font-semibold text-white">{it.name}</h3>
                <span className="shrink-0 rounded-md bg-plasma/20 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-plasma-100">
                  {stageLabel[it.stage] ?? it.stage}
                </span>
              </div>
              <p className="mt-1 text-[10px] uppercase tracking-widest text-slate-500">
                thermal · <span className="text-cyan/90">{it.thermal}</span>
              </p>
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
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
