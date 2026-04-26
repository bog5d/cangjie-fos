import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api/client";
import { AchievementFlash } from "./components/AchievementFlash";
import { ExpHud } from "./components/ExpHud";
import { NPCPanel } from "./components/NPCPanel";
import { ScoreToastStack, type ScoreToastItem } from "./components/ScoreToast";
import { AssetLibrary } from "./components/AssetLibrary";
import { PitchJobHistory } from "./components/PitchJobHistory";
import { InstitutionList } from "./components/InstitutionList";
import { PitchUploadWizard } from "./components/PitchUploadWizard";
import { WarRoomMap } from "./components/WarRoomMap";
import type { DashboardStatus } from "./types/dashboard";
import type { InstitutionProfile } from "./types/institution";
import type { ReadyPayload } from "./types/ready";

const DEFAULT_TENANT = "demo-tenant";

export default function App() {
  const [dashboard, setDashboard] = useState<DashboardStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [toasts, setToasts] = useState<ScoreToastItem[]>([]);
  const [totalExp, setTotalExp] = useState(120);
  const [expHint, setExpHint] = useState("");
  const [achOpen, setAchOpen] = useState(false);
  const [institutions, setInstitutions] = useState<InstitutionProfile[]>([]);
  const [commanderName, setCommanderName] = useState("");
  const [wizardOpen, setWizardOpen] = useState(false);
  const [ready, setReady] = useState<ReadyPayload | null | undefined>(undefined);

  useEffect(() => {
    try {
      const v = localStorage.getItem("fos_commander_name");
      if (v) setCommanderName(v);
    } catch {
      /* ignore */
    }
  }, []);

  const persistCommander = useCallback((v: string) => {
    setCommanderName(v);
    try {
      localStorage.setItem("fos_commander_name", v);
    } catch {
      /* ignore */
    }
  }, []);

  const tenant = useMemo(() => {
    const q = new URLSearchParams(window.location.search).get("tenant");
    return q && q.length > 0 ? q : DEFAULT_TENANT;
  }, []);

  const uploadBlockedReason = useMemo(() => {
    if (ready === undefined) return "正在检查运行环境（/api/v1/ready）…";
    if (ready === null) return "无法获取就绪状态，请确认后端已启动。";
    if (!ready.pitch_coach_ok) {
      const hit = ready.issues.find((i) => i.code === "E_PITCH_COACH_SRC_MISSING");
      return hit?.fix_hint ?? "AI_Pitch_Coach 未正确放置，上传与豆区将不可用。";
    }
    if (!ready.api_keys_ok) {
      return "API 密钥未配置完整，请通过「填写API密钥_双击我」配置 backend/.env。";
    }
    return null;
  }, [ready]);

  const refreshWarData = useCallback(async () => {
    try {
      const [dash, inst] = await Promise.all([
        api.get<DashboardStatus>("/api/dashboard/status", { params: { tenant_id: tenant } }),
        api.get<InstitutionProfile[]>("/api/v1/pipeline/institutions", { params: { tenant_id: tenant } }),
      ]);
      setDashboard(dash.data);
      setInstitutions(inst.data);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [tenant]);

  useEffect(() => {
    void refreshWarData();
  }, [refreshWarData]);

  useEffect(() => {
    void api
      .get<ReadyPayload>("/api/v1/ready")
      .then((r) => setReady(r.data))
      .catch(() => setReady(null));
  }, []);

  useEffect(() => {
    if (!dashboard) return;
    if (dashboard.docs_health_pct < 80) return;
    try {
      const k = `fos_ach_docs80:${tenant}`;
      if (sessionStorage.getItem(k)) return;
      sessionStorage.setItem(k, "1");
      setAchOpen(true);
    } catch {
      setAchOpen(true);
    }
  }, [dashboard, tenant]);

  const pushToast = useCallback((delta: number, reason: string) => {
    const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    setToasts((t) => [...t, { id, delta, reason }]);
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts((t) => t.filter((x) => x.id !== id));
  }, []);

  const onExpEvent = useCallback(
    (delta: number, reason: string, hint?: string) => {
      setTotalExp((x) => Math.max(0, x + delta));
      setExpHint(hint ?? reason);
      pushToast(delta, reason);
    },
    [pushToast],
  );

  const demoDryRun = async () => {
    try {
      const { status } = await api.post("/api/pitch/run", {
        tenant_id: tenant,
        dry_run: true,
        words: [
          {
            word_index: 0,
            text: "测",
            start_time: 0,
            end_time: 0.1,
            speaker_id: "S1",
          },
        ],
      });
      if (status === 200) onExpEvent(5, "Dry-run 链路已打通");
      else onExpEvent(-2, "Dry-run 请求异常");
    } catch {
      onExpEvent(-3, "网络异常");
    }
  };

  return (
    <div className="min-h-screen px-4 pb-10 pt-6 md:px-10">
      {ready && !ready.ok ? (
        <div
          className="mb-4 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100"
          role="status"
        >
          <p className="font-semibold text-amber-200">环境未完全就绪</p>
          <ul className="mt-1 list-inside list-disc text-xs text-amber-100/90">
            {ready.issues
              .filter((i) => i.severity === "error" || i.code.startsWith("E_"))
              .slice(0, 5)
              .map((i) => (
                <li key={i.code + i.message}>
                  <span className="font-mono text-[10px] text-amber-300/90">{i.code}</span> — {i.message}
                </li>
              ))}
          </ul>
          <p className="mt-2 text-xs text-slate-400">详见仓库内 docs/RELEASE_CHECKLIST.md 或同事上手指南。</p>
        </div>
      ) : null}
      <AchievementFlash
        open={achOpen}
        title="资料健康度达标"
        subtitle="团队材料结构已跨过关键水位，继续保持迭代节奏。"
        onClose={() => setAchOpen(false)}
      />
      <ExpHud totalExp={totalExp} lastHint={expHint} />
      <ScoreToastStack items={toasts} onDone={dismissToast} />

      <header className="mb-8 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="font-display text-xs uppercase tracking-[0.4em] text-slate-500">
            CangJie FOS
          </p>
          <h1 className="font-display text-3xl font-bold text-white md:text-4xl">
            融资作战指挥台
          </h1>
          <p className="mt-2 max-w-xl text-sm text-slate-400">
            Phase 6：机构 Pipeline CRM · 路演情报自动落盘 · 战前简报 + 机构看板
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-slate-400">
            指挥官
            <input
              value={commanderName}
              onChange={(e) => persistCommander(e.target.value)}
              placeholder="称呼"
              className="w-28 rounded-lg border border-white/15 bg-black/40 px-2 py-1.5 text-sm text-white placeholder:text-slate-600"
            />
          </label>
          <button
            type="button"
            disabled={!!uploadBlockedReason}
            title={uploadBlockedReason ?? undefined}
            onClick={() => setWizardOpen(true)}
            className="rounded-xl border border-cyan/40 bg-cyan/10 px-4 py-2 font-display text-xs font-bold uppercase tracking-widest text-cyan hover:bg-cyan/20 disabled:cursor-not-allowed disabled:opacity-40"
          >
            复盘上传向导
          </button>
          <button
            type="button"
            onClick={() => onExpEvent(10, "资料补齐")}
            className="rounded-xl bg-gradient-to-r from-cyan/80 to-plasma/80 px-4 py-2 font-display text-xs font-bold uppercase tracking-widest text-white shadow-lg shadow-cyan/25 transition hover:brightness-110"
          >
            模拟 +10 分
          </button>
          <button
            type="button"
            onClick={() => void demoDryRun()}
            title="测试模式：不消耗 API，用固定数据验证系统链路是否正常"
            className="rounded-xl border border-white/20 bg-white/5 px-4 py-2 font-display text-xs font-bold uppercase tracking-widest text-slate-200 transition hover:border-cyan/50 hover:text-white"
          >
            Dry-run /api/pitch/run
          </button>
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
        <WarRoomMap
          dashboard={dashboard}
          loading={loading}
          error={err}
          tenantId={tenant}
          onRequestRefresh={() => void refreshWarData()}
        />
        <NPCPanel
          tenantId={tenant}
          onExpEvent={onExpEvent}
          onPipelineDataChanged={() => void refreshWarData()}
          userName={commanderName}
          onOpenWizard={() => setWizardOpen(true)}
        />
      </div>
      <InstitutionList tenantId={tenant} items={institutions} />
      <PitchJobHistory tenantId={tenant} />
      <AssetLibrary />
      <PitchUploadWizard
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        tenantId={tenant}
        userName={commanderName}
        onPipelineDataChanged={() => void refreshWarData()}
        uploadBlockedReason={uploadBlockedReason}
      />
    </div>
  );
}
