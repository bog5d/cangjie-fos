import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";

// ─── 类型 ─────────────────────────────────────────────────────────────────────

interface InstitutionSummary {
  institution: string;
  bundle_count: number;
  last_activity: number;
}

interface BundleRecord {
  session_id: string;
  created_at: number;
  req_text: string;
  files: { filename: string; relative_path: string; full_path: string }[];
}

interface InstitutionArchive {
  institution: string;
  bundle_count: number;
  total_sent_files: number;
  bundles: BundleRecord[];
}

interface InstitutionBriefing {
  institution: string;
  has_history: boolean;
  total_sessions: number;
  last_contact: number | null;
  preferred_tags: string[];
  gap_hints: string[];
}

// ─── 工具 ─────────────────────────────────────────────────────────────────────

function formatTs(ts: number): string {
  if (!ts) return "—";
  try { return new Date(ts * 1000).toISOString().slice(0, 10); } catch { return "—"; }
}

// ─── Wiki 预览区块 ────────────────────────────────────────────────────────────

function WikiPreview({ name }: { name: string }) {
  const [briefing, setBriefing] = useState<InstitutionBriefing | null>(null);

  useEffect(() => {
    void api.get<InstitutionBriefing>(
      `/api/v1/institutions/${encodeURIComponent(name)}/briefing`
    ).then(r => setBriefing(r.data)).catch(() => {/* 静默 */});
  }, [name]);

  if (!briefing?.has_history) return null;

  return (
    <div className="mb-4 rounded-xl border border-white/8 bg-white/[0.03] p-4">
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
        知识画像
      </p>
      <div className="space-y-2 text-xs">
        <div className="flex items-center gap-2 text-slate-400">
          <span>📊</span>
          <span>历史 {briefing.total_sessions} 次 DD · 最近接触 {formatTs(briefing.last_contact ?? 0)}</span>
        </div>
        {briefing.preferred_tags.length > 0 && (
          <div className="flex flex-wrap items-center gap-1">
            <span className="mr-0.5 text-slate-500">偏好：</span>
            {briefing.preferred_tags.map(t => (
              <span key={t} className="rounded border border-cyan-500/30 bg-cyan-950/20 px-1.5 py-0.5 text-[10px] text-cyan-400">
                {t}
              </span>
            ))}
          </div>
        )}
        {briefing.gap_hints.length > 0 && (
          <div className="flex flex-wrap items-center gap-1">
            <span className="mr-0.5 text-amber-500/70">⚠️ 缺口：</span>
            {briefing.gap_hints.map(g => (
              <span key={g} className="rounded border border-amber-500/30 bg-amber-950/20 px-1.5 py-0.5 text-[10px] text-amber-400">
                {g}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── 路演时间线 ──────────────────────────────────────────────────────────────

interface RoadshowJobRow {
  job_id: string;
  category: string;
  status: string;
  created_at: number;
  interviewee: string | null;
  institution_id: string;
}

const CATEGORY_LABEL: Record<string, string> = {
  "01_机构路演": "路演",
  "02_尽调": "尽调",
  "03_高管访谈": "高管访谈",
};

function InteractionTimeline({ name }: { name: string }) {
  const [jobs, setJobs] = useState<RoadshowJobRow[]>([]);
  const navigate = useNavigate();

  useEffect(() => {
    void api.get<RoadshowJobRow[]>(`/api/v1/institutions/${encodeURIComponent(name)}/jobs`)
      .then(r => setJobs(r.data))
      .catch(() => {/* 静默 */});
  }, [name]);

  if (jobs.length === 0) return null;

  return (
    <div className="mb-4">
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
        路演时间线 ({jobs.length})
      </p>
      <div className="space-y-1.5">
        {jobs.map((j) => (
          <button
            key={j.job_id}
            type="button"
            onClick={() => navigate(`/review/${j.job_id}`)}
            className="flex w-full items-center gap-2 rounded-lg border border-white/5 bg-black/20 px-3 py-2 text-left transition hover:border-cyan-500/20 hover:bg-cyan-950/10"
          >
            <span className="shrink-0 text-[9px] font-mono text-slate-600">{formatTs(j.created_at)}</span>
            <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[9px] font-bold ${
              j.status === "completed"
                ? "border-emerald-500/30 bg-emerald-950/20 text-emerald-400"
                : j.status === "failed"
                ? "border-rose-500/30 bg-rose-950/20 text-rose-400"
                : "border-slate-600/30 text-slate-500"
            }`}>
              {CATEGORY_LABEL[j.category] ?? (j.category || "未知")}
            </span>
            <span className="flex-1 truncate text-xs text-slate-300">
              {j.interviewee || j.job_id.slice(0, 12)}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── 机构详情面板 ─────────────────────────────────────────────────────────────

function InstitutionDetail({ name, onClose }: { name: string; onClose: () => void }) {
  const [archive, setArchive] = useState<InstitutionArchive | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void api.get<InstitutionArchive>(`/api/v1/institutions/${encodeURIComponent(name)}`)
      .then(r => setArchive(r.data))
      .finally(() => setLoading(false));
  }, [name]);

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="fixed inset-y-0 right-0 z-50 flex w-[28rem] max-w-[92vw] flex-col border-l border-white/10 bg-gray-950 shadow-2xl">
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
          <div>
            <p className="text-base font-semibold text-white">{name}</p>
            {archive && (
              <p className="mt-0.5 text-xs text-slate-500">
                {archive.bundle_count} 次打包 · {archive.total_sent_files} 个唯一文件
              </p>
            )}
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-500 hover:bg-white/10 hover:text-white">
            <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
              <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
            </svg>
          </button>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
          {/* Wiki 预览区块 */}
          <WikiPreview name={name} />
          {/* 路演时间线 */}
          <InteractionTimeline name={name} />

          {loading && <p className="text-center text-sm text-slate-500">加载中…</p>}
          {!loading && archive && archive.bundles.length === 0 && (
            <p className="text-center text-sm text-slate-600">暂无打包记录</p>
          )}
          {!loading && archive && archive.bundles.map(bundle => (
            <div key={bundle.session_id} className="rounded-xl border border-white/8 p-4">
              <div className="mb-2 flex items-center justify-between">
                <p className="text-xs font-medium text-slate-300">{formatTs(bundle.created_at)}</p>
                <span className="rounded border border-emerald-500/30 bg-emerald-950/30 px-1.5 py-0.5 text-[10px] text-emerald-400">
                  {bundle.files.length} 个文件
                </span>
              </div>
              {bundle.req_text && !bundle.req_text.startsWith("直接打包") && (
                <p className="mb-2 line-clamp-2 text-[11px] leading-relaxed text-slate-500">{bundle.req_text}</p>
              )}
              <div className="space-y-1">
                {bundle.files.map((f, i) => (
                  <p key={i} className="truncate text-xs text-slate-300">
                    <span className="mr-1.5 text-slate-600">·</span>{f.filename}
                  </p>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

// ─── 主面板 ───────────────────────────────────────────────────────────────────

export function InstitutionArchivePanel() {
  const [institutions, setInstitutions] = useState<InstitutionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    void api.get<{ institutions: InstitutionSummary[] }>("/api/v1/institutions")
      .then(r => setInstitutions(r.data.institutions))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) return (
    <section className="mt-8 rounded-2xl border border-white/10 bg-white/[0.03] p-6">
      <p className="text-sm text-slate-500">加载机构档案…</p>
    </section>
  );

  if (institutions.length === 0) return null;

  return (
    <section className="mt-8 rounded-2xl border border-white/10 bg-white/[0.03] p-6">
      <div className="mb-5">
        <h2 className="font-display text-lg font-bold text-white">机构档案</h2>
        <p className="mt-0.5 text-xs text-slate-500">
          {institutions.length} 个机构 · 点击查看知识画像和打包历史
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {institutions.map(inst => (
          <button
            key={inst.institution}
            type="button"
            onClick={() => setSelected(inst.institution)}
            className="rounded-xl border border-white/8 bg-white/[0.03] p-4 text-left transition hover:border-cyan-500/30 hover:bg-cyan-950/20"
          >
            <p className="truncate font-medium text-white">{inst.institution}</p>
            <p className="mt-1 text-xs text-slate-500">
              {inst.bundle_count} 次打包 · 最近 {formatTs(inst.last_activity)}
            </p>
          </button>
        ))}
      </div>

      {selected && (
        <InstitutionDetail name={selected} onClose={() => setSelected(null)} />
      )}
    </section>
  );
}
